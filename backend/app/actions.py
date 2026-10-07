"""Azioni che richiedono la tua conferma (inviare email, creare/eliminare eventi).

L'agente prepara l'azione → viene salvata come 'pending' → tu approvi dalla UI o da
Telegram → solo allora viene eseguita.
"""
from __future__ import annotations

import json
import uuid
from typing import Callable

from . import db, google_api, mac

EXECUTORS: dict[str, Callable[..., str]] = {
    "calendar_create_event": google_api.calendar_create,
    "calendar_delete_event": lambda event_id: google_api.calendar_delete(event_id),
    "gmail_send": google_api.gmail_send,
    "mac_trash": lambda path: mac.trash(path),
    "mac_move": lambda src, dst: mac.move(src, dst),
    "mac_run_command": lambda command, cwd="~": mac.run_command(command, cwd),
    "mcp_call": lambda tool, arguments=None: _mcp().manager.call_sync(tool, arguments or {}),
}


def _mcp():
    from . import mcp_client

    return mcp_client


def summarize(name: str, args: dict) -> str:
    if name == "gmail_send":
        return f"Inviare email a {args.get('to')}\nOggetto: {args.get('subject')}\n\n{args.get('body', '')}"
    if name == "calendar_create_event":
        extra = f" @ {args['location']}" if args.get("location") else ""
        return f"Creare evento «{args.get('title')}» — {args.get('start')}{(' → ' + args['end']) if args.get('end') else ''}{extra}"
    if name == "mac_trash":
        return f"Spostare nel Cestino: {args.get('path')}"
    if name == "mac_move":
        return f"Spostare {args.get('src')}\n→ {args.get('dst')}"
    if name == "mac_run_command":
        return mac.describe_command(args.get("command", ""), args.get("cwd", "~"))
    if name == "mcp_call":
        tool = str(args.get("tool", ""))
        parts = tool.split("__")
        label = f"{parts[1]} → {parts[2]}" if len(parts) >= 3 else tool
        body = json.dumps(args.get("arguments") or {}, ensure_ascii=False, indent=1)
        return f"Collegamento MCP: {label}\n{body[:1200]}"
    if name == "calendar_delete_event":
        return f"Eliminare l'evento {args.get('event_id')}"
    return f"{name} {json.dumps(args, ensure_ascii=False)}"


def create(agent_id: str, name: str, args: dict) -> dict:
    aid = uuid.uuid4().hex[:10]
    summary = summarize(name, args)
    with db.tx() as c:
        c.execute("INSERT INTO actions(id, agent_id, name, args, summary) VALUES(?,?,?,?,?)",
                  (aid, agent_id, name, json.dumps(args, ensure_ascii=False), summary))
    return {"id": aid, "name": name, "summary": summary, "args": args}


def get(aid: str) -> dict | None:
    rows = db.query("SELECT * FROM actions WHERE id=?", (aid,))
    return rows[0] if rows else None


def pending() -> list[dict]:
    return db.query("SELECT id, name, summary, created_at FROM actions WHERE status='pending' ORDER BY created_at")


def approve(aid: str) -> dict:
    a = get(aid)
    if not a or a["status"] != "pending":
        return {"ok": False, "result": "Azione non trovata o già gestita."}
    try:
        result = EXECUTORS[a["name"]](**json.loads(a["args"]))
        status = "done"
    except Exception as exc:  # noqa: BLE001
        result, status = f"Errore: {exc}", "error"
    with db.tx() as c:
        c.execute("UPDATE actions SET status=?, result=? WHERE id=?", (status, result, aid))
    return {"ok": status == "done", "result": result}


def reject(aid: str) -> dict:
    with db.tx() as c:
        c.execute("UPDATE actions SET status='rejected' WHERE id=? AND status='pending'", (aid,))
    return {"ok": True, "result": "Azione annullata."}
