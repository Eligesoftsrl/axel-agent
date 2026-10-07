"""Compiti ricorrenti dettati a voce: AXEL esegue un'istruzione a orari stabiliti e ti manda il risultato.

Es. "ogni venerdì alle 18 fammi il riepilogo della settimana e delle email senza risposta".
"""
from __future__ import annotations

from datetime import datetime

from . import db
from .reminders import RECURRENCES, _next, _parse, fmt

with db.tx() as _c:
    _c.execute(
        """CREATE TABLE IF NOT EXISTS tasks (
             id INTEGER PRIMARY KEY AUTOINCREMENT,
             agent_id TEXT NOT NULL,
             title TEXT NOT NULL,
             prompt TEXT NOT NULL,
             due_at TEXT NOT NULL,
             recurrence TEXT NOT NULL DEFAULT 'weekly',
             active INTEGER NOT NULL DEFAULT 1,
             created_at TEXT NOT NULL DEFAULT (datetime('now')))"""
    )


def create(agent_id: str, title: str, prompt: str, first_run: str, recurrence: str = "weekly") -> dict:
    due = _parse(first_run)
    recurrence = recurrence if recurrence in RECURRENCES else "weekly"
    with db.tx() as c:
        cur = c.execute(
            "INSERT INTO tasks(agent_id, title, prompt, due_at, recurrence) VALUES(?,?,?,?,?)",
            (agent_id, title, prompt, due.isoformat(timespec="minutes"), recurrence),
        )
    return {"id": cur.lastrowid, "title": title, "due_at": due.isoformat(timespec="minutes"), "recurrence": recurrence}


def list_active(agent_id: str | None = None) -> list[dict]:
    if agent_id:
        return db.query("SELECT * FROM tasks WHERE active=1 AND agent_id=? ORDER BY due_at", (agent_id,))
    return db.query("SELECT * FROM tasks WHERE active=1 ORDER BY due_at")


def delete(task_id: int) -> bool:
    with db.tx() as c:
        return c.execute("UPDATE tasks SET active=0 WHERE id=?", (task_id,)).rowcount > 0


def pop_due() -> list[dict]:
    from .google_api import tz

    now = datetime.now(tz()).replace(tzinfo=None)
    due = db.query("SELECT * FROM tasks WHERE active=1 AND due_at <= ?", (now.isoformat(timespec="minutes"),))
    with db.tx() as c:
        for t in due:
            nxt = _next(datetime.fromisoformat(t["due_at"]), t["recurrence"])
            while nxt and nxt <= now:
                nxt = _next(nxt, t["recurrence"])
            if nxt:
                c.execute("UPDATE tasks SET due_at=? WHERE id=?", (nxt.isoformat(timespec="minutes"), t["id"]))
            else:
                c.execute("UPDATE tasks SET active=0 WHERE id=?", (t["id"],))
    return due


def describe(t: dict) -> str:
    rec = {"none": "una volta", "daily": "ogni giorno", "weekdays": "giorni feriali", "weekly": "ogni settimana",
           "monthly": "ogni mese"}[t["recurrence"]]
    return f"#{t['id']} «{t['title']}» — prossima: {fmt(datetime.fromisoformat(t['due_at']))} ({rec})"
