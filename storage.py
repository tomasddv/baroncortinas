"""GitHub-backed catalog and image persistence with safe local development fallback.
GitHub Contents API reads/writes; do not persist client PII in GitHub.
"""
import base64
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent
CATALOG_PATH = ROOT / "data" / "catalog.json"
REPO = os.environ.get("GITHUB_REPO", "").strip()
TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
BRANCH = os.environ.get("GITHUB_BRANCH", "main").strip() or "main"
IS_RENDER = bool(os.environ.get("RENDER"))

class StorageError(RuntimeError):
    pass


def remote_enabled():
    return bool(REPO and TOKEN)


def storage_label():
    if remote_enabled():
        return f"GitHub: {REPO} / {BRANCH}"
    if IS_RENDER:
        return "Modo demo: catálogo solo lectura (configurá GitHub)"
    return "Local: data/catalog.json (en desarrollo)"


def _github_request(path, method="GET", payload=None, ref=False):
    if not remote_enabled():
        raise StorageError("Configurá GITHUB_REPO y GITHUB_TOKEN")
    encoded = urllib.parse.quote(path, safe="/")
    url = f"https://api.github.com/repos/{REPO}/contents/{encoded}"
    if ref and method == "GET":
        url += "?ref=" + urllib.parse.quote(BRANCH, safe="")
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "baron-cotizador/1.0",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")[:350]
        if exc.code == 404:
            raise FileNotFoundError(path) from exc
        raise StorageError(f"GitHub rechazó la operación ({exc.code}): {details}") from exc
    except Exception as exc:
        raise StorageError(f"No se pudo conectar con GitHub: {exc}") from exc


def read_file(path):
    doc = _github_request(path, ref=True)
    return base64.b64decode(doc["content"].replace("\n", ""))


def write_file(path, content, message):
    try:
        prev = _github_request(path, ref=True)
        sha = prev["sha"]
    except FileNotFoundError:
        sha = None
    payload = {
        "message": message,
        "content": base64.b64encode(content).decode("ascii"),
        "branch": BRANCH,
    }
    if sha:
        payload["sha"] = sha
    return _github_request(path, method="PUT", payload=payload)


def load_catalog():
    if remote_enabled():
        try:
            return json.loads(read_file("data/catalog.json"))
        except FileNotFoundError:
            # Repo needs initial file: first admin save can create it.
            pass
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def save_catalog(data):
    b = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if remote_enabled():
        write_file("data/catalog.json", b, "Actualizar catálogo de cortinas desde panel de administración")
    elif IS_RENDER:
        raise StorageError("Render no mantiene cambios de archivos locales. Configurá GITHUB_REPO y GITHUB_TOKEN.")
    else:
        CATALOG_PATH.write_bytes(b)


def save_image(key, content):
    path = f"static/uploads/{key}"
    if remote_enabled():
        write_file(path, content, f"Agregar fotografía de material: {key}")
    elif IS_RENDER:
        raise StorageError("Configurá GitHub antes de subir imágenes en Render.")
    else:
        p = ROOT / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    return key


def read_image(key):
    if "/" in key or ".." in key:
        raise FileNotFoundError(key)
    path = f"static/uploads/{key}"
    if remote_enabled():
        return read_file(path)
    return (ROOT / path).read_bytes()
