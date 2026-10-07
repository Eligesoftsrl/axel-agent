"""Documenti: trascini un PDF, un Excel, un CSV o un'immagine e AXEL li analizza.

- Il file viene salvato in backend/data/uploads e caricato una volta sola sulla Files API di Anthropic.
- PDF e immagini arrivano a Claude come documento/immagine (li "legge" e li vede).
- Excel, CSV, Word e altri formati vanno nel contenitore della code execution: Claude scrive ed esegue
  codice Python per calcoli, tabelle e grafici. I file che produce (es. grafici PNG) vengono scaricati
  in backend/data/outputs e mostrati nell'app (o inviati su Telegram).
"""
from __future__ import annotations

import json
import logging
import mimetypes
import re
import uuid
from pathlib import Path

from . import db

log = logging.getLogger("axel.documents")

UPLOADS = db.DATA_DIR / "uploads"
OUTPUTS = db.DATA_DIR / "outputs"
MAX_BYTES = 30 * 1024 * 1024

PDF = {".pdf"}
IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
TEXT = {".txt", ".md", ".json", ".xml", ".html", ".log"}


def kind_of(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext in PDF:
        return "pdf"
    if ext in IMAGES:
        return "image"
    if ext in TEXT:
        return "text"
    return "data"  # xlsx, xls, csv, docx, pptx, zip… → code execution


def _index() -> dict:
    return db.get_setting("attachments") or {}


def _save_index(idx: dict) -> None:
    # tiene solo gli ultimi 200 allegati
    if len(idx) > 200:
        idx = dict(sorted(idx.items(), key=lambda kv: kv[1].get("created", 0))[-200:])
    db.set_setting("attachments", idx)


def get(aid: str) -> dict | None:
    return _index().get(aid)


def save_upload(name: str, data: bytes) -> dict:
    """Salva il file e lo carica sulla Files API. Restituisce i metadati dell'allegato."""
    import time

    if len(data) > MAX_BYTES:
        raise ValueError("file troppo grande (massimo 30 MB)")
    UPLOADS.mkdir(exist_ok=True)
    safe = re.sub(r"[^\w.\- ]", "_", Path(name).name)[:120] or "file"
    aid = uuid.uuid4().hex[:12]
    path = UPLOADS / f"{aid}_{safe}"
    path.write_bytes(data)
    meta = {"id": aid, "name": safe, "kind": kind_of(safe), "size": len(data), "path": str(path),
            "mime": mimetypes.guess_type(safe)[0] or "application/octet-stream", "created": time.time(), "file_id": None}
    try:
        meta["file_id"] = _upload_to_anthropic(path, meta["mime"])
    except Exception as exc:  # noqa: BLE001  (senza chiave o rete: si ripiega sull'invio diretto)
        log.warning("Files API non disponibile per %s: %s", safe, exc)
    idx = _index()
    idx[aid] = meta
    _save_index(idx)
    return {k: meta[k] for k in ("id", "name", "kind", "size")}


def _upload_to_anthropic(path: Path, mime: str) -> str | None:
    import os

    if not os.getenv("ANTHROPIC_API_KEY"):
        return None
    from anthropic import Anthropic

    with open(path, "rb") as f:
        fo = Anthropic().files.upload(file=(path.name, f, mime))
    return fo.id


def build_content(text: str, ids: list[str]) -> list[dict]:
    """Messaggio utente con gli allegati come blocchi (documento, immagine o file per la code execution)."""
    import base64

    blocks: list[dict] = []
    names = []
    for aid in ids:
        m = get(aid)
        if not m:
            continue
        names.append(f"{m['name']} ({m['kind']})")
        fid = m.get("file_id")
        if m["kind"] == "pdf":
            src = {"type": "file", "file_id": fid} if fid else \
                {"type": "base64", "media_type": "application/pdf", "data": base64.b64encode(Path(m["path"]).read_bytes()).decode()}
            blocks.append({"type": "document", "source": src, "title": m["name"]})
        elif m["kind"] == "image":
            src = {"type": "file", "file_id": fid} if fid else \
                {"type": "base64", "media_type": m["mime"], "data": base64.b64encode(Path(m["path"]).read_bytes()).decode()}
            blocks.append({"type": "image", "source": src})
        elif m["kind"] == "text":
            body = Path(m["path"]).read_text("utf-8", errors="replace")[:100_000]
            blocks.append({"type": "document", "source": {"type": "text", "media_type": "text/plain", "data": body},
                           "title": m["name"]})
        elif fid:
            blocks.append({"type": "container_upload", "file_id": fid})
        else:
            blocks.append({"type": "text", "text": f"[Allegato {m['name']}: non caricato, manca la chiave API]"})
    note = ""
    if names:
        note = ("\n\n[Allegati: " + ", ".join(names) + ". Per fogli di calcolo, CSV e documenti Office usa la code execution: "
                "i file sono nella cartella di lavoro del contenitore. Se crei grafici o file, salvali in $OUTPUT_DIR.]")
    return blocks + [{"type": "text", "text": (text or "Analizza gli allegati.") + note}]


def needs_code_execution(ids: list[str]) -> bool:
    return any((get(a) or {}).get("kind") == "data" for a in ids)


def collect_outputs(content) -> list[dict]:
    """Trova i file prodotti dalla code execution in una risposta e li scarica in data/outputs."""
    found = []
    for block in content or []:
        btype = getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)
        if btype not in ("bash_code_execution_tool_result", "code_execution_tool_result"):
            continue
        inner = getattr(block, "content", None)
        files = getattr(inner, "content", None) or []
        for f in files:
            fid = getattr(f, "file_id", None)
            if fid:
                try:
                    found.append(_download_output(fid))
                except Exception as exc:  # noqa: BLE001
                    log.warning("download output %s: %s", fid, exc)
    return found


def _download_output(file_id: str) -> dict:
    from anthropic import Anthropic

    c = Anthropic()
    meta = c.files.retrieve_metadata(file_id)
    name = re.sub(r"[^\w.\- ]", "_", getattr(meta, "filename", None) or f"{file_id}.bin")
    OUTPUTS.mkdir(exist_ok=True)
    path = OUTPUTS / f"{file_id}_{name}"
    c.files.download(file_id).write_to_file(str(path))
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return {"id": file_id, "name": name, "mime": mime, "url": f"/api/outputs/{file_id}", "path": str(path)}


def output_path(file_id: str) -> Path | None:
    if not re.fullmatch(r"[\w-]{4,80}", file_id):
        return None
    hits = list(OUTPUTS.glob(f"{file_id}_*")) if OUTPUTS.exists() else []
    return hits[0] if hits else None


def describe(meta: dict) -> str:
    return json.dumps({k: meta[k] for k in ("id", "name", "kind", "size")}, ensure_ascii=False)
