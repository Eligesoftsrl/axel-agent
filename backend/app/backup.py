"""Copia di sicurezza automatica dei dati di AXEL (memoria, conversazioni, impostazioni, agenti, collegamenti).

- Ogni notte (ora configurabile) crea un file AXEL-backup-AAAA-MM-GG_HHMM.zip nella cartella scelta.
  Di default: iCloud Drive/AXEL Backup se iCloud è attivo (così la copia è anche fuori dal Mac),
  altrimenti Documenti/AXEL Backup.
- Il database viene copiato "a caldo" in modo consistente (API di backup di SQLite), anche mentre AXEL lavora.
- Tiene le ultime N copie (default 14) e cancella le più vecchie.
- Contiene: axel.db (memoria, cronologia, promemoria, impostazioni e accessi a Google/Spotify), agents.json,
  mcp.json. NON contiene: google_client_secret.json (si riscarica da Google Cloud), allegati caricati,
  grafici generati e log. La copia contiene i token di accesso: tienila in un posto solo tuo.
- Ripristino: da Integrazioni → Sistema → Copia di sicurezza (prima fa comunque una copia dello stato attuale).
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

from . import db
from .google_api import tz

log = logging.getLogger("axel.backup")

DEFAULTS = {"enabled": True, "folder": "", "time": "03:30", "keep": 14}
EXTRA_FILES = ["agents.json", "mcp.json"]
NAME_RE = re.compile(r"^AXEL-backup-\d{4}-\d{2}-\d{2}_\d{4}(-[a-z]+)?\.zip$")


def settings() -> dict:
    return {**DEFAULTS, **(db.get_setting("backup") or {})}


def save(s: dict) -> dict:
    cur = settings()
    for k in DEFAULTS:
        if k in s:
            cur[k] = s[k]
    cur["keep"] = max(3, min(90, int(cur["keep"])))
    db.set_setting("backup", cur)
    return cur


def default_folder() -> Path:
    icloud = Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
    if icloud.is_dir():
        return icloud / "AXEL Backup"
    return Path.home() / "Documents" / "AXEL Backup"


def folder() -> Path:
    f = settings()["folder"].strip()
    return Path(os.path.expanduser(f)) if f else default_folder()


def list_backups() -> list[dict]:
    d = folder()
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("AXEL-backup-*.zip"), reverse=True):
        if NAME_RE.match(p.name):
            st = p.stat()
            out.append({"name": p.name, "size": st.st_size, "created": datetime.fromtimestamp(st.st_mtime, tz()).isoformat()})
    return out


def create(label: str = "") -> dict:
    """Crea una copia adesso. label: '' (normale), 'manuale', 'prima-ripristino'."""
    d = folder()
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz()).strftime("%Y-%m-%d_%H%M")
    name = f"AXEL-backup-{stamp}{'-' + label if label else ''}.zip"
    target = d / name
    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / "axel.db"
        dst = sqlite3.connect(snap)
        with db._lock:  # copia consistente del database aperto
            db.conn().backup(dst)
        dst.close()
        partial = target.with_suffix(".zip.part")
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(snap, "axel.db")
            for fname in EXTRA_FILES:
                p = db.DATA_DIR / fname
                if p.exists():
                    z.write(p, fname)
            z.writestr("info.json", json.dumps({"created": datetime.now(tz()).isoformat(), "app": "AXEL",
                                                "files": ["axel.db", *[f for f in EXTRA_FILES if (db.DATA_DIR / f).exists()]]}))
        partial.replace(target)
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    prune()
    info = {"name": name, "size": target.stat().st_size, "folder": str(d)}
    db.set_setting("backup_last", {**info, "at": datetime.now(tz()).isoformat()})
    log.info("copia di sicurezza creata: %s (%d KB)", target, info["size"] // 1024)
    return info


def prune() -> None:
    keep = settings()["keep"]
    normal = [b for b in list_backups() if "prima-ripristino" not in b["name"]]
    for b in normal[keep:]:
        try:
            (folder() / b["name"]).unlink()
        except OSError:
            pass


def restore(name: str) -> dict:
    """Ripristina una copia: salva prima lo stato attuale, poi sostituisce database e file di configurazione."""
    if not NAME_RE.match(name):
        raise ValueError("nome della copia non valido")
    src = folder() / name
    if not src.is_file():
        raise ValueError("copia non trovata")
    safety = create("prima-ripristino")
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(src) as z:
        members = set(z.namelist())
        if "axel.db" not in members:
            raise ValueError("la copia non contiene il database")
        z.extract("axel.db", tmp)
        restored = sqlite3.connect(Path(tmp) / "axel.db")
        with db._lock:
            restored.backup(db.conn())  # sovrascrive il database aperto in modo consistente
        restored.close()
        for fname in EXTRA_FILES:
            if fname in members:
                (db.DATA_DIR / fname).write_bytes(z.read(fname))
    log.info("ripristinata la copia %s (stato precedente salvato in %s)", name, safety["name"])
    return {"restored": name, "safety": safety["name"]}


async def check() -> None:
    """Chiamato dal ciclo proattivo: copia notturna, oppure subito se l'ultima ha più di 36 ore (Mac spento di notte)."""
    import asyncio

    s = settings()
    if not s["enabled"]:
        return
    now = datetime.now(tz())
    last = db.get_setting("backup_last") or {}
    last_at = datetime.fromisoformat(last["at"]) if last.get("at") else None
    hh, mm = (int(x) for x in s["time"].split(":"))
    due_today = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    overdue = last_at is None or (now - last_at).total_seconds() > 36 * 3600
    tonight = now >= due_today and (last_at is None or last_at < due_today)
    if overdue or tonight:
        try:
            await asyncio.to_thread(create)
        except Exception as exc:  # noqa: BLE001
            log.warning("copia di sicurezza non riuscita: %s", exc)
            db.set_setting("backup_error", {"at": now.isoformat(), "error": str(exc)})
            time.sleep(0)


def status() -> dict:
    return {**settings(), "folder_effective": str(folder()), "last": db.get_setting("backup_last"),
            "error": db.get_setting("backup_error"), "backups": list_backups()[:30]}
