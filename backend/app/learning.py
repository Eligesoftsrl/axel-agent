"""Memoria che impara da sola + compattazione delle conversazioni lunghe.

Ogni sera (ora configurabile) un modello veloce rilegge le conversazioni della giornata (app e Telegram),
le confronta con ciò che AXEL già ricorda e:
  - salva fatti, preferenze, persone, progetti e decisioni nuovi e duraturi;
  - aggiorna i ricordi superati (es. un cliente che ha cambiato referente);
  - se qualcosa è ambiguo, non lo salva e te lo chiede (Telegram / app).
Compattazione: quando una conversazione nell'app diventa lunga, la parte vecchia viene riassunta in un paragrafo,
così AXEL resta veloce ed economico senza perdere il filo.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from . import db, llm, memory
from .google_api import tz

log = logging.getLogger("axel.learning")

COMPACT_AFTER = 24  # messaggi
KEEP_RECENT = 10
_summaries: dict[str, tuple[int, str]] = {}  # conversazione -> (messaggi riassunti, riassunto)


async def learn_today(agent_id: str) -> dict:
    rows = db.query("SELECT role, content, source FROM messages WHERE source IN ('axel','telegram') "
                    "AND created_at >= datetime('now','-24 hours') ORDER BY id")
    convo = "\n".join(f"{'Utente' if r['role'] == 'user' else 'AXEL'}: {r['content'][:600]}" for r in rows if r["content"])
    if len(convo) < 200:
        return {"saved": [], "updated": [], "questions": []}
    known = memory.list_all(agent_id, None, 300)
    known_txt = "\n".join(f"[{m['id']}] ({m['category']}) {m['content']}" for m in known) or "(niente)"
    data = await llm.ask_json(
        "Sei la memoria a lungo termine di un assistente personale. Rileggi le conversazioni di oggi tra l'utente e AXEL "
        "e confrontale con ciò che già sai.\n"
        f"Categorie: {', '.join(memory.CATEGORIES)}.\n"
        "Salva SOLO informazioni utili anche fra settimane: fatti sull'utente, preferenze, persone e relazioni, clienti e "
        "progetti, decisioni prese, abitudini. NON salvare: richieste del momento (meteo, musica, ora), cose già presenti, "
        "dettagli effimeri, contenuti di email di terzi, dati sensibili (salute, password, dati bancari).\n"
        "Se un ricordo esistente è superato, aggiornalo. Se un'informazione è plausibile ma ambigua o dedotta, NON salvarla: "
        "mettila tra le domande (massimo 2, brevi, in italiano, dando del tu).\n\n"
        f"Ricordi esistenti:\n{known_txt[:12000]}\n\nConversazioni di oggi:\n{convo[-24000:]}\n\n"
        'Formato: {"save": [{"content": "...", "category": "..."}], "update": [{"id": 0, "content": "..."}], '
        '"questions": ["..."]}',
        max_tokens=1500,
    ) or {}
    saved, updated = [], []
    for s in (data.get("save") or [])[:8]:
        c = (s.get("content") or "").strip()
        if 8 < len(c) < 400:
            memory.save(agent_id, c, s.get("category") or "generale")
            saved.append(c)
    ids = {m["id"]: m for m in known}
    for u in (data.get("update") or [])[:5]:
        try:
            old = ids.get(int(u.get("id")))
        except (TypeError, ValueError):
            continue
        c = (u.get("content") or "").strip()
        if old and c and c != old["content"]:
            memory.delete(agent_id, old["id"])
            memory.save(agent_id, c, old["category"])
            updated.append(c)
    questions = [q for q in (data.get("questions") or []) if isinstance(q, str)][:2]
    return {"saved": saved, "updated": updated, "questions": questions}


async def check(deliver, agent_id: str, settings: dict) -> None:
    """Chiamato dal ciclo proattivo: una volta al giorno, all'ora impostata."""
    if not settings.get("memory_learning", True):
        return
    now = datetime.now(tz())
    hh, mm = (int(x) for x in str(settings.get("learning_time", "23:30")).split(":"))
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    today = now.date().isoformat()
    if db.get_setting("learning_last_date") == today or now < target or (now - target).total_seconds() > 3 * 3600:
        return
    db.set_setting("learning_last_date", today)
    res = await learn_today(agent_id)
    n = len(res["saved"]) + len(res["updated"])
    log.info("memoria: %d nuovi, %d aggiornati, %d domande", len(res["saved"]), len(res["updated"]), len(res["questions"]))
    db.set_setting("learning_last_result", {"date": today, **res})
    if n:
        lines = "\n".join(f"• {c}" for c in res["saved"] + res["updated"])
        db.notify("info", f"🧠 Oggi ho imparato {n} {'cosa' if n == 1 else 'cose'} su di te:\n{lines}")
    if res["questions"]:
        q = "\n".join(f"• {x}" for x in res["questions"])
        await deliver("info", f"🧠 Prima di ricordarlo, me lo confermi?\n{q}\n(Rispondimi pure qui o nell'app.)",
                      subject="Una domanda da AXEL")


# ---------- compattazione ----------

async def compact(conversation_id: str, history: list[dict]) -> list[dict]:
    """Se la conversazione è lunga, sostituisce la parte vecchia con un riassunto (in cache per conversazione)."""
    if len(history) <= COMPACT_AFTER:
        return history
    # taglio a blocchi di 10: il riassunto (e quindi la cache dei prompt) cambia solo ogni 10 messaggi
    cut = ((len(history) - KEEP_RECENT) // 10) * 10
    while cut < len(history) and history[cut]["role"] != "user":  # la parte recente deve iniziare dall'utente
        cut += 1
    old, recent = history[:cut], history[cut:]
    if not recent:
        return history
    cached = _summaries.get(conversation_id)
    if cached and cached[0] == len(old):
        summary = cached[1]
    else:
        prev = cached[1] if cached and cached[0] < len(old) else ""
        start = cached[0] if prev else 0
        text = "\n".join(f"{'Utente' if m['role'] == 'user' else 'AXEL'}: {_plain(m['content'])[:800]}" for m in old[start:])
        summary = await llm.ask_text(
            "Riassumi questa conversazione tra l'utente e il suo assistente AXEL in un paragrafo denso (massimo 180 parole): "
            "argomenti, decisioni, dati importanti (nomi, numeri, date), cose rimaste in sospeso. Niente premesse.\n\n"
            + (f"Riassunto precedente: {prev}\n\nSeguito:\n" if prev else "") + text,
            max_tokens=500,
        )
        if not summary:
            return history  # senza riassunto non tagliamo nulla
        _summaries[conversation_id] = (len(old), summary)
    return [{"role": "user", "content": f"[Riassunto della prima parte di questa conversazione]\n{summary}"},
            {"role": "assistant", "content": "Ok, ho presente il contesto."}] + recent


def _plain(content) -> str:
    if isinstance(content, str):
        return content
    return " ".join(b.get("text", "[allegato]") for b in content if isinstance(b, dict))
