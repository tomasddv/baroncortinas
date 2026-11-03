"""Private collection-cover management: image, short MP4, or hosted MP4 URL.

All configuration persists in the existing GitHub-backed catalog. The public
home page reads the current catalog without a redeploy-specific code change.
"""
import uuid
from urllib.parse import urlsplit

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from storage import StorageError, load_catalog, save_catalog, save_image

bp = Blueprint("marketing", __name__)
MODELS = {
    "blackout": "Roller Blackout",
    "sunscreen": "Roller Sun Screen",
    "doble": "Roller Doble",
    "tela": "Cortina de Tela",
}


def detect_media(data):
    if data.startswith(b"\xff\xd8\xff"):
        return "image", "jpg", 1_500_000
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image", "png", 1_500_000
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image", "webp", 1_500_000
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in (b"isom", b"iso2", b"mp41", b"mp42", b"avc1", b"M4V ", b"dash"):
        return "video", "mp4", 8_000_000
    raise ValueError("Formato no compatible. Usá JPG, PNG, WEBP o MP4 (H.264 recomendado).")


@bp.get("/admin/portadas")
def cover_editor():
    cfg = load_catalog()
    return render_template("portadas.html", models=MODELS,
                           covers=cfg["settings"].get("collection_media", {}))


@bp.post("/admin/portadas/<kind>")
def cover_save(kind):
    if kind not in MODELS:
        abort(404)
    cfg = load_catalog()
    covers = cfg["settings"].setdefault("collection_media", {})
    mode = request.form.get("mode", "")
    try:
        if mode == "reset":
            covers.pop(kind, None)
        elif mode in ("image", "video"):
            file = request.files.get("media")
            if not file or not file.filename:
                raise ValueError("Seleccioná un archivo para subir.")
            raw = file.read(8_000_001)
            detected, extension, limit = detect_media(raw)
            if detected != mode:
                raise ValueError("El tipo de archivo no coincide con la opción seleccionada.")
            if not 1 <= len(raw) <= limit:
                raise ValueError("La foto debe pesar hasta 1,5 MB y el video MP4 hasta 8 MB.")
            key = "cover-" + uuid.uuid4().hex + "." + extension
            save_image(key, raw)
            covers[kind] = {"type": detected, "source": "upload", "value": key}
        elif mode == "video_url":
            url = request.form.get("video_url", "").strip()
            parsed = urlsplit(url)
            if len(url) > 1500 or parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Ingresá un enlace HTTPS válido a un archivo MP4 público.")
            if not parsed.path.lower().endswith(".mp4"):
                raise ValueError("El enlace debe apuntar directamente a un archivo .mp4 (no a una página de YouTube).")
            covers[kind] = {"type": "video", "source": "url", "value": url}
        else:
            raise ValueError("Elegí foto, video, enlace MP4 o restaurar ilustración.")
        save_catalog(cfg)
        flash("Portada de " + MODELS[kind] + " actualizada", "success")
    except (ValueError, StorageError) as exc:
        flash(str(exc), "error")
    return redirect(url_for("marketing.cover_editor") + "#" + kind)
