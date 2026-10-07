"""Attività in background: promemoria scaduti e briefing mattutino."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from . import db, google_api, memory, proactive, reminders, store, telegram, tools
from .google_api import tz

log = logging.getLogger("axel.scheduler")

DEFAULT_BRIEFING = {"enabled": False, "time": "07:30", "city": "Roma", "last_date": None}


def briefing_settings() -> dict:
    return {**DEFAULT_BRIEFING, **(db.get_setting("briefing") or {})}


async def deliver(kind: str, text: str, subject: str = "AXEL") -> str:
    """Telegram se collegato, altrimenti email a te stesso. Sempre anche notifica nella UI."""
    db.notify(kind, text)
    if await telegram.send(text):
        return "telegram"
    try:
        if await asyncio.to_thread(google_api.send_to_self, subject, text):
            return "email"
    except Exception as exc:  # noqa: BLE001
        log.warning("email di notifica fallita: %s", exc)
    return "ui"


BRIEFING_PROMPT = (
    "Prepara il mio briefing di oggi. Usa gli strumenti disponibili e salta le sezioni che non puoi compilare:\n"
    "1. Meteo a {city} per oggi.\n"
    "2. Appuntamenti di oggi dal calendario (e il primo di domani).\n"
    "3. Email importanti non lette delle ultime 24 ore, riassunte in una riga ciascuna (ignora newsletter e promozioni).\n"
    "4. Promemoria in scadenza oggi.\n"
    "5. {news}\n"
    "6. Pacchi in arrivo oggi o in ritardo (shipments_list), se ce ne sono.\n"
    "7. Per il primo appuntamento con un indirizzo, quanto ci metto ad arrivare (travel_time) e quando partire.\n"
    "Chiudi con un suggerimento pratico per la giornata."
)
NEWS_RSS = "Notizie: usa news_digest e riporta le notizie con la fonte."
NEWS_WEB = "Tre notizie rilevanti per i miei interessi (cerca in memoria cosa mi interessa, poi usa la ricerca web)."


def _news_line() -> str:
    from . import news

    ns = news.settings()
    if ns["feeds"] and ns.get("in_briefing", True):
        return NEWS_RSS
    return NEWS_WEB


async def build_briefing() -> str:
    from .agent import run_once

    agents = store.list_agents()
    agent = next((a for a in agents if a.id == db.get_setting("telegram_agent")), agents[0])
    agent = agent.model_copy(update={"max_tokens": max(agent.max_tokens, 2000)})
    city = briefing_settings()["city"]
    ctx = tools.Ctx(agent_id=agent.id, channel="briefing")
    text, _ = await run_once(agent, [{"role": "user", "content": BRIEFING_PROMPT.format(city=city, news=_news_line())}], ctx)
    memory.log_message("axel", "briefing", "assistant", text, f"Briefing {datetime.now(tz()):%d/%m}")
    return text


async def send_briefing(force: bool = False) -> str:
    text = await build_briefing()
    channel = await deliver("briefing", f"☀️ Buongiorno!\n\n{text}", subject="Il tuo briefing di AXEL")
    s = briefing_settings()
    s["last_date"] = datetime.now(tz()).date().isoformat()
    db.set_setting("briefing", s)
    return channel


async def tick() -> None:
    for r in await asyncio.to_thread(reminders.pop_due):
        await deliver("reminder", f"⏰ Promemoria: {r['text']}", subject=f"Promemoria: {r['text'][:60]}")

    s = briefing_settings()
    if s["enabled"]:
        now = datetime.now(tz())
        hh, mm = (int(x) for x in s["time"].split(":"))
        target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        today = now.date().isoformat()
        # se il Mac era spento all'ora giusta, recupera entro 4 ore
        if s.get("last_date") != today and target <= now and (now - target).total_seconds() < 4 * 3600:
            try:
                await send_briefing()
            except Exception:  # noqa: BLE001
                log.exception("briefing fallito")
                s["last_date"] = today  # evita tentativi in loop
                db.set_setting("briefing", s)


async def tick_all() -> None:
    await tick()
    await proactive.tick(deliver)


async def run_forever() -> None:
    while True:
        try:
            await tick_all()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("scheduler")
        await asyncio.sleep(20)
