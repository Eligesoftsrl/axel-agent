"""Galleria foto: AXEL mostra le immagini di una cartella del Mac in un carosello 3D (stile Cover Flow).

- Solo cartelle dentro la tua Home (stessa regola degli altri strumenti del Mac).
- Il server serve SOLO le immagini della galleria aperta (niente accesso libero ai file).
- Anteprime ridimensionate e convertite in JPEG (le HEIC dell'iPhone il browser non le apre):
  con `sips` (incluso in macOS) o, se installato, Pillow. Cache in backend/data/thumbs.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path

from . import db, mac

EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif", ".tif", ".tiff", ".bmp"}
WEB_OK = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
THUMBS = db.DATA_DIR / "thumbs"
MAX_ITEMS = 300
_galleries: dict[str, dict] = {}


def _default_root() -> Path:
    home = Path.home()
    for name in ("Pictures", "Immagini"):
        if (home / name).is_dir():
            return home / name
    return home


def collect(folder: str = "", query: str = "", limit: int = 120, recursive: bool = True) -> tuple[Path, list[Path]]:
    root = mac.safe_path(folder) if folder else _default_root()
    if not root.exists():
        raise mac.MacError(f"Non trovo la cartella {root}")
    if root.is_file():
        root = root.parent
    terms = [t for t in query.lower().split() if t]
    found: list[tuple[float, Path]] = []
    base_depth = len(root.parts)
    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).parts) - base_depth
        # niente cartelle nascoste o librerie di app (es. "Photos Library.photoslibrary")
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and not d.endswith((".photoslibrary", ".app", ".lrlibrary"))]
        if not recursive or depth >= 4:
            dirnames[:] = []
        for f in filenames:
            p = Path(dirpath) / f
            if p.suffix.lower() not in EXTS or f.startswith("."):
                continue
            if terms:
                hay = str(p.relative_to(root)).lower()
                if not all(t in hay for t in terms):
                    continue
            try:
                found.append((p.stat().st_mtime, p))
            except OSError:
                continue
        if len(found) > 5000:
            break
    found.sort(key=lambda x: -x[0])
    return root, [p for _, p in found[: max(1, min(limit, MAX_ITEMS))]]


def open_gallery(folder: str = "", query: str = "", limit: int = 120) -> dict:
    root, files = collect(folder, query, limit)
    gid = uuid.uuid4().hex[:10]
    _galleries[gid] = {"files": files, "created": time.time()}
    for old in sorted(_galleries, key=lambda k: _galleries[k]["created"])[:-8]:  # tiene le ultime 8 gallerie
        _galleries.pop(old, None)
    title = root.name if root != Path.home() else "Home"
    if query:
        title += f" · {query}"
    items = []
    for i, p in enumerate(files):
        st = p.stat()
        items.append({"i": i, "name": p.name, "folder": str(p.parent.relative_to(root)) if p.parent != root else "",
                      "date": datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%Y")})
    return {"id": gid, "title": title, "path": str(root).replace(str(Path.home()), "~"), "items": items}


def file_for(gid: str, idx: int) -> Path | None:
    g = _galleries.get(gid)
    if not g or not (0 <= idx < len(g["files"])):
        return None
    return g["files"][idx]


def image(gid: str, idx: int, size: int) -> tuple[Path, str] | None:
    """Percorso di un'immagine pronta per il browser (ridimensionata/convertita se serve) e il suo tipo."""
    src = file_for(gid, idx)
    if not src or not src.exists():
        return None
    size = 480 if size <= 480 else 1600
    ext = src.suffix.lower()
    if ext == ".gif":
        return src, "image/gif"  # le GIF animate restano originali
    st = src.stat()
    key = hashlib.sha1(f"{src}|{st.st_mtime}|{st.st_size}|{size}".encode()).hexdigest()
    THUMBS.mkdir(exist_ok=True)
    out = THUMBS / f"{key}.jpg"
    if out.exists():
        return out, "image/jpeg"
    if _resize(src, out, size):
        return out, "image/jpeg"
    if ext in WEB_OK:  # nessun programma per ridimensionare: va bene l'originale
        return src, {".png": "image/png", ".webp": "image/webp"}.get(ext, "image/jpeg")
    return None


def _resize(src: Path, out: Path, size: int) -> bool:
    if shutil.which("sips"):
        try:
            subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "82", "-Z", str(size), str(src), "--out", str(out)],
                           check=True, capture_output=True, timeout=30)
            return out.exists()
        except Exception:  # noqa: BLE001
            pass
    try:
        from PIL import Image, ImageOps

        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im)
            im.thumbnail((size, size))
            im.convert("RGB").save(out, "JPEG", quality=82)
        return True
    except Exception:  # noqa: BLE001
        return False


def prune_cache(max_mb: int = 400) -> None:
    if not THUMBS.exists():
        return
    files = sorted(THUMBS.glob("*.jpg"), key=lambda p: p.stat().st_atime)
    total = sum(p.stat().st_size for p in files)
    while files and total > max_mb * 1024 * 1024:
        p = files.pop(0)
        total -= p.stat().st_size
        p.unlink(missing_ok=True)
