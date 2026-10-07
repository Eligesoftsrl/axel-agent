"""Bot Telegram: notifiche (promemoria, briefing) e chat con AXEL dal telefono.

Funziona in "long polling": nessun indirizzo pubblico necessario, basta che il Mac sia acceso.
Sicurezza: il bot risponde solo alla chat collegata tramite il codice di abbinamento
mostrato nel pannello Integrazioni.
"""
from __future__ import annotations

import asyncio
import logging
import os
import secrets

import httpx

from . import actions, db, memory, store, tools

log = logging.getLogger("axel.telegram")
API = "https://api.telegram.org/bot{token}/{method}"


def token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def chat_id() -> int | None:
    return db.get_setting("telegram_chat_id")


def pair_code() -> str:
    code = db.get_setting("telegram_pair_code")
    if not code:
        code = secrets.token_hex(3).upper()
        db.set_setting("telegram_pair_code", code)
    return code


def status() -> dict:
    return {
        "configured": bool(token()),
        "linked": chat_id() is not None,
        "bot": db.get_setting("telegram_bot_username"),
        "pair_code": pair_code() if token() and chat_id() is None else None,
    }


def unlink() -> None:
    db.del_setting("telegram_chat_id")
    db.del_setting("telegram_pair_code")


async def call(method: str, **payload) -> dict:
    async with httpx.AsyncClient(timeout=40) as c:
        r = await c.post(API.format(token=token(), method=method), json=payload)
        return r.json()


async def download(file_id: str) -> bytes:
    info = await call("getFile", file_id=file_id)
    path = info.get("result", {}).get("file_path")
    if not path:
        raise RuntimeError("file non disponibile")
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.get(f"https://api.telegram.org/file/bot{token()}/{path}")
        r.raise_for_status()
        return r.content


async def send_voice(text: str, to: int | None = None) -> bool:
    """Risponde con una nota vocale (voce italiana del Mac)."""
    from . import tts

    target = to or chat_id()
    if not token() or not target or not (tts.available() or (tts.google_key() and (_agent().voice or "").startswith("google:"))):
        return False
    try:
        audio, kind = await asyncio.to_thread(tts.synthesize, text, _agent().voice or "")
    except Exception as exc:  # noqa: BLE001
        log.warning("vocale non generato: %s", exc)
        return False
    method, field, name = ("sendVoice", "voice", "axel.ogg") if kind == "voice" else ("sendAudio", "audio", "axel.m4a")
    async with httpx.AsyncClient(timeout=60) as c:
        await c.post(API.format(token=token(), method=method), data={"chat_id": str(target)},
                     files={field: (name, audio)})
    return True


async def send_file(path: str, name: str, mime: str, to: int | None = None) -> None:
    target = to or chat_id()
    if not token() or not target:
        return
    photo = mime.startswith("image/") and not mime.endswith("svg+xml")
    method, field = ("sendPhoto", "photo") if photo else ("sendDocument", "document")
    with open(path, "rb") as f:
        async with httpx.AsyncClient(timeout=60) as c:
            await c.post(API.format(token=token(), method=method), data={"chat_id": str(target)}, files={field: (name, f.read())})


def voice_reply_enabled() -> bool:
    return bool(db.get_setting("telegram_voice_reply", True))


async def send(text: str, buttons: list[list[dict]] | None = None, to: int | None = None) -> bool:
    target = to or chat_id()
    if not token() or not target:
        return False
    chunks = [text[i:i + 3900] for i in range(0, len(text), 3900)] or [""]
    for i, chunk in enumerate(chunks):
        payload: dict = {"chat_id": target, "text": chunk, "disable_web_page_preview": True}
        if buttons and i == len(chunks) - 1:
            payload["reply_markup"] = {"inline_keyboard": buttons}
        await call("sendMessage", **payload)
    return True


def _agent() -> store.AgentConfig:
    agents = store.list_agents()
    wanted = db.get_setting("telegram_agent")
    return next((a for a in agents if a.id == wanted), agents[0])


async def _handle_voice(chat: int, voice: dict) -> None:
    """Nota vocale: trascrizione con Whisper, poi come un messaggio scritto (e risposta anche a voce)."""
    from . import stt

    await call("sendChatAction", chat_id=chat, action="typing")
    try:
        data = await download(voice["file_id"])
        res = await asyncio.to_thread(stt.transcribe_any, data)
    except stt.STTUnavailable as exc:
        await send(f"Non riesco ad ascoltare i vocali: {exc}")
        return
    except Exception as exc:  # noqa: BLE001
        log.exception("vocale Telegram")
        await send(f"Non sono riuscito a trascrivere il vocale: {exc}")
        return
    text = res["text"]
    if not text:
        await send("Non ho capito il vocale, puoi ripetere?")
        return
    await send(f"🎙 «{text}»")
    await _handle_text(chat, text, voice=True)


async def _handle_text(chat: int, text: str, voice: bool = False, attachments: list[str] | None = None) -> None:
    from .scheduler import send_briefing

    if text.strip().lower() in ("/briefing", "briefing"):
        await send("Preparo il briefing…")
        await send_briefing(force=True)
        return
    if text.startswith("/start"):
        await send("Sono AXEL. Scrivimi o mandami un vocale: agenda, email, promemoria, documenti, musica e casa.")
        return
    if text.strip().lower() in ("/voce", "/voice"):
        on = not voice_reply_enabled()
        db.set_setting("telegram_voice_reply", on)
        await send("Risposte vocali " + ("attive: ai vocali rispondo anche a voce." if on else "disattivate."))
        return

    agent = _agent()
    conv = "telegram"
    history = [{"role": m["role"], "content": m["content"]} for m in memory.recent(conv, 16)]
    while history and history[0]["role"] != "user":  # l'API vuole iniziare con l'utente
        history.pop(0)
    if attachments:
        from . import documents

        history.append({"role": "user", "content": documents.build_content(text, attachments)})
    else:
        history.append({"role": "user", "content": text})
    await call("sendChatAction", chat_id=chat, action="typing")
    ctx = tools.Ctx(agent_id=agent.id, channel="telegram")
    reply, confirms = await agent_reply(agent, history, ctx)
    memory.log_message("telegram", conv, "user", text, "Telegram")
    memory.log_message("telegram", conv, "assistant", reply, "Telegram")
    await send(reply or "…")
    for out in ctx.outputs:  # grafici o file creati dall'analisi
        await send_file(out["path"], out["name"], out["mime"])
    if voice and reply and voice_reply_enabled():
        await call("sendChatAction", chat_id=chat, action="record_voice")
        await send_voice(reply)
    for a in confirms:
        await send(f"Confermi?\n\n{a['summary']}",
                   buttons=[[{"text": "✅ Conferma", "callback_data": f"ok:{a['id']}"},
                             {"text": "✖ Annulla", "callback_data": f"no:{a['id']}"}]])


async def agent_reply(agent, history, ctx):
    from .agent import run_once

    try:
        return await run_once(agent, history, ctx)
    except Exception as exc:  # noqa: BLE001
        log.exception("errore agente")
        return f"Errore: {exc}", []


async def _handle_update(u: dict) -> None:
    linked = chat_id()
    if "callback_query" in u:
        cq = u["callback_query"]
        if cq["message"]["chat"]["id"] != linked:
            return
        kind, aid = cq.get("data", ":").split(":", 1)
        res = await asyncio.to_thread(actions.approve if kind == "ok" else actions.reject, aid)
        await call("answerCallbackQuery", callback_query_id=cq["id"])
        await call("editMessageText", chat_id=linked, message_id=cq["message"]["message_id"],
                   text=("✅ " if res["ok"] and kind == "ok" else "✖ ") + res["result"])
        memory.log_message("telegram", "telegram", "assistant", f"(azione {aid}: {res['result']})", "Telegram")
        return

    msg = u.get("message") or {}
    chat = msg.get("chat", {}).get("id")
    text = (msg.get("text") or "").strip()
    if not chat:
        return
    if linked is None:
        # abbinamento: "/start CODICE" oppure solo "CODICE"
        code = text.replace("/start", "").strip().upper()
        if code and code == pair_code():
            db.set_setting("telegram_chat_id", chat)
            db.del_setting("telegram_pair_code")
            await send("Collegamento riuscito. Sono AXEL: da qui riceverai promemoria e briefing, e puoi scrivermi quando vuoi.", to=chat)
        else:
            await send("Per collegarmi inviami il codice di abbinamento che trovi in AXEL → Integrazioni.", to=chat)
        return
    if chat != linked:
        return  # ignora sconosciuti
    voice = msg.get("voice") or msg.get("audio") or msg.get("video_note")
    if voice:
        await _handle_voice(chat, voice)
        return
    doc = msg.get("document") or (msg.get("photo") or [None])[-1]
    if doc:
        await _handle_document(chat, msg, doc)
        return
    if not text:
        await send("Mandami un messaggio, un vocale, un documento o una foto.")
        return
    await _handle_text(chat, text)


async def _handle_document(chat: int, msg: dict, doc: dict) -> None:
    """PDF, Excel, CSV, immagini inviati in chat: li analizza (vedi documents.py)."""
    from . import documents

    await call("sendChatAction", chat_id=chat, action="typing")
    name = doc.get("file_name") or ("foto.jpg" if "width" in doc else "documento")
    try:
        data = await download(doc["file_id"])
        att = await asyncio.to_thread(documents.save_upload, name, data)
    except Exception as exc:  # noqa: BLE001
        await send(f"Non riesco ad aprire il file: {exc}")
        return
    request = (msg.get("caption") or "").strip() or "Analizza questo file e dimmi le cose importanti."
    await _handle_text(chat, request, attachments=[att["id"]])


async def poll_forever() -> None:
    if not token():
        log.info("Telegram non configurato (TELEGRAM_BOT_TOKEN mancante)")
        return
    me = await call("getMe")
    if me.get("ok"):
        db.set_setting("telegram_bot_username", me["result"]["username"])
    else:
        log.error("Token Telegram non valido: %s", me)
        return
    offset = None
    while True:
        try:
            res = await call("getUpdates", timeout=30, offset=offset, allowed_updates=["message", "callback_query"])
            for u in res.get("result", []):
                offset = u["update_id"] + 1
                asyncio.create_task(_safe(u))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001  rete assente, Mac in stop…
            log.warning("polling Telegram: %s", exc)
            await asyncio.sleep(5)


async def _safe(u: dict) -> None:
    try:
        await _handle_update(u)
    except Exception:  # noqa: BLE001
        log.exception("errore gestendo update Telegram")
