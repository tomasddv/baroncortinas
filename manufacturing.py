"""Editable manufacturing bill of materials and per-colour fabric photographs.

All cost calculations are server-side. Legacy flat hardware costs remain in use
until a model has at least one recipe line, preventing silent price changes.
"""
import math
import re
import uuid

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from storage import StorageError, load_catalog, save_catalog, save_image, storage_label

bp = Blueprint("manufacturing", __name__)
PRODUCT_LABELS = {
    "blackout": "Roller Blackout",
    "sunscreen": "Roller Sun Screen",
    "doble": "Roller Doble",
    "tela": "Cortina de Tela",
}
MODES = {
    "fijo": "Cantidad fija por cortina",
    "ancho_m": "Por metro de ancho",
    "alto_m": "Por metro de alto",
    "perimetro_m": "Por metro de perímetro",
    "area_m2": "Por m² de cortina",
    "cada_50cm_ancho": "Por cada 50 cm de ancho (redondea arriba)",
    "cada_100cm_ancho": "Por cada 100 cm de ancho (redondea arriba)",
}
UNITS = {"unidad": "Unidad", "metro": "Metro", "m2": "Metro cuadrado"}


def numeric(raw, label, minimum=0, maximum=1_000_000_000):
    try:
        value = float(raw)
    except (ValueError, TypeError):
        raise ValueError(f"{label}: ingresá un número válido")
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{label}: valor permitido entre {minimum} y {maximum}")
    return value


def calculate_hardware(cfg, kind, width_cm, height_cm, chain, chain_costs):
    """Return (cost, itemized lines, recipe_used) for one finished curtain."""
    recipe = cfg.get("recipes", {}).get(kind) or []
    components = {item["id"]: item for item in cfg.get("components", [])}
    lines = []
    if recipe:
        for item in recipe:
            component = components.get(item.get("component_id"))
            if not component or not component.get("active", True):
                raise ValueError("La receta de fabricación contiene un insumo inexistente o inactivo. Revisá Administración.")
            mode = item.get("mode", "fijo")
            factor = numeric(item.get("factor", 1), "Cantidad de insumo", 0, 100000)
            waste = numeric(item.get("waste_pct", 0), "Merma del insumo", 0, 80)
            if mode == "fijo":
                base = 1
            elif mode == "ancho_m":
                base = width_cm / 100
            elif mode == "alto_m":
                base = height_cm / 100
            elif mode == "perimetro_m":
                base = 2 * (width_cm + height_cm) / 100
            elif mode == "area_m2":
                base = width_cm * height_cm / 10000
            elif mode == "cada_50cm_ancho":
                base = math.ceil(width_cm / 50)
            elif mode == "cada_100cm_ancho":
                base = math.ceil(width_cm / 100)
            else:
                raise ValueError("Regla de fabricación no reconocida")
            qty = base * factor * (1 + waste / 100)
            unit = component.get("unit", "unidad")
            if unit == "unidad":
                qty = math.ceil(qty - 1e-9)
            else:
                qty = round(qty, 4)
            unit_cost = numeric(component.get("unit_cost", 0), "Costo de insumo")
            lines.append({
                "name": component["name"], "quantity": qty,
                "unit": UNITS.get(unit, unit), "unit_cost": unit_cost,
                "subtotal": round(qty * unit_cost, 2), "mode": MODES[mode],
            })
    else:
        settings = cfg["settings"]
        key = "double_hardware_cost" if kind == "doble" else "traditional_hardware_cost" if kind == "tela" else "base_hardware_cost"
        flat = numeric(settings.get(key, 0), "Costo fijo de accesorios")
        lines.append({"name": "Accesorios (costo fijo anterior)", "quantity": 1, "unit": "Unidad", "unit_cost": flat, "subtotal": flat, "mode": "Costo fijo"})
    if kind != "tela":
        extra = numeric(chain_costs.get(chain, 0), "Costo adicional de cadena")
        if extra:
            lines.append({"name": f"Adicional cadena {chain}", "quantity": 1, "unit": "Unidad", "unit_cost": extra, "subtotal": extra, "mode": "Según opción seleccionada"})
    return round(sum(line["subtotal"] for line in lines), 2), lines, bool(recipe)


@bp.get("/admin/componentes")
def components_page():
    cfg = load_catalog()
    return render_template("components.html", components=cfg.get("components", []), storage=storage_label())


@bp.route("/admin/componente/nuevo", methods=["GET", "POST"])
@bp.route("/admin/componente/<component_id>", methods=["GET", "POST"])
def component_editor(component_id=None):
    cfg = load_catalog()
    components = cfg.setdefault("components", [])
    existing = next((c for c in components if c["id"] == component_id), None)
    if component_id and not existing:
        abort(404)
    if request.method == "GET":
        return render_template("component.html", component=existing, units=UNITS)
    try:
        name = request.form.get("name", "").strip()
        unit = request.form.get("unit", "unidad")
        if not 1 <= len(name) <= 90:
            raise ValueError("Ingresá el nombre del insumo (máximo 90 caracteres)")
        if unit not in UNITS:
            raise ValueError("Unidad de costo inválida")
        item = {
            "id": existing["id"] if existing else "ins-" + uuid.uuid4().hex[:12],
            "name": name,
            "unit": unit,
            "unit_cost": numeric(request.form.get("unit_cost"), "Costo del insumo"),
            "active": bool(request.form.get("active")),
        }
        if existing:
            cfg["components"] = [item if c["id"] == component_id else c for c in components]
        else:
            components.append(item)
        save_catalog(cfg)
        flash("Insumo guardado correctamente", "success")
        return redirect(url_for("manufacturing.components_page"))
    except (ValueError, StorageError) as exc:
        flash(str(exc), "error")
        return render_template("component.html", component=existing, units=UNITS), 400


@bp.get("/admin/recetas")
def recipes_page():
    cfg = load_catalog()
    return render_template(
        "recipes.html", components=[c for c in cfg.get("components", []) if c.get("active", True)],
        recipes=cfg.get("recipes", {}), models=PRODUCT_LABELS, modes=MODES,
    )


@bp.post("/admin/recetas/<kind>")
def recipe_save(kind):
    if kind not in PRODUCT_LABELS:
        abort(404)
    cfg = load_catalog()
    components = [c for c in cfg.get("components", []) if c.get("active", True)]
    try:
        rows = []
        for comp in components:
            ident = comp["id"]
            if request.form.get("use_" + ident) != "on":
                continue
            mode = request.form.get("mode_" + ident, "fijo")
            if mode not in MODES:
                raise ValueError("Regla de cantidad inválida")
            factor = numeric(request.form.get("factor_" + ident), "Factor de " + comp["name"], 0.001, 100000)
            waste = numeric(request.form.get("waste_" + ident, 0), "Merma de " + comp["name"], 0, 80)
            rows.append({"component_id": ident, "mode": mode, "factor": factor, "waste_pct": waste})
        cfg.setdefault("recipes", {})[kind] = rows
        save_catalog(cfg)
        flash("Receta de " + PRODUCT_LABELS[kind] + " guardada", "success")
    except (ValueError, StorageError) as exc:
        flash(str(exc), "error")
    return redirect(url_for("manufacturing.recipes_page") + "#" + kind)


def image_extension(raw):
    if raw.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp"
    return None


@bp.post("/admin/material/<material_id>/color/<color_id>/actualizar")
def color_variant_save(material_id, color_id):
    cfg = load_catalog()
    material = next((m for m in cfg["materials"] if m["id"] == material_id), None)
    if not material:
        abort(404)
    color = next((c for c in material.get("colors", []) if c["id"] == color_id), None)
    if not color:
        abort(404)
    try:
        raw_cost = request.form.get("price_override", "").strip()
        if raw_cost:
            color["price_override"] = numeric(raw_cost, "Costo de color")
        else:
            color.pop("price_override", None)
        if request.form.get("remove_photo") == "on":
            color.pop("photo", None)
        photo = request.files.get("photo")
        if photo and photo.filename:
            raw = photo.read()
            ext = image_extension(raw)
            if not ext or not 1 <= len(raw) <= 1_500_000:
                raise ValueError("La foto debe ser JPG, PNG o WEBP y pesar menos de 1,5 MB")
            key = "color-" + uuid.uuid4().hex + "." + ext
            save_image(key, raw)
            color["photo"] = key
        save_catalog(cfg)
        flash("Variante «" + color["name"] + "» actualizada", "success")
    except (ValueError, StorageError) as exc:
        flash(str(exc), "error")
    return redirect(url_for("material_editor", material_id=material_id) + "#variantes")
