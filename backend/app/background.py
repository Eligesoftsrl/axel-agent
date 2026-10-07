"""Compiti lunghi in background: un sotto-agente lavora da solo mentre tu continui a parlare con AXEL.

Esempi: "cercami un volo per Lisbona sotto i 200 euro", "confronta questi 5 preventivi", "fammi una ricerca su…".
Il sotto-agente ha gli stessi strumenti di AXEL (ricerca web, email, documenti, collegamenti MCP…) e più passi a
disposizione. Le azioni che richiedono conferma restano in attesa come sempre. Quando finisce: bolla nell'app,
risultato completo su Telegram e nella cronologia.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid

from . import db, memory, store, tools

log = logging.getLogger("axel.background")

MAX_RUNNING = 3
LOOP: asyncio.AbstractEventLoop | None = None
_tasks: dict[str, asyncio.Task] = {}

SCHEMA = """
CREATE TABLE IF NOT EXISTS bg_tasks (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  instructions TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'running',   -- running | done | error | cancelled
  result TEXT,
  steps INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  finished_at TEXT
);
"""

PREAMBLE = (
    "Stai lavorando IN BACKGROUND per l'utente, che nel frattempo fa altro: non puoi fargli domande. "
    "Fai ipotesi ragionevoli e dichiarale. Lavora a fondo: cerca sul web più fonti, confronta, verifica numeri e date, "
    "usa gli strumenti che servono. Alla fine consegna un risultato completo e ordinato in italiano: prima una "
    "conclusione in 2-3 righe, poi i dettagli (elenchi o tabelle semplici in testo), con link alle fonti. "
    "Prezzi e disponibilità cambiano: indica quando li hai controllati.\n\nCompito: "
)


def init(loop: asyncio.AbstractEventLoop) -> None:
    global LOOP
    LOOP = loop
    with db.tx() as c:
        c.executescript(SCHEMA)
        c.execute("UPDATE bg_tasks SET status='error', result='Interrotto dal riavvio di AXEL' WHERE status='running'")


def list_recent(limit: int = 15) -> list[dict]:
    return db.query("SELECT id, title, status, steps, created_at, finished_at, substr(result, 1, 300) AS preview "
                    "FROM bg_tasks ORDER BY created_at DESC LIMIT ?", (limit,))


def get(tid: str) -> dict | None:
    rows = db.query("SELECT * FROM bg_tasks WHERE id=?", (tid,))
    return rows[0] if rows else None


def start(agent_id: str, title: str, instructions: str) -> str:
    """Avvia il compito (chiamabile da un thread). Restituisce l'id o un messaggio d'errore."""
    if not LOOP:
        return "errore: background non inizializzato"
    running = [t for t in _tasks.values() if not t.done()]
    if len(running) >= MAX_RUNNING:
        return f"errore: ci sono già {MAX_RUNNING} compiti in corso, aspetta che ne finisca uno"
    tid = uuid.uuid4().hex[:8]
    with db.tx() as c:
        c.execute("INSERT INTO bg_tasks(id, title, instructions) VALUES (?,?,?)", (tid, title[:120], instructions))

    def _spawn():
        _tasks[tid] = LOOP.create_task(_run(tid, agent_id, title, instructions))

    LOOP.call_soon_threadsafe(_spawn)
    return tid


def cancel(tid: str) -> bool:
    t = _tasks.get(tid)
    if t and not t.done():
        t.cancel()
        return True
    return False


async def _run(tid: str, agent_id: str, title: str, instructions: str) -> None:
    from . import agent as agent_loop

    agents = store.list_agents()
    cfg = next((a for a in agents if a.id == agent_id), agents[0])
    cfg = cfg.model_copy(update={"max_tokens": max(cfg.max_tokens, 6000),
                                 "tools": [t for t in cfg.tools if t != "background"]})  # niente compiti annidati
    ctx = tools.Ctx(agent_id=cfg.id, channel="background")
    text, steps = "", 0
    try:
        async for ev in agent_loop.run(cfg, [{"role": "user", "content": PREAMBLE + instructions}], ctx, max_steps=25):
            if ev["type"] == "text":
                text += ev["delta"]
            elif ev["type"] == "tool_use":
                steps += 1
                db.execute("UPDATE bg_tasks SET steps=? WHERE id=?", (steps, tid))
        status = "done"
    except asyncio.CancelledError:
        status, text = "cancelled", (text + "\n\n(Compito annullato.)").strip()
    except Exception as exc:  # noqa: BLE001
        log.exception("compito %s", tid)
        status, text = "error", f"Il compito si è interrotto: {exc}"
    text = text.strip() or "(nessun risultato)"
    db.execute("UPDATE bg_tasks SET status=?, result=?, finished_at=datetime('now') WHERE id=?", (status, text, tid))
    memory.log_message("axel", f"bg-{tid}", "assistant", text, f"Compito: {title}")
    if status == "cancelled":
        return
    summary = text.split("\n\n")[0][:240]
    db.notify("task_done", json.dumps({"id": tid, "title": title, "status": status, "summary": summary}, ensure_ascii=False))
    # risultato completo su Telegram (o email) — la notifica nell'app è la bolla
    try:
        from . import telegram

        await telegram.send(f"✅ Compito completato: {title}\n\n{text}" if status == "done" else f"⚠️ {title}\n\n{text}")
        for out in ctx.outputs:
            await telegram.send_file(out["path"], out["name"], out["mime"])
    except Exception as exc:  # noqa: BLE001
        log.warning("invio risultato: %s", exc)
