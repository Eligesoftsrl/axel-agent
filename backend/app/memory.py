"""Memoria a lungo termine, storico conversazioni e import delle chat di claude.ai."""
from __future__ import annotations

import io
import json
import zipfile

from . import db

CATEGORIES = ["profilo", "preferenze", "lavoro", "progetti", "persone", "salute", "casa", "generale"]


# ---------- memorie ----------

def save(agent_id: str, content: str, category: str = "generale") -> int:
    category = category if category in CATEGORIES else "generale"
    # evita duplicati identici
    dup = db.query("SELECT id FROM memories WHERE agent_id=? AND content=?", (agent_id, content.strip()))
    if dup:
        return dup[0]["id"]
    with db.tx() as c:
        cur = c.execute(
            "INSERT INTO memories(agent_id, category, content) VALUES(?,?,?)",
            (agent_id, category, content.strip()),
        )
        return int(cur.lastrowid)


def delete(agent_id: str, memory_id: int) -> bool:
    with db.tx() as c:
        cur = c.execute("DELETE FROM memories WHERE id=? AND agent_id=?", (memory_id, agent_id))
        return cur.rowcount > 0


def list_all(agent_id: str, category: str | None = None, limit: int = 200) -> list[dict]:
    if category:
        return db.query(
            "SELECT * FROM memories WHERE agent_id=? AND category=? ORDER BY id DESC LIMIT ?",
            (agent_id, category, limit),
        )
    return db.query("SELECT * FROM memories WHERE agent_id=? ORDER BY id DESC LIMIT ?", (agent_id, limit))


def search(agent_id: str, text: str, limit: int = 8) -> list[dict]:
    q = db.fts_query(text)
    if not q:
        return []
    if db.FTS:
        return db.query(
            """SELECT m.* FROM memories_fts f JOIN memories m ON m.id = f.rowid
               WHERE memories_fts MATCH ? AND m.agent_id=? ORDER BY rank LIMIT ?""",
            (q, agent_id, limit),
        )
    like = f"%{text[:40]}%"
    return db.query("SELECT * FROM memories WHERE agent_id=? AND content LIKE ? LIMIT ?", (agent_id, like, limit))


def context_for(agent_id: str, last_user_text: str) -> str:
    """Memorie da iniettare nel prompt: profilo sempre + le più pertinenti alla domanda."""
    profile = db.query(
        "SELECT * FROM memories WHERE agent_id=? AND category IN ('profilo','preferenze') ORDER BY id DESC LIMIT 25",
        (agent_id,),
    )
    relevant = search(agent_id, last_user_text, 8)
    seen, lines = set(), []
    for m in profile + relevant:
        if m["id"] in seen:
            continue
        seen.add(m["id"])
        lines.append(f"- [{m['category']}] {m['content']} (#{m['id']})")
    return "\n".join(lines)


# ---------- storico conversazioni ----------

def log_message(source: str, conversation_id: str, role: str, content: str, title: str | None = None) -> None:
    if not content.strip():
        return
    with db.tx() as c:
        c.execute(
            "INSERT INTO messages(source, conversation_id, conversation_title, role, content) VALUES(?,?,?,?,?)",
            (source, conversation_id, title, role, content),
        )


def recent(conversation_id: str, limit: int = 20) -> list[dict]:
    rows = db.query(
        "SELECT role, content FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?",
        (conversation_id, limit),
    )
    return list(reversed(rows))


def search_history(text: str, source: str = "all", limit: int = 12) -> list[dict]:
    q = db.fts_query(text)
    if not q:
        return []
    src_sql, params = "", [q]
    if source in ("axel", "claude", "telegram"):
        src_sql = " AND m.source=?"
        params.append(source)
    params.append(limit)
    if db.FTS:
        return db.query(
            f"""SELECT m.source, m.conversation_title, m.role, m.created_at,
                       snippet(messages_fts, 0, '«', '»', ' … ', 40) AS snippet
                FROM messages_fts JOIN messages m ON m.id = messages_fts.rowid
                WHERE messages_fts MATCH ?{src_sql} ORDER BY rank LIMIT ?""",
            params,
        )
    return db.query(
        "SELECT source, conversation_title, role, created_at, substr(content,1,300) AS snippet FROM messages "
        "WHERE content LIKE ? LIMIT ?",
        (f"%{text[:40]}%", limit),
    )


def recent_claude_conversations(limit: int = 15) -> list[dict]:
    return db.query(
        """SELECT conversation_title, MAX(created_at) AS last_at, COUNT(*) AS n
           FROM messages WHERE source='claude' GROUP BY conversation_id
           ORDER BY last_at DESC LIMIT ?""",
        (limit,),
    )


def claude_conversation(title_query: str, max_chars: int = 12000) -> str:
    """Testo di una conversazione importata (ricerca per titolo), troncato."""
    conv = db.query(
        "SELECT conversation_id, conversation_title FROM messages WHERE source='claude' AND conversation_title LIKE ? "
        "ORDER BY created_at DESC LIMIT 1",
        (f"%{title_query}%",),
    )
    if not conv:
        return "Nessuna conversazione con questo titolo."
    rows = db.query(
        "SELECT role, content FROM messages WHERE conversation_id=? ORDER BY id", (conv[0]["conversation_id"],)
    )
    text = f"Conversazione: {conv[0]['conversation_title']}\n\n" + "\n\n".join(
        f"{'Utente' if r['role'] == 'user' else 'Claude'}: {r['content']}" for r in rows
    )
    return text[:max_chars] + ("\n…(troncata)" if len(text) > max_chars else "")


# ---------- import export claude.ai ----------

def import_claude_export(data: bytes, filename: str) -> dict:
    """Accetta lo .zip dell'export di claude.ai o direttamente conversations.json."""
    if filename.lower().endswith(".zip") or data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            name = next((n for n in z.namelist() if n.endswith("conversations.json")), None)
            if not name:
                raise ValueError("conversations.json non trovato nello zip")
            data = z.read(name)
    convs = json.loads(data.decode("utf-8"))
    if isinstance(convs, dict):
        convs = convs.get("conversations", [])

    imported_convs = imported_msgs = skipped = 0
    with db.tx() as c:
        for conv in convs:
            cid = "claude:" + str(conv.get("uuid") or conv.get("id"))
            if c.execute("SELECT 1 FROM messages WHERE conversation_id=? LIMIT 1", (cid,)).fetchone():
                skipped += 1
                continue
            title = conv.get("name") or "Senza titolo"
            n = 0
            for m in conv.get("chat_messages", []):
                text = m.get("text") or ""
                if not text and isinstance(m.get("content"), list):
                    text = "\n".join(p.get("text", "") for p in m["content"] if isinstance(p, dict))
                if not text.strip():
                    continue
                role = "user" if m.get("sender") == "human" else "assistant"
                created = (m.get("created_at") or conv.get("created_at") or "")[:19].replace("T", " ")
                c.execute(
                    "INSERT INTO messages(source, conversation_id, conversation_title, role, content, created_at) "
                    "VALUES('claude',?,?,?,?,COALESCE(NULLIF(?, ''), datetime('now')))",
                    (cid, title, role, text, created),
                )
                n += 1
            if n:
                imported_convs += 1
                imported_msgs += n
    return {"conversations": imported_convs, "messages": imported_msgs, "skipped": skipped}


def stats() -> dict:
    r = db.query(
        "SELECT source, COUNT(DISTINCT conversation_id) AS convs, COUNT(*) AS msgs FROM messages GROUP BY source"
    )
    return {row["source"]: {"conversations": row["convs"], "messages": row["msgs"]} for row in r}
