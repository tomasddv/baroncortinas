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


def available_options(cfg, kind):
    """Choices must match the actual configurator and server-side validation."""
    options = {"mount": ["Pared", "Techo"]}
    if kind == "tela":
        options["pleat"] = list(cfg["settings"].get("traditional_pleat_multiplier", {"Fruncida": 1.8}).keys())
    else:
        options.update({
            "drop": ["Detrás", "Delante"],
            "side": ["Izquierda", "Derecha"],
            "chain": list(cfg["settings"].get("chain_costs", {"Plástica": 0}).keys()),
        })
    return options


def _calculate_lines(recipe, components, width_cm, height_cm, prefix=""):
    """Calculate a recipe's cost, never trusting unit costs from client input."""
    lines = []
    for item in recipe:
        component = components.get(item.get("component_id"))
        if not component or not component.get("active", True):
            raise ValueError("Hay un insumo inactivo o inexistente en las recetas. Revisá Administración.")
        mode = item.get("mode", "fijo")
        if mode not in MODES:
            raise ValueError("Regla de fabricación no reconocida")
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
        else:
            base = math.ceil(width_cm / 100)
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
            "subtotal": round(qty * unit_cost, 2),
            "mode": prefix + MODES[mode],
        })
    return lines


def calculate_hardware(cfg, kind, width_cm, height_cm, chain, chain_costs,
                       mount="Pared", drop="Detrás", side="Derecha", pleat="Fruncida"):
    """One base BOM + matching conditional BOM lines. Never multiply recipes per combination."""
    recipe = cfg.get("recipes", {}).get(kind) or []
    components = {item["id"]: item for item in cfg.get("components", [])}
    if recipe:
        lines = _calculate_lines(recipe, components, width_cm, height_cm)
    else:
        settings = cfg["settings"]
        key = "double_hardware_cost" if kind == "doble" else "traditional_hardware_cost" if kind == "tela" else "base_hardware_cost"
        flat = numeric(settings.get(key, 0), "Costo fijo de accesorios")
        lines = [{"name": "Accesorios (costo fijo anterior)", "quantity": 1,
                  "unit": "Unidad", "unit_cost": flat, "subtotal": flat, "mode": "Costo fijo"}]

    selected = {"mount": mount, "drop": drop, "side": side, "chain": chain, "pleat": pleat}
    allowed = available_options(cfg, kind)
    rules = cfg.get("option_rules", {}).get(kind) or []
    for rule in rules:
        key, value = rule.get("option_key"), rule.get("option_value")
        if key not in allowed or value not in allowed[key]:
            raise ValueError("Hay una regla de opción desactualizada. Revisá Administración > Opciones.")
        if selected[key] == value:
            lines.extend(_calculate_lines([rule], components, width_cm, height_cm,
                                          prefix=f"{key}: {value} · "))

    # Legacy chain extras apply only until any conditional chain rules are defined
    # for this model. Otherwise a configured chain would be charged twice.
    has_chain_rules = any(rule.get("option_key") == "chain" for rule in rules)
    if kind != "tela" and not has_chain_rules:
        extra = numeric(chain_costs.get(chain, 0), "Costo adicional de cadena")
        if extra:
            lines.append({"name": f"Adicional cadena {chain}", "quantity": 1,
                          "unit": "Unidad", "unit_cost": extra, "subtotal": extra,
                          "mode": "Adicional anterior según cadena"})
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


@bp.get("/admin/opciones")
def option_rules_page():
    cfg = load_catalog()
    return render_template(
        "option_rules.html", models=PRODUCT_LABELS,
        option_rules=cfg.get("option_rules", {}),
        options_by_model={kind: available_options(cfg, kind) for kind in PRODUCT_LABELS},
        components=[c for c in cfg.get("components", []) if c.get("active", True)],
        modes=MODES,
    )


@bp.post("/admin/opciones/<kind>")
def option_rules_save(kind):
    if kind not in PRODUCT_LABELS:
        abort(404)
    cfg = load_catalog()
    allowed = available_options(cfg, kind)
    active_components = {c["id"] for c in cfg.get("components", []) if c.get("active", True)}
    f = request.form
    fields = [f.getlist(key) for key in
              ("option_key", "option_value", "component_id", "mode", "factor", "waste_pct")]
    try:
        if len({len(values) for values in fields}) != 1:
            raise ValueError("Hay una fila incompleta en las reglas de opciones")
        if len(fields[0]) > 120:
            raise ValueError("Máximo 120 reglas por modelo")
        rows = []
        for key, value, component_id, mode, factor, waste in zip(*fields):
            if key not in allowed or value not in allowed[key]:
                raise ValueError("Seleccioná una opción válida para este modelo")
            if component_id not in active_components:
                raise ValueError("Seleccioná un insumo activo")
            if mode not in MODES:
                raise ValueError("Regla de cantidad inválida")
            rows.append({
                "option_key": key, "option_value": value, "component_id": component_id,
                "mode": mode, "factor": numeric(factor, "Factor", 0.001, 100000),
                "waste_pct": numeric(waste, "Merma", 0, 80),
            })
        cfg.setdefault("option_rules", {})[kind] = rows
        save_catalog(cfg)
        flash(f"Reglas de {PRODUCT_LABELS[kind]} guardadas", "success")
    except (ValueError, StorageError) as exc:
        flash(str(exc), "error")
    return redirect(url_for("manufacturing.option_rules_page") + "#" + kind)
