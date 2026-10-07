"""Promemoria con ricorrenza. Il controllo periodico è in scheduler.py."""
from __future__ import annotations

import calendar
from datetime import datetime, timedelta

from . import db
from .google_api import tz

RECURRENCES = ["none", "daily", "weekdays", "weekly", "monthly"]
GIORNI = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]


def fmt(dt: datetime) -> str:
    return f"{GIORNI[dt.weekday()]} {dt:%d/%m %H:%M}"


def _parse(s: str) -> datetime:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt.astimezone(tz()).replace(tzinfo=None) if dt.tzinfo else dt


def create(agent_id: str, text: str, due_at: str, recurrence: str = "none") -> dict:
    due = _parse(due_at)
    recurrence = recurrence if recurrence in RECURRENCES else "none"
    with db.tx() as c:
        cur = c.execute(
            "INSERT INTO reminders(agent_id, text, due_at, recurrence) VALUES(?,?,?,?)",
            (agent_id, text, due.isoformat(timespec="minutes"), recurrence),
        )
    return {"id": cur.lastrowid, "text": text, "due_at": due.isoformat(timespec="minutes"), "recurrence": recurrence}


def list_active(agent_id: str | None = None) -> list[dict]:
    if agent_id:
        return db.query("SELECT * FROM reminders WHERE active=1 AND agent_id=? ORDER BY due_at", (agent_id,))
    return db.query("SELECT * FROM reminders WHERE active=1 ORDER BY due_at")


def delete(reminder_id: int) -> bool:
    with db.tx() as c:
        return c.execute("UPDATE reminders SET active=0 WHERE id=?", (reminder_id,)).rowcount > 0


def _next(due: datetime, rec: str) -> datetime | None:
    if rec == "daily":
        return due + timedelta(days=1)
    if rec == "weekly":
        return due + timedelta(weeks=1)
    if rec == "weekdays":
        n = due + timedelta(days=1)
        while n.weekday() >= 5:
            n += timedelta(days=1)
        return n
    if rec == "monthly":
        m = due.month % 12 + 1
        y = due.year + (due.month // 12)
        d = min(due.day, calendar.monthrange(y, m)[1])
        return due.replace(year=y, month=m, day=d)
    return None


def pop_due() -> list[dict]:
    """Restituisce i promemoria scaduti e li riprogramma (o disattiva)."""
    now = datetime.now(tz()).replace(tzinfo=None)
    due = db.query("SELECT * FROM reminders WHERE active=1 AND due_at <= ?", (now.isoformat(timespec="minutes"),))
    with db.tx() as c:
        for r in due:
            nxt = _next(datetime.fromisoformat(r["due_at"]), r["recurrence"])
            while nxt and nxt <= now:  # Mac spento a lungo: salta le occorrenze passate
                nxt = _next(nxt, r["recurrence"])
            if nxt:
                c.execute("UPDATE reminders SET due_at=? WHERE id=?", (nxt.isoformat(timespec="minutes"), r["id"]))
            else:
                c.execute("UPDATE reminders SET active=0 WHERE id=?", (r["id"],))
    return due


def describe(r: dict) -> str:
    rec = {"none": "", "daily": " (ogni giorno)", "weekdays": " (giorni feriali)", "weekly": " (ogni settimana)",
           "monthly": " (ogni mese)"}[r["recurrence"]]
    return f"#{r['id']} {fmt(datetime.fromisoformat(r['due_at']))}{rec} — {r['text']}"
