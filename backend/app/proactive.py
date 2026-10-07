"""Proattività: AXEL ti cerca lui.

- avvisi prima degli appuntamenti del calendario;
- segnalazione delle email importanti appena arrivano (filtrate da Claude con un modello veloce);
- riepilogo serale della giornata;
- esecuzione dei compiti ricorrenti (tasks.py).
Le impostazioni stanno nel database (chiave "proactive") e si cambiano dal pannello Integrazioni.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta

from . import db, google_api, memory, store, tasks, tools
from .google_api import tz

log = logging.getLogger("axel.proactive")

DEFAULTS = {
    "event_alerts": True,
    "event_lead_min": 15,
    "email_alerts": True,
    "mail_bubbles": True,
    "email_interval_min": 10,
    "shipments": True,
    "vip_senders": [],      # sempre importanti: email, @dominio o nome (es. "mario.rossi@x.it", "@perfexia.it", "Banca")
    "ignore_senders": [],   # mai importanti
    "email_rules": "",      # in parole tue: cosa conta per te
    "memory_learning": True,
    "learning_time": "23:30",
    "evening_recap": False,
    "recap_time": "21:00",
    "recap_last_date": None,
}
TRIAGE_MODEL = os.getenv("TRIAGE_MODEL", "claude-haiku-4-5-20251001")

_last_calendar_check = 0.0
_last_email_check = 0.0


def settings() -> dict:
    return {**DEFAULTS, **(db.get_setting("proactive") or {})}


def save(s: dict) -> dict:
    cur = settings()
    cur.update({k: v for k, v in s.items() if k in DEFAULTS})
    db.set_setting("proactive", cur)
    return cur


def _agent() -> store.AgentConfig:
    agents = store.list_agents()
    return next((a for a in agents if a.id == db.get_setting("telegram_agent")), agents[0])


def _google_ok() -> bool:
    return bool(db.get_setting("google_token"))


# ---------- avvisi appuntamenti ----------

def upcoming_events(lead_min: int) -> list[dict]:
    now = datetime.now(tz())
    res = (
        google_api._svc("calendar", "v3").events()
        .list(calendarId="primary", timeMin=now.isoformat(), timeMax=(now + timedelta(minutes=lead_min + 1)).isoformat(),
              singleEvents=True, orderBy="startTime", maxResults=10)
        .execute()
    )
    out = []
    for e in res.get("items", []):
        start = e["start"].get("dateTime")
        if not start:  # eventi di tutto il giorno: niente avviso
            continue
        out.append({"id": e["id"] + start, "title": e.get("summary", "(senza titolo)"),
                    "start": datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(tz()),
                    "location": e.get("location", ""), "link": e.get("hangoutLink", "")})
    return out


async def check_events(deliver) -> None:
    s = settings()
    if not s["event_alerts"] or not _google_ok():
        return
    seen = set(db.get_setting("notified_events") or [])
    events = await asyncio.to_thread(upcoming_events, int(s["event_lead_min"]))
    for e in events:
        if e["id"] in seen:
            continue
        mins = max(0, round((e["start"] - datetime.now(tz())).total_seconds() / 60))
        extra = f"\n📍 {e['location']}" if e["location"] else ""
        extra += f"\n🔗 {e['link']}" if e["link"] else ""
        await deliver("alert", f"🗓 Tra {mins} minuti: {e['title']} (alle {e['start']:%H:%M}){extra}",
                      subject=f"Tra {mins} min: {e['title']}")
        seen.add(e["id"])
    db.set_setting("notified_events", list(seen)[-200:])


# ---------- email importanti ----------

def _new_unread() -> list[dict]:
    svc = google_api._svc("gmail", "v1")
    q = "is:unread newer_than:1d in:inbox -category:promotions -category:social -category:updates -category:forums"
    vip = [v.strip() for v in (settings().get("vip_senders") or []) if v.strip()]
    if vip:  # i mittenti prioritari contano anche se Gmail li mette in Aggiornamenti o Promozioni
        terms = " ".join(f'from:"{v.lstrip("@")}"' if " " in v else f"from:{v.lstrip('@')}" for v in vip[:30])
        q = ("is:unread newer_than:1d in:inbox {(-category:promotions -category:social -category:updates -category:forums) "
             + terms + "}")
    ids = [m["id"] for m in svc.users().messages().list(userId="me", q=q, maxResults=15).execute().get("messages", [])]
    stored = db.get_setting("seen_emails")
    if stored is None:  # primo avvio: non segnalare gli arretrati
        db.set_setting("seen_emails", ids)
        return []
    seen = set(stored)
    fresh = [i for i in ids if i not in seen]
    out = []
    for mid in fresh:
        m = svc.users().messages().get(userId="me", id=mid, format="metadata",
                                        metadataHeaders=["From", "Subject"]).execute()
        out.append({"id": mid, "from": google_api._header(m, "From"), "subject": google_api._header(m, "Subject"),
                    "snippet": m.get("snippet", "")[:200]})
    db.set_setting("seen_emails", (list(seen) + fresh)[-500:])
    return out


def _match_sender(raw_from: str, rules: list[str]) -> str | None:
    """True se il mittente corrisponde a una regola: indirizzo esatto, @dominio, oppure parte del nome."""
    low = (raw_from or "").lower()
    addr = low[low.find("<") + 1: low.find(">")] if "<" in low else low.strip()
    for r in rules:
        r = (r or "").strip().lower()
        if not r:
            continue
        if r.startswith("@") and addr.endswith(r):
            return r
        if "@" in r and not r.startswith("@") and addr == r:
            return r
        if "@" not in r and r in low:
            return r
    return None


async def triage(emails: list[dict], agent_id: str) -> list[dict]:
    """Decide quali email meritano un avviso: prima le tue regole (mittenti prioritari e ignorati), poi Claude."""
    if not emails:
        return []
    s = settings()
    vip, rest = [], []
    for e in emails:
        if _match_sender(e["from"], s.get("ignore_senders") or []):
            continue
        hit = _match_sender(e["from"], s.get("vip_senders") or [])
        if hit:
            vip.append({**e, "why": "mittente prioritario"})
        else:
            rest.append(e)
    return vip + await _triage_ai(rest, agent_id, s.get("email_rules") or "")


async def _triage_ai(emails: list[dict], agent_id: str, rules: str) -> list[dict]:
    if not emails or not os.getenv("ANTHROPIC_API_KEY"):
        return []
    from anthropic import AsyncAnthropic

    profile = memory.context_for(agent_id, " ".join(e["subject"] for e in emails))
    listing = "\n".join(f"[{e['id']}] Da: {e['from']} | Oggetto: {e['subject']} | {e['snippet']}" for e in emails)
    prompt = (
        "Sei il filtro email di un assistente personale. Segnala SOLO le email che l'utente vorrebbe sapere subito: "
        "persone reali che scrivono a lui (familiari, amici, clienti, colleghi), scadenze, pagamenti, problemi di "
        "sicurezza, appuntamenti. Ignora newsletter, notifiche automatiche, marketing, ricevute di routine.\n\n"
        + (f"Regole dell'utente (hanno la precedenza): {rules}\n\n" if rules.strip() else "")
        + f"Cosa sai dell'utente:\n{profile or '(niente)'}\n\nEmail nuove:\n{listing}\n\n"
        'Rispondi solo con JSON: {"important": [{"id": "...", "why": "motivo in 8 parole"}]}'
    )
    client = AsyncAnthropic()
    msg = await client.messages.create(model=TRIAGE_MODEL, max_tokens=400, messages=[{"role": "user", "content": prompt}])
    text = "".join(b.text for b in msg.content if b.type == "text")
    try:
        data = json.loads(text[text.index("{"): text.rindex("}") + 1])
    except ValueError:
        return []
    by_id = {e["id"]: e for e in emails}
    return [{**by_id[i["id"]], "why": i.get("why", "")} for i in data.get("important", []) if i.get("id") in by_id]


def _sender_name(raw: str) -> str:
    return raw.split("<")[0].strip().strip('"') or raw


async def check_emails(deliver) -> None:
    s = settings()
    if not (s["email_alerts"] or s["mail_bubbles"]) or not _google_ok():
        return
    emails = await asyncio.to_thread(_new_unread)
    if s["mail_bubbles"]:  # bolla nell'app per ogni nuova email (non va su Telegram)
        for e in emails[:5]:
            db.notify("mail", json.dumps({
                "id": e["id"], "from": _sender_name(e["from"]), "email": e["from"], "subject": e["subject"] or "(senza oggetto)",
                "snippet": e["snippet"], "link": f"https://mail.google.com/mail/u/0/#all/{e['id']}",
            }, ensure_ascii=False))
    if not s["email_alerts"]:
        return
    important = await triage(emails, _agent().id)
    for e in important:
        sender = e["from"].split("<")[0].strip().strip('"') or e["from"]
        await deliver("alert", f"✉️ Email importante da {sender}: «{e['subject']}»\n{e['why']}",
                      subject=f"Email importante: {e['subject'][:60]}")


# ---------- compiti ricorrenti + riepilogo serale ----------

RECAP_PROMPT = (
    "Fammi il riepilogo serale della mia giornata, breve e utile:\n"
    "1. Cosa avevo in calendario oggi e cosa ho domani (i primi impegni).\n"
    "2. Email importanti di oggi a cui sembra che io non abbia ancora risposto.\n"
    "3. Promemoria e compiti in scadenza domani.\n"
    "4. Cose da fare emerse nelle conversazioni di oggi con te (cerca nello storico).\n"
    "Chiudi con una frase di incoraggiamento, senza retorica."
)


async def run_prompt(prompt: str, title: str) -> str:
    from .agent import run_once

    agent = _agent()
    agent = agent.model_copy(update={"max_tokens": max(agent.max_tokens, 2000)})
    text, _ = await run_once(agent, [{"role": "user", "content": prompt}], tools.Ctx(agent_id=agent.id, channel="briefing"))
    memory.log_message("axel", "proactive", "assistant", text, title)
    return text


async def check_tasks(deliver) -> None:
    for t in await asyncio.to_thread(tasks.pop_due):
        try:
            text = await run_prompt(t["prompt"], t["title"])
            await deliver("task", f"🔁 {t['title']}\n\n{text}", subject=t["title"])
        except Exception:  # noqa: BLE001
            log.exception("compito %s fallito", t["id"])


async def check_recap(deliver) -> None:
    s = settings()
    if not s["evening_recap"]:
        return
    now = datetime.now(tz())
    hh, mm = (int(x) for x in s["recap_time"].split(":"))
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    today = now.date().isoformat()
    if s.get("recap_last_date") != today and target <= now and (now - target).total_seconds() < 3 * 3600:
        s["recap_last_date"] = today
        db.set_setting("proactive", s)
        text = await run_prompt(RECAP_PROMPT, f"Riepilogo {now:%d/%m}")
        await deliver("recap", f"🌙 Riepilogo della giornata\n\n{text}", subject="Il tuo riepilogo serale")


async def tick(deliver) -> None:
    """Chiamato dallo scheduler ogni ~20 s; calendario ogni 2 min, email ogni N minuti (impostazione)."""
    global _last_calendar_check, _last_email_check
    await check_tasks(deliver)
    await check_recap(deliver)
    try:
        from . import backup

        await backup.check()
    except Exception as exc:  # noqa: BLE001
        log.warning("copia di sicurezza: %s", exc)
    try:
        from . import learning

        await learning.check(deliver, _agent().id, settings())
    except Exception as exc:  # noqa: BLE001
        log.warning("apprendimento memoria: %s", exc)
    now = time.time()
    if now - _last_calendar_check > 120:
        _last_calendar_check = now
        try:
            await check_events(deliver)
        except Exception as exc:  # noqa: BLE001
            log.warning("avvisi calendario: %s", exc)
        try:  # "parti ora": appuntamenti con indirizzo nelle prossime 3 ore
            from . import maps

            if maps.settings()["leave_alerts"] and maps.settings()["home"] and _google_ok():
                await maps.check_leave(deliver, await asyncio.to_thread(upcoming_events, 180))
        except Exception as exc:  # noqa: BLE001
            log.warning("avviso partenza: %s", exc)
    if now - _last_email_check > max(2, int(settings()["email_interval_min"])) * 60:
        _last_email_check = now
        try:
            await check_emails(deliver)
        except Exception as exc:  # noqa: BLE001
            log.warning("controllo email: %s", exc)
        if settings().get("shipments", True) and _google_ok():
            try:
                from . import shipments

                await shipments.check(deliver)
            except Exception as exc:  # noqa: BLE001
                log.warning("spedizioni: %s", exc)
