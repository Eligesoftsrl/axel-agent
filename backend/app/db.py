"""Database SQLite locale (backend/data/axel.db).

Tabelle: memorie, messaggi (AXEL + chat importate da claude.ai), promemoria,
azioni in attesa di conferma, notifiche, impostazioni chiave/valore.
La ricerca testuale usa FTS5 (incluso in SQLite) — niente servizi esterni.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "axel.db"

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None
FTS = True

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_id TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'generale',
  content TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,            -- 'axel' | 'telegram' | 'claude'
  conversation_id TEXT NOT NULL,
  conversation_title TEXT,
  role TEXT NOT NULL,              -- 'user' | 'assistant'
  content TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, id);
CREATE TABLE IF NOT EXISTS reminders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_id TEXT NOT NULL,
  text TEXT NOT NULL,
  due_at TEXT NOT NULL,            -- ISO locale, es. 2026-10-06T18:00:00
  recurrence TEXT NOT NULL DEFAULT 'none',  -- none|daily|weekdays|weekly|monthly
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS actions (
  id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  name TEXT NOT NULL,
  args TEXT NOT NULL,
  summary TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',   -- pending|done|rejected|error
  result TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,              -- reminder|briefing|info
  text TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  day TEXT NOT NULL,               -- YYYY-MM-DD locale
  channel TEXT NOT NULL,           -- ui | telegram | briefing | fastlane
  model TEXT NOT NULL,
  input INTEGER NOT NULL DEFAULT 0,
  output INTEGER NOT NULL DEFAULT 0,
  cache_read INTEGER NOT NULL DEFAULT 0,
  cache_write INTEGER NOT NULL DEFAULT 0,
  ms INTEGER NOT NULL DEFAULT 0,   -- tempo alla prima parola
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_usage_day ON usage(day);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(content, category, content='memories', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
  INSERT INTO memories_fts(rowid, content, category) VALUES (new.id, new.content, new.category);
END;
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
  INSERT INTO memories_fts(memories_fts, rowid, content, category) VALUES ('delete', old.id, old.content, old.category);
END;
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(content, conversation_title, content='messages', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
  INSERT INTO messages_fts(rowid, content, conversation_title) VALUES (new.id, new.content, new.conversation_title);
END;
CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
  INSERT INTO messages_fts(messages_fts, rowid, content, conversation_title) VALUES ('delete', old.id, old.content, old.conversation_title);
END;
"""


def conn() -> sqlite3.Connection:
    global _conn, FTS
    if _conn is None:
        c = sqlite3.connect(DB_PATH, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA)
        try:
            c.executescript(FTS_SCHEMA)
        except sqlite3.OperationalError:
            FTS = False  # SQLite senza FTS5: si ripiega su LIKE
        c.commit()
        _conn = c
    return _conn


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    with _lock:
        c = conn()
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise


def query(sql: str, params: tuple | list = ()) -> list[dict]:
    with _lock:
        return [dict(r) for r in conn().execute(sql, params).fetchall()]


def execute(sql: str, params: tuple | list = ()) -> None:
    with tx() as c:
        c.execute(sql, params)


def fts_query(text: str) -> str:
    """Trasforma testo libero in una query FTS5 sicura (parole in OR, prefisso)."""
    words = [w for w in "".join(ch if ch.isalnum() else " " for ch in text).split() if len(w) > 2]
    return " OR ".join(f'"{w}"*' for w in words[:12])


# ---------- impostazioni ----------

def get_setting(key: str, default: Any = None) -> Any:
    rows = query("SELECT value FROM settings WHERE key=?", (key,))
    return json.loads(rows[0]["value"]) if rows else default


def set_setting(key: str, value: Any) -> None:
    with tx() as c:
        c.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )


def del_setting(key: str) -> None:
    with tx() as c:
        c.execute("DELETE FROM settings WHERE key=?", (key,))


def notify(kind: str, text: str) -> None:
    with tx() as c:
        c.execute("INSERT INTO notifications(kind, text) VALUES(?, ?)", (kind, text))
