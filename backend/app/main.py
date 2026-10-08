from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

mimetypes.add_type("text/javascript", ".mjs")  # file del rilevatore di voce (onnxruntime)
mimetypes.add_type("application/wasm", ".wasm")

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from . import actions, background, backup, db, documents, learning, maps, news, shipments, fastlane, google_api, hue, mcp_client, mac, memory, proactive, reminders, scheduler, spotify, store, stt, tasks, telegram, tools, tts  # noqa: E402
from . import agent as agent_loop  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")


def _migrate_legacy_memory() -> None:
    """Porta i ricordi del vecchio memory.json nel nuovo database."""
    f = db.DATA_DIR / "memory.json"
    if not f.exists():
        return
    try:
        for agent_id, facts in json.loads(f.read_text("utf-8")).items():
            for k, v in facts.items():
                memory.save(agent_id, f"{k}: {v}", "profilo")
        f.rename(f.with_suffix(".json.migrated"))
    except Exception:  # noqa: BLE001
        logging.exception("migrazione memoria")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.conn()
    _migrate_legacy_memory()
    tasks = [asyncio.create_task(scheduler.run_forever()), asyncio.create_task(telegram.poll_forever())]
    background.init(asyncio.get_running_loop())
    await mcp_client.manager.start()
    yield
    await mcp_client.manager.stop_all()
    for t in tasks:
        t.cancel()


app = FastAPI(title="AXEL Agent API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatMessage(BaseModel):
    role: str
    content: str
    attachments: list[str] = []


class ChatRequest(BaseModel):
    agent_id: str
    messages: list[ChatMessage]
    conversation_id: Optional[str] = None


class BriefingSettings(BaseModel):
    enabled: bool
    time: str
    city: str


# ---------- base ----------

@app.get("/api/health")
def health():
    return {"ok": True, "demo": not bool(os.getenv("ANTHROPIC_API_KEY"))}


@app.get("/api/tools")
def list_tools():
    return tools.AVAILABLE


@app.get("/api/agents")
def list_agents():
    return store.list_agents()


@app.put("/api/agents/{agent_id}")
def upsert_agent(agent_id: str, cfg: store.AgentConfig):
    cfg.id = agent_id
    return store.save_agent(cfg)


@app.post("/api/agents")
def create_agent(cfg: store.AgentConfig):
    return store.save_agent(cfg)


@app.delete("/api/agents/{agent_id}")
def remove_agent(agent_id: str):
    if not store.delete_agent(agent_id):
        raise HTTPException(404, "agente non trovato")
    return {"ok": True}


@app.post("/api/chat")
async def chat(req: ChatRequest):
    cfg = store.get_agent(req.agent_id)
    if not cfg:
        raise HTTPException(404, "agente non trovato")
    conv = req.conversation_id or "ui"
    if req.messages and req.messages[-1].role == "user":
        names = [(documents.get(a) or {}).get("name", "file") for a in req.messages[-1].attachments]
        memory.log_message("axel", conv, "user", req.messages[-1].content + (f" [allegati: {', '.join(names)}]" if names else ""), "AXEL")
    history = [
        {"role": m.role, "content": documents.build_content(m.content, m.attachments) if m.attachments else m.content}
        for m in req.messages
    ]

    history = await learning.compact(conv, history)  # conversazioni lunghe: la parte vecchia diventa un riassunto

    # corsia veloce: comandi semplici eseguiti subito, senza Claude
    last = history[-1]["content"] if history and history[-1]["role"] == "user" else ""
    hit = fastlane.match(last, cfg) if agent_loop.speed_settings()["fastlane"] else None
    if hit:
        m, fn = hit

        async def fast():
            t0 = time.perf_counter()
            yield f"data: {json.dumps({'type': 'meta', 'model': 'fastlane'})}\n\n"
            yield f"data: {json.dumps({'type': 'tool_use', 'name': 'corsia veloce'})}\n\n"
            res = await asyncio.to_thread(fn, m)
            if res.widget:
                yield f"data: {json.dumps(res.widget, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'text', 'delta': res.text}, ensure_ascii=False)}\n\n"
            agent_loop.log_usage("fastlane", "fastlane", {"input_tokens": 0}, int((time.perf_counter() - t0) * 1000))
            memory.log_message("axel", conv, "assistant", res.text, "AXEL")
            yield f"data: {json.dumps({'type': 'done', 'usage': None, 'fast': True})}\n\n"

        return StreamingResponse(fast(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    async def sse():
        reply = ""
        ctx = tools.Ctx(agent_id=cfg.id, channel="ui")
        try:
            async for ev in agent_loop.run(cfg, history, ctx):
                if ev["type"] == "text":
                    reply += ev["delta"]
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
        finally:
            memory.log_message("axel", conv, "assistant", reply, "AXEL")

    return StreamingResponse(sse(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------- integrazioni ----------

@app.get("/api/integrations")
def integrations(agent_id: str = "axel"):
    return {
        "google": google_api.status(),
        "telegram": {**telegram.status(), "voice_reply": telegram.voice_reply_enabled()},
        "spotify": spotify.status(),
        "proactive": proactive.settings(),
        "hue": hue.status(),
        "mac": mac.IS_MAC,
        "mcp": {"available": mcp_client.available(), "servers": len(mcp_client.manager.servers),
                "tools": mcp_client.manager.total()},
        "briefing": scheduler.briefing_settings(),
        "history": memory.stats(),
        "memories": len(memory.list_all(agent_id, None, 10000)),
    }


@app.get("/api/google/auth")
def google_auth():
    if not google_api.status()["configured"]:
        raise HTTPException(400, "Manca backend/data/google_client_secret.json (vedi README)")
    return RedirectResponse(google_api.auth_url())


@app.get("/api/google/callback")
def google_callback(request: Request, state: str = "", error: str = ""):
    if error:
        return RedirectResponse(f"{FRONTEND_URL}/?google=error&msg={error}")
    try:
        google_api.finish_auth(str(request.url), state)
    except Exception as exc:  # noqa: BLE001
        logging.exception("OAuth Google")
        return RedirectResponse(f"{FRONTEND_URL}/?google=error&msg={str(exc)[:120]}")
    return RedirectResponse(f"{FRONTEND_URL}/?google=ok")


@app.post("/api/google/disconnect")
def google_disconnect():
    google_api.disconnect()
    return {"ok": True}


@app.get("/api/spotify/auth")
def spotify_auth():
    if not spotify.status()["configured"]:
        raise HTTPException(400, "Mancano SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET nel .env (vedi README)")
    return RedirectResponse(spotify.auth_url())


@app.get("/api/spotify/callback")
def spotify_callback(code: str = "", state: str = "", error: str = ""):
    if error or not code:
        return RedirectResponse(f"{FRONTEND_URL}/?spotify=error&msg={error or 'annullato'}")
    try:
        spotify.finish_auth(code, state)
    except Exception as exc:  # noqa: BLE001
        logging.exception("OAuth Spotify")
        return RedirectResponse(f"{FRONTEND_URL}/?spotify=error&msg={str(exc)[:120]}")
    return RedirectResponse(f"{FRONTEND_URL}/?spotify=ok")


@app.post("/api/spotify/disconnect")
def spotify_disconnect():
    spotify.disconnect()
    return {"ok": True}


@app.get("/api/spotify/now")
def spotify_now():
    try:
        return {"text": spotify.now_playing()}
    except Exception as exc:  # noqa: BLE001
        return {"text": str(exc)}


@app.get("/api/spotify/diagnose")
async def spotify_diagnose():
    return await asyncio.to_thread(spotify.diagnose)


@app.get("/api/spotify/state")
async def spotify_state():
    try:
        return {"data": await asyncio.to_thread(spotify.state)}
    except Exception as exc:  # noqa: BLE001
        return {"data": None, "error": str(exc)}


class SpotifyAction(BaseModel):
    action: str
    value: Optional[int] = None


@app.post("/api/spotify/control")
async def spotify_control(a: SpotifyAction):
    if a.action not in ("play", "pause", "next", "previous", "volume", "shuffle_on", "shuffle_off"):
        raise HTTPException(400, "azione non valida")
    msg = await asyncio.to_thread(spotify.control, a.action, a.value)
    await asyncio.sleep(0.6)  # lo stato su Spotify si aggiorna con un attimo di ritardo
    try:
        data = await asyncio.to_thread(spotify.state)
    except Exception:  # noqa: BLE001
        data = None
    return {"message": msg, "data": data}


@app.post("/api/telegram/test")
async def telegram_test():
    ok = await telegram.send("👋 Test da AXEL: le notifiche funzionano.")
    return {"ok": ok}


@app.post("/api/telegram/unlink")
def telegram_unlink():
    telegram.unlink()
    return {"ok": True}


@app.put("/api/briefing")
def set_briefing(s: BriefingSettings):
    cur = scheduler.briefing_settings()
    cur.update(s.model_dump())
    db.set_setting("briefing", cur)
    return cur


@app.post("/api/briefing/run")
async def run_briefing():
    channel = await scheduler.send_briefing(force=True)
    return {"ok": True, "channel": channel}


@app.post("/api/hue/pair")
async def hue_pair():
    try:
        return await asyncio.to_thread(hue.pair)
    except hue.HueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Bridge non raggiungibile: {exc}") from exc


@app.post("/api/hue/unlink")
def hue_unlink():
    hue.unlink()
    return {"ok": True}


@app.get("/api/vocabulary")
def get_vocabulary():
    return db.get_setting("vocabulary") or []


@app.put("/api/vocabulary")
def set_vocabulary(words: list[str]):
    clean = list(dict.fromkeys(w.strip() for w in words if w.strip()))[:200]
    db.set_setting("vocabulary", clean)
    return clean


@app.put("/api/proactive")
def set_proactive(s: dict):
    return proactive.save(s)


@app.post("/api/mail/test")
def mail_test():
    """Bolla di prova per vedere l'animazione."""
    db.notify("mail", json.dumps({"id": "test", "from": "AXEL", "email": "axel@localhost",
                                  "subject": "Questa è una bolla di prova", "snippet": "Le nuove email arriveranno così.",
                                  "link": "https://mail.google.com"}, ensure_ascii=False))
    return {"ok": True}


# ---------- notizie, spedizioni, mappe, voce Telegram ----------

@app.get("/api/news")
def news_get():
    return {**news.settings(), "presets": news.PRESETS}


@app.put("/api/news")
def news_put(s: dict):
    return {**news.save(s), "presets": news.PRESETS}


@app.post("/api/news/feed")
async def news_add_feed(body: dict):
    """Aggiunge una fonte personalizzata: verifica il feed, ne ricava il nome e la attiva."""
    try:
        f = await news.inspect_feed(str(body.get("url", "")))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Feed non aggiunto: {exc}") from exc
    if body.get("name"):
        f["name"] = str(body["name"])[:40]
    cur = news.settings()
    known = {x["url"] for x in news.PRESETS}
    custom = [c for c in cur["custom"] if c["url"] != f["url"]]
    if f["url"] not in known:
        custom.append({"name": f["name"], "url": f["url"]})
    feeds = [x for x in cur["feeds"] if x["url"] != f["url"]] + [{"name": f["name"], "url": f["url"]}]
    return {**news.save({"custom": custom, "feeds": feeds}), "presets": news.PRESETS, "added": f}


@app.delete("/api/news/feed")
def news_delete_feed(url: str):
    cur = news.settings()
    return {**news.save({"custom": [c for c in cur["custom"] if c["url"] != url],
                         "feeds": [x for x in cur["feeds"] if x["url"] != url]}), "presets": news.PRESETS}


@app.post("/api/news/test")
async def news_test():
    return {"text": await news.digest()}


@app.get("/api/shipments")
def shipments_get():
    return [{**r, "label": shipments.LABEL.get(r["status"], r["status"])} for r in shipments.active()]


@app.delete("/api/shipments/{sid}")
def shipments_archive(sid: int):
    return {"ok": shipments.archive(sid)}


@app.post("/api/shipments/check")
async def shipments_check():
    from .scheduler import deliver

    await shipments.check(deliver)
    return shipments_get()


@app.get("/api/maps")
def maps_get():
    return {**maps.settings(), **maps.status()}


@app.put("/api/maps")
def maps_put(s: dict):
    maps.save(s)
    return maps_get()


@app.get("/api/maps/test")
async def maps_test(destination: str, origin: str = ""):
    return {"text": await asyncio.to_thread(maps.travel_text, destination, origin)}


@app.put("/api/telegram/voice")
def telegram_voice(body: dict):
    db.set_setting("telegram_voice_reply", bool(body.get("on")))
    return {"on": telegram.voice_reply_enabled()}


# ---------- copia di sicurezza ----------

@app.get("/api/backup")
def backup_get():
    return backup.status()


@app.put("/api/backup")
def backup_put(s: dict):
    backup.save(s)
    return backup.status()


@app.post("/api/backup/run")
async def backup_run():
    try:
        await asyncio.to_thread(backup.create, "manuale")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Copia non riuscita: {exc}") from exc
    db.del_setting("backup_error")
    return backup.status()


@app.post("/api/backup/restore")
async def backup_restore(body: dict):
    try:
        res = await asyncio.to_thread(backup.restore, str(body.get("name", "")))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await mcp_client.manager.reload()
    return {**res, **backup.status()}


# ---------- compiti in background ----------

@app.get("/api/background")
def bg_list():
    return background.list_recent()


@app.get("/api/background/{tid}")
def bg_get(tid: str):
    t = background.get(tid)
    if not t:
        raise HTTPException(404, "compito non trovato")
    return t


@app.delete("/api/background/{tid}")
def bg_cancel(tid: str):
    return {"ok": background.cancel(tid)}


# ---------- galleria foto ----------

@app.get("/api/photos/{gid}/{idx}")
def photo(gid: str, idx: int, size: int = 480):
    from . import photos

    res = photos.image(gid, idx, size)
    if not res:
        raise HTTPException(404, "immagine non disponibile")
    path, ctype = res
    return FileResponse(path, media_type=ctype, headers={"Cache-Control": "private, max-age=86400"})


@app.post("/api/photos/open")
async def photos_open(body: dict):
    """Apre una galleria direttamente dall'interfaccia (senza passare da Claude)."""
    from . import photos

    try:
        return await asyncio.to_thread(photos.open_gallery, str(body.get("folder", "")), str(body.get("query", "")), 200)
    except mac.MacError as exc:
        raise HTTPException(400, str(exc)) from exc


# ---------- documenti ----------

@app.post("/api/upload")
async def upload(request: Request, filename: str = "file"):
    data = await request.body()
    if not data:
        raise HTTPException(400, "file vuoto")
    try:
        return await asyncio.to_thread(documents.save_upload, filename, data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/outputs/{file_id}")
def output_file(file_id: str):
    p = documents.output_path(file_id)
    if not p:
        raise HTTPException(404, "file non trovato")
    return FileResponse(p, filename=p.name.split("_", 1)[-1])


# ---------- collegamenti MCP ----------

class McpServerConfig(BaseModel):
    command: Optional[str] = None
    args: list[str] = []
    env: dict[str, str] = {}
    cwd: Optional[str] = None
    url: Optional[str] = None
    headers: dict[str, str] = {}
    transport: Optional[str] = None
    approval: str = "auto-read"
    enabled: bool = True
    description: Optional[str] = None
    keep_secrets: bool = True  # se env/headers arrivano vuoti, conserva quelli già salvati


@app.get("/api/mcp")
def mcp_list():
    return {"available": mcp_client.available(), "servers": mcp_client.manager.status(),
            "config_path": str(mcp_client.CONFIG)}


@app.put("/api/mcp/servers/{name}")
async def mcp_save(name: str, cfg: McpServerConfig):
    import re as _re

    if not _re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name):
        raise HTTPException(400, "Nome non valido: usa lettere, numeri, - e _ (max 40)")
    if not cfg.command and not cfg.url:
        raise HTTPException(400, "Serve un comando (server locale) oppure un URL (server remoto)")
    if cfg.approval not in mcp_client.APPROVALS:
        raise HTTPException(400, "approval non valido")
    servers = mcp_client.load_config()
    old = servers.get(name, {})
    data = {k: v for k, v in cfg.model_dump().items() if k != "keep_secrets" and v not in (None, [], {}, "")}
    data["enabled"] = cfg.enabled
    if cfg.keep_secrets:
        if not cfg.env and old.get("env"):
            data["env"] = old["env"]
        if not cfg.headers and old.get("headers"):
            data["headers"] = old["headers"]
    servers[name] = data
    mcp_client.save_config(servers)
    await mcp_client.manager.reload()
    return mcp_list()


@app.delete("/api/mcp/servers/{name}")
async def mcp_delete(name: str):
    servers = mcp_client.load_config()
    servers.pop(name, None)
    mcp_client.save_config(servers)
    await mcp_client.manager.reload()
    return mcp_list()


@app.post("/api/mcp/reload")
async def mcp_reload():
    await mcp_client.manager.reload()
    await asyncio.sleep(1.5)
    return mcp_list()


# ---------- velocità e consumi ----------

@app.get("/api/speed")
def get_speed():
    return agent_loop.speed_settings()


@app.put("/api/speed")
def set_speed(s: dict):
    cur = agent_loop.speed_settings()
    cur.update({k: v for k, v in s.items() if k in agent_loop.SPEED_DEFAULTS})
    db.set_setting("speed", cur)
    return cur


@app.get("/api/usage")
def usage(days: int = 7):
    rows = db.query(
        "SELECT day, channel, model, COUNT(*) AS calls, SUM(input) AS input, SUM(output) AS output, "
        "SUM(cache_read) AS cache_read, SUM(cache_write) AS cache_write, CAST(AVG(NULLIF(ms,0)) AS INTEGER) AS avg_ms "
        "FROM usage WHERE day >= date('now', ?) GROUP BY day, channel, model ORDER BY day DESC",
        (f"-{max(1, days)} days",),
    )
    return rows


# ---------- voce di AXEL (sintesi dal backend) ----------

class TTSRequest(BaseModel):
    text: str
    voice: str
    rate: float = 1.0


@app.post("/api/tts")
async def tts_speak(req: TTSRequest):
    from fastapi.responses import Response

    try:
        audio, ctype = await asyncio.to_thread(tts.synth_for_app, req.voice, req.text, req.rate)
    except tts.TTSError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"sintesi non riuscita: {exc}") from exc
    return Response(audio, media_type=ctype, headers={"Cache-Control": "private, max-age=3600"})


@app.get("/api/tts/voices")
async def tts_voices():
    google, gerr = [], None
    if tts.google_key():
        try:
            google = await asyncio.to_thread(tts.google_voices)
        except Exception as exc:  # noqa: BLE001
            gerr = str(exc)
    mac_voices = await asyncio.to_thread(tts.italian_voices) if tts.available() else []
    return {"google": google, "google_key": bool(tts.google_key()), "google_error": gerr,
            "mac": mac_voices, "mac_available": tts.available()}


# ---------- voce locale (Whisper) ----------

@app.get("/api/stt/status")
def stt_status():
    return stt.status()


@app.put("/api/stt/quality")
def stt_quality(body: dict):
    try:
        return stt.set_quality(str(body.get("quality", "")))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/stt/warmup")
async def stt_warmup():
    try:
        await asyncio.to_thread(stt.load)
    except stt.STTUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    return stt.status()


@app.post("/api/stt")
async def stt_transcribe(request: Request):
    data = await request.body()
    if not data:
        raise HTTPException(400, "audio vuoto")
    try:
        return await asyncio.to_thread(stt.transcribe, data)
    except stt.STTUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/api/memory/learn")
async def memory_learn(agent_id: str = "axel"):
    """Fa subito l'apprendimento della giornata (di solito avviene la sera)."""
    res = await learning.learn_today(agent_id)
    db.set_setting("learning_last_result", {"date": "manuale", **res})
    return res


@app.get("/api/memory/learned")
def memory_learned():
    return db.get_setting("learning_last_result") or {}


@app.get("/api/tasks")
def list_tasks():
    return tasks.list_active()


@app.delete("/api/tasks/{tid}")
def delete_task(tid: int):
    return {"ok": tasks.delete(tid)}


@app.get("/api/reminders")
def list_reminders():
    return reminders.list_active()


@app.delete("/api/reminders/{rid}")
def delete_reminder(rid: int):
    return {"ok": reminders.delete(rid)}


@app.get("/api/memories")
def list_memories(agent_id: str = "axel"):
    return memory.list_all(agent_id, None, 500)


@app.delete("/api/memories/{mid}")
def delete_memory(mid: int, agent_id: str = "axel"):
    return {"ok": memory.delete(agent_id, mid)}


@app.post("/api/import/claude")
async def import_claude(request: Request, filename: str = "conversations.json"):
    data = await request.body()
    if not data:
        raise HTTPException(400, "file vuoto")
    try:
        return await asyncio.to_thread(memory.import_claude_export, data, filename)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Import non riuscito: {exc}") from exc


@app.get("/api/actions/pending")
def pending_actions():
    return actions.pending()


@app.post("/api/actions/{aid}/approve")
async def approve_action(aid: str):
    return await asyncio.to_thread(actions.approve, aid)


@app.post("/api/actions/{aid}/reject")
def reject_action(aid: str):
    return actions.reject(aid)


@app.get("/api/notifications")
def notifications(after: int = -1):
    if after < 0:  # primo caricamento: solo l'ultimo id, niente arretrati
        rows = db.query("SELECT COALESCE(MAX(id),0) AS id FROM notifications")
        return {"last": rows[0]["id"], "items": []}
    items = db.query("SELECT * FROM notifications WHERE id > ? ORDER BY id", (after,))
    return {"last": items[-1]["id"] if items else after, "items": items}


# In produzione serve anche il frontend compilato (npm run build -> frontend/dist)
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = DIST / path
        return FileResponse(f if f.is_file() else DIST / "index.html")
