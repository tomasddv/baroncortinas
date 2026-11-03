"""Cotizador de cortinas a medida — tienda web y administración privada."""
import hmac
import json
import math
import os
import re
import secrets
import uuid
from datetime import datetime, timezone
from io import BytesIO

from flask import Flask, Response, abort, flash, jsonify, redirect, render_template, request, send_file, session, url_for
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from storage import StorageError, load_catalog, read_image, remote_enabled, save_catalog, save_image, storage_label
from manufacturing import bp as manufacturing_bp, calculate_hardware
from marketing import bp as marketing_bp

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or (secrets.token_hex(32) if not os.environ.get("RENDER") else None),
    MAX_CONTENT_LENGTH=10 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")),
)
if not app.config['SECRET_KEY']:
    raise RuntimeError("En Render es obligatorio configurar SECRET_KEY")
app.register_blueprint(manufacturing_bp)
app.register_blueprint(marketing_bp)
serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="cotizador-presupuesto-v1")
PRODUCTS = {
    "blackout": {"name": "Roller Blackout", "subtitle": "Oscuridad total y privacidad", "families": ["blackout"]},
    "sunscreen": {"name": "Roller Sun Screen", "subtitle": "Luz equilibrada sin perder estilo", "families": ["sunscreen"]},
    "doble": {"name": "Roller Doble", "subtitle": "Blackout + Sun Screen, control total", "families": ["blackout", "sunscreen"]},
    "tela": {"name": "Cortina de Tela", "subtitle": "Textiles, caída y calidez", "families": ["tela"]},
}


def number(raw, name, minimum, maximum):
    try:
        n = float(raw)
    except (ValueError, TypeError):
        raise ValueError(f"{name}: ingresá un número válido")
    if not math.isfinite(n) or not minimum <= n <= maximum:
        raise ValueError(f"{name}: valor permitido entre {minimum} y {maximum}")
    return n


def as_int(n):
    return int(round(n))


def price_quote(cfg, body):
    """All prices and allowed product options are resolved on the server."""
    settings = cfg["settings"]
    kind = body.get("kind")
    if kind not in PRODUCTS:
        raise ValueError("Seleccioná un tipo de cortina")
    w = number(body.get("width_cm"), "Ancho", settings.get("min_width_cm", 30), settings.get("max_width_cm", 300))
    h = number(body.get("height_cm"), "Alto", settings.get("min_height_cm", 30), settings.get("max_height_cm", 300))
    qty = int(number(body.get("quantity", 1), "Cantidad", 1, 30))
    if qty != number(body.get("quantity", 1), "Cantidad", 1, 30):
        raise ValueError("La cantidad debe ser un número entero")
    mount = body.get("mount", "Pared")
    if mount not in ("Pared", "Techo"):
        raise ValueError("Tipo de colocación inválido")
    drop = body.get("drop", "Detrás")
    if drop not in ("Detrás", "Delante"):
        raise ValueError("Caída del rollo inválida")
    side = body.get("side", "Derecha")
    if side not in ("Derecha", "Izquierda"):
        raise ValueError("Posición del mando inválida")
    chain = body.get("chain", "Plástica")
    chain_costs = settings.get("chain_costs", {})
    if chain not in chain_costs:
        raise ValueError("Tipo de cadena inválido")
    pleat = body.get("pleat", "Fruncida")
    pleat_multipliers = settings.get("traditional_pleat_multiplier", {"Fruncida":1.8,"Onda perfecta":2.2})
    if pleat not in pleat_multipliers:
        raise ValueError("Confección inválida")
    items = body.get("selections", {})
    if not isinstance(items, dict):
        raise ValueError("Seleccioná las telas")
    required_families = PRODUCTS[kind]["families"]
    all_materials = {m["id"]: m for m in cfg["materials"] if m.get("active", True)}
    selected = []
    consumption = []
    fabric_cost = 0.0
    for fam in required_families:
        selection = items.get(fam)
        if not isinstance(selection, dict):
            raise ValueError(f"Elegí la tela {fam}")
        material = all_materials.get(selection.get("material_id"))
        if not material or material.get("family") != fam:
            raise ValueError(f"Material {fam} no disponible")
        color = next((c for c in material.get("colors", []) if c["id"] == selection.get("color_id")), None)
        if not color:
            raise ValueError(f"Elegí un color válido para {material['name']}")
        extra_w = number(settings.get("waste_width_cm",0), "Extra de ancho", 0, 300)
        extra_h = number(settings.get("waste_height_cm",0), "Extra de alto", 0, 300)
        reduction = number(settings.get("roller_fabric_narrower_cm",0), "Descuento de tela", 0, 20)
        if kind == "tela":
            cut_width = w * float(pleat_multipliers[pleat]) + extra_w
            cut_height = h + extra_h
        else:
            cut_width = w - reduction + extra_w
            cut_height = h + extra_h
        if cut_width <= 0:
            raise ValueError("El ancho de corte no puede ser cero")
        if kind != "tela" and cut_width > float(material.get("roll_width_cm",300)):
            raise ValueError(f"{material['name']}: el ancho excede el rollo disponible ({material.get('roll_width_cm')} cm)")
        waste_pct = number(settings.get("waste_pct",0), "Desperdicio general", 0, 80) + number(material.get("waste_pct", 0), "Desperdicio de tela", 0, 80)
        area_m2 = cut_width * cut_height / 10000
        # Price unit is a supplier cost unit, not the retail unit.
        if material["price_unit"] == "metro_lineal":
            if kind != "tela" and cut_width > float(material.get("roll_width_cm", 300)):
                raise ValueError(f"{material['name']}: ancho de corte {cut_width:.1f} cm supera el rollo de {material.get('roll_width_cm')} cm")
            # Traditional curtains need multiple panels if combined width exceeds roll width.
            panels = max(1, math.ceil(cut_width / float(material.get("roll_width_cm", 300))))
            billable_linear_m = max(0.5, (cut_height/100) * panels * (1 + waste_pct/100))
            material_cost = billable_linear_m * float(color.get("price_override", material["price"]))
            estimated_qty = billable_linear_m
            estimated_unit = "m lineales"
        else:
            billable_m2 = max(float(settings.get("min_billable_m2",1)), area_m2 * (1+waste_pct/100))
            material_cost = billable_m2 * float(color.get("price_override", material["price"]))
            estimated_qty = billable_m2
            estimated_unit = "m²"
        fabric_cost += material_cost
        selected.append({"family":fam,"material_id":material["id"],"material":material["name"],"color_id":color["id"],"color":color["name"]})
        consumption.append({"material":material["name"],"quantity":round(estimated_qty,3),"unit":estimated_unit,"waste_pct":waste_pct,"cut_width_cm":round(cut_width,1),"cut_height_cm":round(cut_height,1)})
    hardware, component_lines, recipe_used = calculate_hardware(
        cfg, kind, w, h, chain, chain_costs, mount=mount, drop=drop, side=side, pleat=pleat)
    total_cost = fabric_cost + hardware
    markup = number(settings.get("markup_pct",0), "Recargo de venta", 0, 1000)
    unit_price = as_int(total_cost * (1 + markup/100))
    if unit_price <= 0:
        raise ValueError("No se puede cotizar una cortina sin precios configurados")
    result = {
        "kind":kind,"product":PRODUCTS[kind]["name"],"width_cm":w,"height_cm":h,
        "quantity":qty,"mount":mount,"drop":drop,"side":side,"chain":chain,"pleat":pleat,
        "selections":selected,"unit_price":unit_price,"total":unit_price*qty,
        "currency":settings.get("currency","ARS"),
        "reference":uuid.uuid4().hex[:8].upper(),
        "created_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return result, {"cost_per_unit":round(total_cost,2),"consumption":consumption,"fabric_cost":round(fabric_cost,2),"hardware_cost":round(hardware,2),"components":component_lines,"recipe_used":recipe_used}


def admin_ok():
    return bool(session.get("admin_auth"))


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]

@app.context_processor
def inject_common():
    return {"csrf_token":csrf_token, "products":PRODUCTS, "brand_settings":load_catalog()["settings"], "is_admin":admin_ok()}

@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; media-src 'self' https:; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if request.path.startswith("/admin"):
        response.headers["Cache-Control"] = "no-store"
    return response

@app.before_request
def admin_guards():
    if request.path.startswith("/admin") and request.method == "POST":
        provided = request.form.get("csrf", "")
        expected = session.get("csrf", "")
        if not expected or not hmac.compare_digest(provided, expected):
            abort(403)
    if request.path.startswith("/admin") and request.path not in ("/admin/login",) and not admin_ok():
        return redirect(url_for("admin_login", next=request.path))

@app.get("/tema.css")
def theme_css():
    settings=load_catalog()["settings"]
    colors=[]
    for key,default in (("primary_color","#292724"),("accent_color","#aa8666"),("background_color","#faf7f1")):
        val=settings.get(key,default)
        if not isinstance(val,str) or not re.fullmatch(r"#[a-fA-F0-9]{6}",val):
            val=default
        colors.append(val)
    primary,accent,bg=colors
    css=f":root{{--forest:{primary};--forest2:{primary};--terracotta:{accent};--ivory:{bg};--milk:#fffdfa;--sand:#f0ebe4;--text:#302d29;--muted:#77716a;--stroke:#e8e0d7;}}"
    return Response(css,mimetype="text/css",headers={"Cache-Control":"no-store"})

@app.get("/health")
def health():
    return {"ok":True}

@app.get("/")
def home():
    cfg = load_catalog()
    return render_template("home.html", settings=cfg["settings"], materials=cfg["materials"])

@app.get("/carrito")
def cart():
    cfg = load_catalog()
    return render_template("cart.html", settings=cfg["settings"])

@app.get("/cotizar/<kind>")
def configurator(kind):
    if kind not in PRODUCTS:
        abort(404)
    cfg = load_catalog()
    compatible = [m for m in cfg["materials"] if m.get("active",True) and m["family"] in PRODUCTS[kind]["families"]]
    return render_template("configurador.html",settings=cfg["settings"],kind=kind,material_list=compatible,public_settings={k:cfg["settings"].get(k) for k in ("min_width_cm","max_width_cm","min_height_cm","max_height_cm","measurement_note")})

@app.post("/api/cotizar")
def quote_api():
    if request.content_length and request.content_length>10000:
        return jsonify(error="Solicitud demasiado grande"),413
    body = request.get_json(silent=True)
    if not isinstance(body,dict):
        return jsonify(error="Datos inválidos"),400
    try:
        result, _ = price_quote(load_catalog(),body)
        # A signed reference demonstrates that the displayed amount was issued by the server.
        result["token"] = serializer.dumps(result)
        return jsonify(result)
    except (ValueError,KeyError,TypeError,StorageError) as e:
        return jsonify(error=str(e)),400

@app.post("/api/verificar")
def verify_quote():
    body=request.get_json(silent=True) or {}
    try:
        data=serializer.loads(body.get("token",""),max_age=7*24*3600)
        return jsonify(data)
    except (BadSignature,SignatureExpired):
        return jsonify(error="La cotización caducó o es inválida"),400

@app.post("/api/armar-pedido")
def checkout_api():
    """Verify signed server quotes, recalculate with current catalogue, then build WhatsApp URL.
    No customer data or orders are written to GitHub.
    """
    import urllib.parse
    body=request.get_json(silent=True)
    if not isinstance(body,dict):
        return jsonify(error="Datos de pedido inválidos"),400
    tokens=body.get("tokens")
    name=str(body.get("name","")).strip()[:120]
    city=str(body.get("city","")).strip()[:120]
    if not name or not city or not isinstance(tokens,list) or not 1<=len(tokens)<=20:
        return jsonify(error="Ingresá nombre y localidad y agregá al menos una cortina"),400
    cfg=load_catalog()
    phone=re.sub(r"\D","",cfg["settings"].get("whatsapp",""))
    if not (8<=len(phone)<=15):
        return jsonify(error="El comercio debe configurar su WhatsApp en Administración"),400
    orders=[]
    try:
        for token in tokens:
            original=serializer.loads(token,max_age=2*24*3600)
            choices={item["family"]:{"material_id":item["material_id"],"color_id":item["color_id"]} for item in original["selections"]}
            data={field:original[field] for field in ("kind","width_cm","height_cm","quantity","mount","drop","side","chain","pleat")}
            data["selections"]=choices
            fresh,_=price_quote(cfg,data)
            orders.append(fresh)
    except (BadSignature,SignatureExpired,KeyError,TypeError,ValueError) as exc:
        return jsonify(error="Una cotización venció o cambió. Volvé a configurar la cortina."),400
    rows=[f"Hola, soy {name}. Quiero solicitar un presupuesto a medida.",f"Localidad: {city}",""]
    for index,quote in enumerate(orders,1):
        rows.extend([f"{index}) {quote['product']}",f"{quote['width_cm']:g} × {quote['height_cm']:g} cm · {quote['quantity']} unidad(es)",
            "Materiales: "+", ".join(x["material"]+" / "+x["color"] for x in quote["selections"]),
            "Colocación: "+quote["mount"],
            "Confección: "+quote["pleat"] if quote["kind"]=="tela" else "Caída: "+quote["drop"]+" · Mando: "+quote["side"]+" · Cadena: "+quote["chain"],
            f"Valor orientativo: $ {quote['total']:,.0f}".replace(",","."),""])
    total=sum(x["total"] for x in orders)
    rows.extend([f"TOTAL ORIENTATIVO: $ {total:,.0f}".replace(",","."),
                 "Pedido sujeto a confirmación de medidas, disponibilidad, entrega y forma de pago."])
    msg="\n".join(rows)
    return jsonify(url="https://wa.me/"+phone+"?"+urllib.parse.urlencode({"text":msg}),total=total)

@app.get("/media/<key>")
def material_image(key):
    if not re.fullmatch(r"[a-zA-Z0-9_-]+\.(png|jpg|jpeg|webp|mp4)",key):
        abort(404)
    try:
        raw=read_image(key)
    except (FileNotFoundError,StorageError):
        abort(404)
    mimetype="video/mp4" if key.endswith("mp4") else "image/png" if key.endswith("png") else "image/webp" if key.endswith("webp") else "image/jpeg"
    return send_file(BytesIO(raw), mimetype=mimetype, max_age=300, conditional=True)

@app.route("/admin/login",methods=["GET","POST"])
def admin_login():
    if request.method=="POST":
        expected=os.environ.get("ADMIN_PASSWORD","")
        given=request.form.get("password", "")
        if expected and hmac.compare_digest(given,expected):
            session.clear()
            session["admin_auth"]=True
            csrf_token()
            return redirect(url_for("admin"))
        flash("Contraseña incorrecta o ADMIN_PASSWORD no configurada", "error")
    return render_template("login.html",configured=bool(os.environ.get("ADMIN_PASSWORD")))

@app.post("/admin/salir")
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.get("/admin")
def admin():
    cfg=load_catalog()
    return render_template("admin.html",settings=cfg["settings"],materials=cfg["materials"],storage=storage_label(),persistent=remote_enabled() or not bool(os.environ.get("RENDER")))

@app.get("/admin/exportar")
def admin_export():
    output=json.dumps(load_catalog(),ensure_ascii=False,indent=2).encode("utf-8")
    return send_file(BytesIO(output),mimetype="application/json",as_attachment=True,download_name="catalogo-cortinas.json")

@app.get("/admin/simulador")
def admin_cost_preview():
    cfg=load_catalog()
    kind=request.args.get("kind", "blackout")
    if kind not in PRODUCTS:
        kind="blackout"
    try:
        width=number(request.args.get("width_cm",120), "Ancho", 30, 300)
        height=number(request.args.get("height_cm",150), "Alto", 30, 300)
        selections={}
        for fam in PRODUCTS[kind]["families"]:
            available=[m for m in cfg["materials"] if m.get("active",True) and m["family"]==fam and m.get("colors")]
            if not available:
                raise ValueError("No hay materiales activos para " + fam)
            material=available[0]
            selections[fam]={"material_id":material["id"],"color_id":material["colors"][0]["id"]}
        choices={
            "mount":request.args.get("mount", "Pared"),
            "drop":request.args.get("drop", "Detrás"),
            "side":request.args.get("side", "Derecha"),
            "chain":request.args.get("chain", "Plástica"),
            "pleat":request.args.get("pleat", "Fruncida"),
        }
        quote, detail=price_quote(cfg,{"kind":kind,"width_cm":width,"height_cm":height,"quantity":1,
            "selections":selections,**choices})
        error=None
    except (ValueError,KeyError,TypeError,StorageError) as exc:
        quote,detail,error=None,None,str(exc)
    return render_template("despiece.html",models=PRODUCTS,kind=kind,width=request.args.get("width_cm",120),
        height=request.args.get("height_cm",150),quote=quote,detail=detail,error=error,
        choices={key:request.args.get(key,default) for key,default in
                 (("mount","Pared"),("drop","Detrás"),("side","Derecha"),("chain","Plástica"),("pleat","Fruncida"))},
        available_choices={"mount":["Pared","Techo"],"drop":["Detrás","Delante"],
                           "side":["Izquierda","Derecha"],
                           "chain":list(cfg["settings"].get("chain_costs",{})),
                           "pleat":list(cfg["settings"].get("traditional_pleat_multiplier",{}))})

@app.post("/admin/logo")
def upload_brand_logo():
    cfg=load_catalog()
    photo=request.files.get("logo")
    if not photo or not photo.filename:
        flash("Seleccioná una imagen de logo", "error")
        return redirect(url_for("admin")+"#identidad")
    raw=photo.read()
    ext=("png" if raw.startswith(b"\x89PNG\r\n\x1a\n") else
         "jpg" if raw.startswith(b"\xff\xd8\xff") else
         "webp" if raw[:4]==b"RIFF" and raw[8:12]==b"WEBP" else None)
    if not ext or not (1<=len(raw)<=1_500_000):
        flash("El logo debe ser PNG, JPG o WEBP de menos de 1,5 MB", "error")
        return redirect(url_for("admin")+"#identidad")
    try:
        key="baron-logo-"+uuid.uuid4().hex+"."+ext
        save_image(key,raw)
        cfg["settings"]["brand_logo"]=key
        save_catalog(cfg)
        flash("Logo BARÓN actualizado correctamente", "success")
    except StorageError as exc:
        flash(str(exc),"error")
    return redirect(url_for("admin")+"#identidad")

@app.post("/admin/configuracion")
def save_settings():
    cfg=load_catalog()
    f=request.form
    fields={"brand":str,"tagline":str,"whatsapp":str,"shipping_message":str,"measurement_note":str,
        "primary_color":str,"accent_color":str,"background_color":str,
        "markup_pct":float,"waste_pct":float,"waste_width_cm":float,"waste_height_cm":float,
        "roller_fabric_narrower_cm":float,"min_billable_m2":float,
        "base_hardware_cost":float,"double_hardware_cost":float,"traditional_hardware_cost":float,
        "min_width_cm":float,"max_width_cm":float,"min_height_cm":float,"max_height_cm":float}
    try:
        for key,converter in fields.items():
            if key in f:
                value=converter(f[key].strip()) if converter==str else number(f[key],key,0,1_000_000)
                cfg["settings"][key]=value[:500] if isinstance(value,str) else value
        for color_key in ("primary_color","accent_color","background_color"):
            if not re.fullmatch(r"#[0-9a-fA-F]{6}",cfg["settings"].get(color_key,"")):
                raise ValueError(f"Color inválido: {color_key}. Usá #RRGGBB")
        whatsapp=re.sub(r"\D","",cfg["settings"].get("whatsapp",""))
        if whatsapp and not (8<=len(whatsapp)<=15):
            raise ValueError("WhatsApp debe incluir código de país y número, entre 8 y 15 dígitos")
        cfg["settings"]["whatsapp"]=whatsapp
        for k in cfg["settings"].get("chain_costs", {}):
            val=f.get("chain_"+k)
            if val is not None:
                cfg["settings"]["chain_costs"][k]=number(val,k,0,1_000_000_000)
        for k in cfg["settings"].get("traditional_pleat_multiplier", {}):
            val=f.get("pleat_"+k)
            if val is not None:
                cfg["settings"]["traditional_pleat_multiplier"][k]=number(val,k,1,5)
        if cfg["settings"]["max_width_cm"]<cfg["settings"]["min_width_cm"] or cfg["settings"]["max_height_cm"]<cfg["settings"]["min_height_cm"]:
            raise ValueError("El máximo de medidas debe ser mayor que el mínimo")
        save_catalog(cfg)
        flash("Configuración guardada correctamente", "success")
    except (StorageError,ValueError) as exc:
        flash(str(exc),"error")
    return redirect(url_for("admin")+"#fabricacion")


def parse_colors(raw):
    colors=[]
    for line in raw.splitlines():
        line=line.strip()
        if not line: continue
        parts=[p.strip() for p in line.split("|")]
        if len(parts)!=2 or not re.fullmatch(r"#[0-9a-fA-F]{6}",parts[1]) or not 1<=len(parts[0])<=50:
            raise ValueError("Formato de colores: Nombre | #RRGGBB (uno por línea)")
        uid=re.sub(r"[^a-z0-9]+","-",parts[0].lower()).strip("-") or uuid.uuid4().hex[:6]
        if any(c["id"]==uid for c in colors):
            raise ValueError("Los colores deben tener nombres distintos")
        colors.append({"id":uid,"name":parts[0],"hex":parts[1]})
    if not colors:
        raise ValueError("Cargá al menos un color")
    return colors

@app.route("/admin/material/nuevo",methods=["GET","POST"])
@app.route("/admin/material/<material_id>",methods=["GET","POST"])
def material_editor(material_id=None):
    cfg=load_catalog()
    existing=next((m for m in cfg["materials"] if m["id"]==material_id),None)
    if material_id and not existing:abort(404)
    if request.method=="GET":
        return render_template("material.html", material=existing,storage=storage_label())
    f=request.form
    try:
        name=f.get("name","").strip()
        family=f.get("family","")
        if not name or len(name)>90:raise ValueError("Ingresá un nombre de hasta 90 caracteres")
        if family not in ("blackout","sunscreen","tela"):raise ValueError("Familia inválida")
        if f.get("price_unit") not in ("m2","metro_lineal"):
            raise ValueError("Unidad de precio inválida")
        colors=parse_colors(f.get("colors",""))
        # Preserve photos and individual prices when editing the list of colour names.
        previous_colors={c["id"]:c for c in (existing or {}).get("colors", [])}
        for color in colors:
            previous=previous_colors.get(color["id"], {})
            for key in ("photo", "price_override"):
                if key in previous:
                    color[key]=previous[key]
        material=dict(existing or {})
        material.update({"id":(existing or {}).get("id") or "mat-"+uuid.uuid4().hex[:10],
            "name":name,"family":family,"description":f.get("description","").strip()[:300],
            "price":number(f.get("price"),"Precio",0,1_000_000_000),
            "price_unit":f.get("price_unit"),
            "roll_width_cm":number(f.get("roll_width_cm"),"Ancho del rollo",20,600),
            "waste_pct":number(f.get("waste_pct",0),"Desperdicio material",0,80),
            "active":bool(f.get("active")),"colors":colors,"photo":material.get("photo","")})
        photo=request.files.get("photo")
        if photo and photo.filename:
            raw=photo.read()
            valid=(raw.startswith(b"\xff\xd8\xff") and "jpg") or (raw.startswith(b"\x89PNG\r\n\x1a\n") and "png") or (raw[:4]==b"RIFF" and raw[8:12]==b"WEBP" and "webp")
            if not valid or not 1<=len(raw)<=1_500_000:
                raise ValueError("La imagen debe ser JPG, PNG o WEBP y ocupar menos de 1,5 MB")
            key=uuid.uuid4().hex+"."+valid
            save_image(key,raw)
            material["photo"]=key
        if existing:
            cfg["materials"]=[material if m["id"]==material_id else m for m in cfg["materials"]]
        else:
            cfg["materials"].append(material)
        save_catalog(cfg)
        flash(f"Material «{name}» guardado", "success")
        return redirect(url_for("admin")+"#catalogo")
    except (ValueError,StorageError) as exc:
        flash(str(exc),"error")
        return render_template("material.html",material=existing,storage=storage_label()),400

@app.post("/admin/material/<material_id>/eliminar")
def material_delete(material_id):
    cfg=load_catalog()
    cfg["materials"]=[m for m in cfg["materials"] if m["id"]!=material_id]
    try:
        save_catalog(cfg)
        flash("Material eliminado del catálogo (la imagen previa queda en el repositorio)","success")
    except StorageError as exc:
        flash(str(exc),"error")
    return redirect(url_for("admin")+"#catalogo")

@app.errorhandler(413)
def too_large(_):
    return "Archivo demasiado grande: máximo 3 MB por solicitud",413

if __name__ == "__main__":
    app.run(debug=not bool(os.environ.get("RENDER")),port=int(os.environ.get("PORT",5000)))
