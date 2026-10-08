"""Strumenti dell'agente. Ogni gruppo si attiva/disattiva dal builder.

Per aggiungerne uno: scrivi la funzione (riceve ctx + argomenti) e registrala in REGISTRY.
Le azioni "pericolose" (inviare, creare, eliminare) passano da actions.create → conferma.
"""
from __future__ import annotations

import ast
import math
import operator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo

from . import actions, google_api, hue, mac, memory, reminders, shipments, spotify, tasks, weather


@dataclass
class Ctx:
    agent_id: str
    channel: str = "ui"  # ui | telegram | briefing
    events: list[dict] = field(default_factory=list)  # eventi extra (es. richieste di conferma)
    outputs: list[dict] = field(default_factory=list)  # file prodotti dalla code execution (grafici…)


# ---------- base ----------

def get_time(ctx: Ctx, timezone: str = "Europe/Rome") -> str:
    try:
        return datetime.now(ZoneInfo(timezone)).strftime("%A %d %B %Y, %H:%M:%S %Z")
    except Exception:
        return f"Fuso orario sconosciuto: {timezone}"


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod, ast.USub: operator.neg, ast.UAdd: operator.pos,
        ast.FloorDiv: operator.floordiv}
_FUNCS = {k: getattr(math, k) for k in ("sqrt", "sin", "cos", "tan", "log", "log10", "exp", "floor", "ceil")}
_FUNCS |= {"abs": abs, "round": round, "pi": math.pi, "e": math.e}


def _eval(node: ast.AST):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Name) and node.id in _FUNCS:
        return _FUNCS[node.id]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
        return _FUNCS[node.func.id](*[_eval(a) for a in node.args])
    raise ValueError("espressione non consentita")


def calculator(ctx: Ctx, expression: str) -> str:
    try:
        return str(_eval(ast.parse(expression, mode="eval").body))
    except Exception as exc:  # noqa: BLE001
        return f"Errore: {exc}"


# ---------- memoria ----------

def memory_save(ctx: Ctx, content: str, category: str = "generale") -> str:
    mid = memory.save(ctx.agent_id, content, category)
    return f"Memorizzato (#{mid}, {category})."


def memory_search(ctx: Ctx, query: str) -> str:
    rows = memory.search(ctx.agent_id, query, 10)
    return "\n".join(f"#{r['id']} [{r['category']}] {r['content']}" for r in rows) or "Nessun ricordo pertinente."


def memory_list(ctx: Ctx, category: str = "") -> str:
    rows = memory.list_all(ctx.agent_id, category or None, 60)
    return "\n".join(f"#{r['id']} [{r['category']}] {r['content']}" for r in rows) or "Memoria vuota."


def memory_delete(ctx: Ctx, memory_id: int) -> str:
    return "Ricordo eliminato." if memory.delete(ctx.agent_id, int(memory_id)) else "Ricordo non trovato."


# ---------- storico (conversazioni AXEL + chat importate da claude.ai) ----------

def history_search(ctx: Ctx, query: str, source: str = "all") -> str:
    rows = memory.search_history(query, source, 12)
    if not rows:
        return "Nessun risultato nello storico."
    return "\n".join(
        f"- [{r['source']}] {r['created_at'][:10]} «{r['conversation_title'] or ''}» {r['role']}: {r['snippet']}"
        for r in rows
    )


def claude_recent(ctx: Ctx) -> str:
    rows = memory.recent_claude_conversations(20)
    return "\n".join(f"- {r['last_at'][:10]} «{r['conversation_title']}» ({r['n']} msg)" for r in rows) \
        or "Nessuna chat di Claude importata. Importa l'export dal pannello Integrazioni."


def claude_read(ctx: Ctx, title: str) -> str:
    return memory.claude_conversation(title)


# ---------- meteo ----------

def get_weather(ctx: Ctx, city: str = "", days: int = 2) -> str:
    from . import db

    city = city or db.get_setting("briefing", {}).get("city") or "Roma"
    try:
        w = weather.data(city, max(days, 4))
    except weather.WeatherError as e:
        return str(e)
    if ctx.channel == "ui":  # mostra il widget olografico nell'app
        ctx.events.append({"type": "widget", "widget": "weather", "data": w})
    return weather.as_text(w, days) + "\n(Il widget meteo è già visibile all'utente: non elencare tutti i numeri, riassumi.)"


# ---------- calendario ----------

def calendar_list(ctx: Ctx, start: str = "", end: str = "", query: str = "") -> str:
    return google_api.calendar_list(start or None, end or None, query or None)


def _confirm(ctx: Ctx, name: str, args: dict) -> str:
    a = actions.create(ctx.agent_id, name, args)
    ctx.events.append({"type": "confirm", "action": {"id": a["id"], "name": name, "summary": a["summary"]}})
    return (f"Azione preparata (id {a['id']}) e IN ATTESA DI CONFERMA dell'utente: {a['summary']}\n"
            "Non è ancora stata eseguita. Riassumila in una frase e chiedi all'utente di confermare col pulsante.")


def calendar_create_event(ctx: Ctx, title: str, start: str, end: str = "", description: str = "",
                          location: str = "", attendees: list | None = None) -> str:
    args = {"title": title, "start": start, "end": end or None, "description": description, "location": location}
    if attendees:
        args["attendees"] = attendees
    return _confirm(ctx, "calendar_create_event", args)


def calendar_delete_event(ctx: Ctx, event_id: str) -> str:
    return _confirm(ctx, "calendar_delete_event", {"event_id": event_id})


# ---------- gmail ----------

def gmail_search(ctx: Ctx, query: str = "is:unread newer_than:2d", max_results: int = 10) -> str:
    return google_api.gmail_search(query, min(int(max_results), 25))


def gmail_read(ctx: Ctx, message_id: str) -> str:
    return google_api.gmail_read(message_id)


def gmail_draft(ctx: Ctx, to: str, subject: str, body: str, thread_id: str = "") -> str:
    return google_api.gmail_draft(to, subject, body, thread_id or None)


def gmail_send(ctx: Ctx, to: str, subject: str, body: str, thread_id: str = "") -> str:
    args = {"to": to, "subject": subject, "body": body}
    if thread_id:
        args["thread_id"] = thread_id
    return _confirm(ctx, "gmail_send", args)


# ---------- promemoria ----------

def reminder_create(ctx: Ctx, text: str, due_at: str, recurrence: str = "none") -> str:
    r = reminders.create(ctx.agent_id, text, due_at, recurrence)
    return "Promemoria impostato: " + reminders.describe({**r, "id": r["id"]})


def reminder_list(ctx: Ctx) -> str:
    rows = reminders.list_active(ctx.agent_id)
    return "\n".join(reminders.describe(r) for r in rows) or "Nessun promemoria attivo."


def reminder_delete(ctx: Ctx, reminder_id: int) -> str:
    return "Promemoria eliminato." if reminders.delete(int(reminder_id)) else "Promemoria non trovato."


# ---------- notizie, spedizioni ----------

def news_digest(ctx: Ctx, topic: str = "", count: int = 5) -> str:
    import asyncio as _a

    from . import news

    return _a.run(news.digest(topic, count))


def shipments_list(ctx: Ctx) -> str:
    return shipments.as_text()


# ---------- compiti in background ----------

def background_start(ctx: Ctx, title: str, instructions: str) -> str:
    from . import background

    tid = background.start(ctx.agent_id, title, instructions)
    if tid.startswith("errore"):
        return tid
    return (f"Compito «{title}» avviato in background (id {tid}). Dillo all'utente in una frase: quando ho finito arriva "
            "una notifica con il risultato; nel frattempo può continuare a parlarmi.")


def background_status(ctx: Ctx, task_id: str = "") -> str:
    from . import background

    if task_id:
        t = background.get(task_id)
        if not t:
            return "Compito non trovato."
        return f"{t['title']} — {t['status']} ({t['steps']} passi)\n\n{(t['result'] or 'in corso…')[:6000]}"
    rows = background.list_recent(8)
    return "\n".join(f"- [{r['id']}] {r['title']}: {r['status']}, {r['steps']} passi" for r in rows) or "Nessun compito."


# ---------- mappe ----------

def travel_time(ctx: Ctx, destination: str, origin: str = "", mode: str = "", arrive_by: str = "", depart_at: str = "") -> str:
    from . import maps

    return maps.travel_text(destination, origin, mode, arrive_by, depart_at)


# ---------- spotify ----------

def _spotify_widget(ctx: Ctx, wait: float = 0.0, need_target: bool = False) -> bool:
    """Mostra la scheda olografica di Spotify nell'app (solo canale ui), appena Spotify ha aggiornato lo stato."""
    if ctx.channel != "ui":
        return False
    try:
        st = spotify.wait_state(timeout=5.0, need_target=need_target) if wait else spotify.state()
    except Exception:  # noqa: BLE001
        return False
    if st:
        ctx.events.append({"type": "widget", "widget": "spotify", "data": st})
    return bool(st)


_SPOTIFY_NOTE = "\n(La scheda Spotify è già visibile all'utente: rispondi brevissimo, senza ripetere tempi e volume.)"


def spotify_now(ctx: Ctx) -> str:
    text = spotify.now_playing()
    return text + (_SPOTIFY_NOTE if _spotify_widget(ctx) else "")


def spotify_control(ctx: Ctx, action: str, value: int | None = None) -> str:
    text = spotify.control(action, value)
    ok = not spotify.is_error(text)
    return text + (_SPOTIFY_NOTE if ok and _spotify_widget(ctx, 0.7) else "")


def spotify_play(ctx: Ctx, query: str, kind: str = "track", artist: str = "") -> str:
    text = spotify.play(query, kind, artist)
    ok = text.startswith("Metto")
    return text + (_SPOTIFY_NOTE if ok and _spotify_widget(ctx, 1.0, need_target=True) else "")


def spotify_queue(ctx: Ctx, query: str) -> str:
    return spotify.queue(query)


def spotify_devices(ctx: Ctx, transfer_to: str = "") -> str:
    return spotify.transfer(transfer_to) if transfer_to else spotify.devices()


def spotify_playlists(ctx: Ctx) -> str:
    return spotify.my_playlists()


# ---------- Mac ----------

def _mac(fn, *a, **k):
    try:
        return fn(*a, **k)
    except mac.MacError as e:
        return str(e)


def mac_open_app(ctx: Ctx, app: str, path: str = "") -> str:
    return _mac(mac.open_app, app, path)


def mac_open(ctx: Ctx, target: str) -> str:
    return _mac(mac.open_target, target)


def photos_show(ctx: Ctx, folder: str = "", query: str = "", limit: int = 120) -> str:
    from . import photos

    try:
        g = photos.open_gallery(folder, query, limit)
    except mac.MacError as e:
        return str(e)
    if not g["items"]:
        return f"Nessuna immagine trovata in {g['path']}" + (f" per «{query}»" if query else "") + "."
    if ctx.channel == "ui":
        ctx.events.append({"type": "widget", "widget": "gallery", "data": g})
        return (f"Galleria aperta: {len(g['items'])} immagini da {g['path']}. L'utente le sta già vedendo a schermo "
                "(si scorrono con le frecce o dicendo 'avanti', 'indietro', 'chiudi'): rispondi con una frase breve.")
    return f"Trovate {len(g['items'])} immagini in {g['path']} (la galleria si vede solo nell'app)."


def youtube(ctx: Ctx, query: str = "", play: bool = False) -> str:
    return _mac(mac.youtube, query, play)


def mac_find_files(ctx: Ctx, query: str, kind: str = "", folder: str = "") -> str:
    return _mac(mac.find_files, query, kind, folder)


def mac_read_file(ctx: Ctx, path: str) -> str:
    return _mac(mac.read_file, path)


def mac_list_folder(ctx: Ctx, path: str = "~/Desktop") -> str:
    return _mac(mac.list_folder, path)


def mac_notes_add(ctx: Ctx, title: str, body: str) -> str:
    return _mac(mac.notes_add, title, body)


def mac_notes_search(ctx: Ctx, query: str) -> str:
    return _mac(mac.notes_search, query)


def mac_volume(ctx: Ctx, level: int | None = None, mute: bool | None = None) -> str:
    return _mac(mac.volume, level, mute)


def mac_brightness(ctx: Ctx, level: int) -> str:
    return _mac(mac.brightness, level)


def mac_status(ctx: Ctx) -> str:
    return _mac(mac.battery)


def mac_clipboard(ctx: Ctx, text: str = "") -> str:
    return _mac(mac.clipboard_set, text) if text else _mac(mac.clipboard_get)


def mac_shortcuts(ctx: Ctx, run: str = "", input: str = "") -> str:
    return _mac(mac.shortcut_run, run, input) if run else _mac(mac.shortcuts_list)


def mac_screenshot(ctx: Ctx):
    try:
        return mac.screenshot()
    except mac.MacError as e:
        return str(e)


def mac_trash(ctx: Ctx, path: str) -> str:
    try:
        p = mac.safe_path(path)
    except mac.MacError as e:
        return str(e)
    return _confirm(ctx, "mac_trash", {"path": str(p)})


def mac_move(ctx: Ctx, source: str, destination: str) -> str:
    try:
        s, d = mac.safe_path(source), mac.safe_path(destination)
    except mac.MacError as e:
        return str(e)
    return _confirm(ctx, "mac_move", {"src": str(s), "dst": str(d)})


def mac_run_command(ctx: Ctx, command: str, cwd: str = "~") -> str:
    return _confirm(ctx, "mac_run_command", {"command": command, "cwd": cwd})


# ---------- luci Philips Hue ----------

def _hue(fn, *a, **k):
    try:
        return fn(*a, **k)
    except hue.HueError as e:
        return str(e)
    except Exception as e:  # noqa: BLE001  bridge irraggiungibile
        return f"Non riesco a raggiungere il Bridge Hue: {e}"


def hue_status(ctx: Ctx) -> str:
    return _hue(hue.overview)


def hue_set(ctx: Ctx, target: str = "tutte", on: bool | None = None, brightness: int | None = None, color: str = "") -> str:
    return _hue(hue.set_lights, target, on, brightness, color)


def hue_scene(ctx: Ctx, name: str = "", room: str = "") -> str:
    return _hue(hue.activate_scene, name, room) if name else _hue(hue.scenes, room)


# ---------- compiti ricorrenti ----------

def task_create(ctx: Ctx, title: str, prompt: str, first_run: str, recurrence: str = "weekly") -> str:
    t = tasks.create(ctx.agent_id, title, prompt, first_run, recurrence)
    return "Compito programmato: " + tasks.describe(t)


def task_list(ctx: Ctx) -> str:
    return "\n".join(tasks.describe(t) for t in tasks.list_active(ctx.agent_id)) or "Nessun compito ricorrente."


def task_delete(ctx: Ctx, task_id: int) -> str:
    return "Compito eliminato." if tasks.delete(int(task_id)) else "Compito non trovato."


# ---------- registro ----------

def _schema(name: str, description: str, props: dict | None = None, required: list[str] | None = None) -> dict:
    return {"name": name, "description": description,
            "input_schema": {"type": "object", "properties": props or {}, "required": required or []}}


S = {"type": "string"}
CAT = {"type": "string", "enum": memory.CATEGORIES}
ISO = {"type": "string", "description": "Data/ora locale ISO 8601, es. 2026-10-06T18:00"}

REGISTRY: dict[str, list[tuple[dict, Callable[..., str]]]] = {
    "get_time": [(_schema("get_time", "Data e ora correnti in un fuso orario IANA.", {"timezone": S}), get_time)],
    "calculator": [(_schema("calculator", "Valuta un'espressione matematica.", {"expression": S}, ["expression"]), calculator)],
    "memory": [
        (_schema("memory_save", "Salva un fatto duraturo sull'utente (preferenze, persone, progetti, abitudini). "
                 "Usa 'profilo' per dati anagrafici e identità.", {"content": S, "category": CAT}, ["content"]), memory_save),
        (_schema("memory_search", "Cerca nei ricordi salvati.", {"query": S}, ["query"]), memory_search),
        (_schema("memory_list", "Elenca i ricordi, opzionalmente per categoria.", {"category": S}), memory_list),
        (_schema("memory_delete", "Elimina un ricordo per id.", {"memory_id": {"type": "integer"}}, ["memory_id"]), memory_delete),
    ],
    "history": [
        (_schema("history_search", "Cerca nelle conversazioni passate: con AXEL, via Telegram e nelle chat importate da claude.ai.",
                 {"query": S, "source": {"type": "string", "enum": ["all", "axel", "telegram", "claude"]}}, ["query"]), history_search),
        (_schema("claude_recent_chats", "Elenca le chat di claude.ai importate più recenti.", {}), claude_recent),
        (_schema("claude_read_chat", "Legge il contenuto di una chat di claude.ai importata, cercandola per titolo.",
                 {"title": S}, ["title"]), claude_read),
    ],
    "weather": [(_schema("get_weather", "Meteo attuale e previsioni per una città.", {"city": S, "days": {"type": "integer"}}), get_weather)],
    "calendar": [
        (_schema("calendar_list_events", "Elenca gli eventi del Google Calendar in un intervallo (default: oggi).",
                 {"start": ISO, "end": ISO, "query": S}), calendar_list),
        (_schema("calendar_create_event", "Prepara un nuovo evento nel calendario (richiede conferma dell'utente).",
                 {"title": S, "start": ISO, "end": ISO, "description": S, "location": S,
                  "attendees": {"type": "array", "items": S}}, ["title", "start"]), calendar_create_event),
        (_schema("calendar_delete_event", "Prepara l'eliminazione di un evento (richiede conferma).", {"event_id": S}, ["event_id"]),
         calendar_delete_event),
    ],
    "gmail": [
        (_schema("gmail_search", "Cerca email con la sintassi di ricerca Gmail (es. 'is:unread newer_than:1d', 'from:mario').",
                 {"query": S, "max_results": {"type": "integer"}}), gmail_search),
        (_schema("gmail_read", "Legge il contenuto completo di un'email per id.", {"message_id": S}, ["message_id"]), gmail_read),
        (_schema("gmail_create_draft", "Salva una bozza in Gmail (non la invia).", {"to": S, "subject": S, "body": S, "thread_id": S},
                 ["to", "subject", "body"]), gmail_draft),
        (_schema("gmail_send", "Prepara l'invio di un'email (richiede conferma dell'utente prima di partire).",
                 {"to": S, "subject": S, "body": S, "thread_id": S}, ["to", "subject", "body"]), gmail_send),
    ],
    "spotify": [
        (_schema("spotify_now_playing", "Cosa sta suonando ora su Spotify.", {}), spotify_now),
        (_schema("spotify_control", "Controlla la riproduzione Spotify.",
                 {"action": {"type": "string", "enum": ["play", "pause", "next", "previous", "volume", "shuffle_on", "shuffle_off"]},
                  "value": {"type": "integer", "description": "volume 0-100 per action=volume"}}, ["action"]), spotify_control),
        (_schema("spotify_play", "Cerca e fa partire musica su Spotify. Per un artista ('metti gli Iron Maiden') usa "
                 "kind=artist e query=nome dell'artista. Per un brano usa kind=track, query=titolo e artist=artista se noto "
                 "(es. query='The Trooper', artist='Iron Maiden'). Per un album kind=album. Per le playlist kind=playlist "
                 "(prima cerca tra quelle dell'utente).",
                 {"query": S, "artist": S, "kind": {"type": "string", "enum": ["track", "album", "artist", "playlist"]}},
                 ["query"]), spotify_play),
        (_schema("spotify_queue", "Aggiunge un brano alla coda.", {"query": S}, ["query"]), spotify_queue),
        (_schema("spotify_devices", "Elenca i dispositivi Spotify o sposta la riproduzione su uno (transfer_to = nome).",
                 {"transfer_to": S}), spotify_devices),
        (_schema("spotify_playlists", "Elenca le playlist dell'utente.", {}), spotify_playlists),
    ],
    "mac": [
        (_schema("mac_open_app", "Apre un'app sul Mac, opzionalmente su un file o una cartella (es. VS Code su un progetto).",
                 {"app": S, "path": {"type": "string", "description": "percorso, es. ~/React/axel-agent"}}, ["app"]), mac_open_app),
        (_schema("mac_open", "Apre un file, una cartella o un URL con l'app predefinita.", {"target": S}, ["target"]), mac_open),
        (_schema("photos_show", "Mostra le foto/immagini di una cartella del Mac in una galleria a schermo (carosello). "
                 "folder: percorso nella Home (vuoto = cartella Immagini); query: parole da cercare nei nomi di file e "
                 "sottocartelle (es. 'lisbona 2024'). Per trovare prima la cartella giusta puoi usare mac_find_files.",
                 {"folder": S, "query": S, "limit": {"type": "integer"}}), photos_show),
        (_schema("youtube", "Apre YouTube nel browser del Mac: senza query la home, con 'query' la ricerca. "
                 "play=true fa partire direttamente il primo video trovato (usalo per 'metti/fammi vedere/fai partire').",
                 {"query": S, "play": {"type": "boolean"}}), youtube),
        (_schema("mac_find_files", "Cerca file e cartelle sul Mac con Spotlight (per nome, poi contenuto). I risultati più recenti prima.",
                 {"query": S, "kind": {"type": "string", "enum": ["", "pdf", "cartella", "immagine", "word", "excel", "testo"]},
                  "folder": S}, ["query"]), mac_find_files),
        (_schema("mac_read_file", "Legge il testo di un file (PDF, Word, testo, codice) per riassumerlo o rispondere.", {"path": S}, ["path"]),
         mac_read_file),
        (_schema("mac_list_folder", "Elenca il contenuto di una cartella (default Scrivania).", {"path": S}), mac_list_folder),
        (_schema("mac_notes_add", "Crea una nota nell'app Note.", {"title": S, "body": S}, ["title", "body"]), mac_notes_add),
        (_schema("mac_notes_search", "Cerca nelle Note dell'utente.", {"query": S}, ["query"]), mac_notes_search),
        (_schema("mac_volume", "Legge o imposta il volume del Mac, o lo silenzia.",
                 {"level": {"type": "integer"}, "mute": {"type": "boolean"}}), mac_volume),
        (_schema("mac_brightness", "Imposta la luminosità dello schermo (0-100).", {"level": {"type": "integer"}}, ["level"]), mac_brightness),
        (_schema("mac_status", "Stato batteria/alimentazione del Mac.", {}), mac_status),
        (_schema("mac_clipboard", "Legge gli appunti, oppure copia un testo negli appunti se 'text' è indicato.", {"text": S}), mac_clipboard),
        (_schema("mac_shortcuts", "Elenca i Comandi rapidi dell'utente, oppure ne esegue uno ('run' = nome). Utile per "
                 "Non disturbare, luci e scene di Casa (HomeKit), termostato, lettura sensori: il risultato del comando viene restituito.", {"run": S, "input": S}), mac_shortcuts),
        (_schema("mac_screenshot", "Cattura lo schermo e lo guarda: usalo quando l'utente chiede di vedere/guardare il suo schermo.", {}),
         mac_screenshot),
        (_schema("mac_trash", "Prepara lo spostamento di un file nel Cestino (richiede conferma).", {"path": S}, ["path"]), mac_trash),
        (_schema("mac_move", "Prepara lo spostamento/rinomina di un file (richiede conferma).", {"source": S, "destination": S},
                 ["source", "destination"]), mac_move),
        (_schema("mac_run_command", "Prepara un comando da terminale zsh (richiede conferma). Usalo solo se nessun altro strumento basta.",
                 {"command": S, "cwd": S}, ["command"]), mac_run_command),
    ],
    "hue": [
        (_schema("hue_status", "Stato delle luci Philips Hue: stanze, zone e luci accese.", {}), hue_status),
        (_schema("hue_set", "Accende/spegne le luci Hue, regola luminosità (0-100) e colore. 'target' = nome di stanza, "
                 "zona o luce, oppure 'tutte'. Colori: rosso, blu, verde, viola, rosa, arancione, giallo, azzurro, bianco, "
                 "caldo, freddo, naturale o esadecimale.",
                 {"target": S, "on": {"type": "boolean"}, "brightness": {"type": "integer"}, "color": S}), hue_set),
        (_schema("hue_scene", "Attiva una scena Hue per nome (opzionalmente in una stanza); senza nome elenca le scene.",
                 {"name": S, "room": S}), hue_scene),
    ],
    "news": [
        (_schema("news_digest", "Notizie recenti dalle fonti RSS scelte dall'utente, filtrate sui suoi interessi e riassunte. "
                 "'topic' facoltativo per un argomento (es. 'intelligenza artificiale'). Includi le fonti nella risposta.",
                 {"topic": S, "count": {"type": "integer"}}), news_digest),
    ],
    "background": [
        (_schema("background_start", "Avvia un compito LUNGO in background con un sotto-agente (ricerche approfondite, "
                 "confronti di prezzi/voli/preventivi, analisi di molti documenti). Usalo quando il lavoro richiede molti "
                 "passaggi o più di un minuto, o quando l'utente dice 'fallo con calma', 'avvisami quando hai fatto'. "
                 "'instructions' deve essere completo e autosufficiente (il sotto-agente non vede questa conversazione).",
                 {"title": S, "instructions": S}, ["title", "instructions"]), background_start),
        (_schema("background_status", "Stato e risultato dei compiti in background (senza id: elenco recente).",
                 {"task_id": S}), background_status),
    ],
    "maps": [
        (_schema("travel_time", "Tempo di viaggio (con il traffico se disponibile), distanza e link al percorso. "
                 "origin vuoto = casa; 'casa' e 'ufficio' sono scorciatoie. mode: drive, walk, bike, transit, moto. "
                 "arrive_by (HH:MM o ISO) calcola anche l'ora di partenza.",
                 {"destination": S, "origin": S, "mode": {"type": "string", "enum": ["drive", "walk", "bike", "transit", "moto"]},
                  "arrive_by": S, "depart_at": S}, ["destination"]), travel_time),
    ],
    "shipments": [
        (_schema("shipments_list", "Pacchi e ordini in arrivo (rilevati dalle email di negozi e corrieri): stato, corriere, "
                 "tracking, data prevista.", {}), shipments_list),
    ],
    "tasks": [
        (_schema("task_create", "Programma un compito ricorrente che AXEL eseguirà da solo inviando il risultato su Telegram "
                 "(es. riepilogo settimanale). 'prompt' è l'istruzione completa da eseguire.",
                 {"title": S, "prompt": S, "first_run": ISO, "recurrence": {"type": "string", "enum": reminders.RECURRENCES}},
                 ["title", "prompt", "first_run"]), task_create),
        (_schema("task_list", "Elenca i compiti ricorrenti.", {}), task_list),
        (_schema("task_delete", "Elimina un compito ricorrente per id.", {"task_id": {"type": "integer"}}, ["task_id"]), task_delete),
    ],
    "reminders": [
        (_schema("reminder_create", "Crea un promemoria che verrà notificato su Telegram all'ora indicata.",
                 {"text": S, "due_at": ISO, "recurrence": {"type": "string", "enum": reminders.RECURRENCES}},
                 ["text", "due_at"]), reminder_create),
        (_schema("reminder_list", "Elenca i promemoria attivi.", {}), reminder_list),
        (_schema("reminder_delete", "Elimina un promemoria per id.", {"reminder_id": {"type": "integer"}}, ["reminder_id"]), reminder_delete),
    ],
}

# Strumenti di sola lettura che Claude può chiamare anche da un programma (programmatic tool calling):
# restituiscono testo, non chiedono conferme e non hanno effetti collaterali.
PTC_SAFE = {
    "get_time", "calculator", "get_weather", "memory_search", "history_search", "calendar_list_events",
    "gmail_search", "gmail_read", "spotify_now_playing", "spotify_playlists", "hue_status", "reminder_list",
    "mac_find_files", "mac_read_file", "mac_list_folder", "mac_status", "travel_time", "news_digest",
    "shipments_list", "task_list", "background_status",
}

SERVER_TOOLS: dict[str, dict] = {
    "web_search": {"type": "web_search_20250305", "name": "web_search", "max_uses": 4},
}

AVAILABLE = [
    {"id": "memory", "label": "Memoria", "description": "Ricorda fatti, preferenze, persone"},
    {"id": "history", "label": "Storico chat", "description": "Conversazioni passate e chat di Claude"},
    {"id": "reminders", "label": "Promemoria", "description": "Notifiche su Telegram"},
    {"id": "calendar", "label": "Calendario", "description": "Google Calendar"},
    {"id": "gmail", "label": "Gmail", "description": "Leggi, riassumi, invia con conferma"},
    {"id": "mac", "label": "Controllo Mac", "description": "App, file, Note, volume, schermo"},
    {"id": "hue", "label": "Luci Hue", "description": "Accendi, spegni, colori, scene"},
    {"id": "tasks", "label": "Compiti ricorrenti", "description": "Azioni programmate a voce"},
    {"id": "news", "label": "Notizie", "description": "Notizie su misura dalle tue fonti RSS"},
    {"id": "background", "label": "Compiti in background", "description": "Ricerche e confronti lunghi mentre fai altro"},
    {"id": "maps", "label": "Mappe e traffico", "description": "Tempi di viaggio e avviso parti ora"},
    {"id": "shipments", "label": "Spedizioni", "description": "Pacchi in arrivo letti dalle email"},
    {"id": "mcp", "label": "Collegamenti MCP", "description": "Strumenti dei server MCP configurati (Notion, GitHub…)"},
    {"id": "spotify", "label": "Spotify", "description": "Musica: cerca, play, pausa, volume"},
    {"id": "web_search", "label": "Ricerca web", "description": "Notizie e info aggiornate"},
    {"id": "weather", "label": "Meteo", "description": "Previsioni (Open-Meteo)"},
    {"id": "get_time", "label": "Orologio", "description": "Ora nei vari fusi"},
    {"id": "calculator", "label": "Calcolatrice", "description": "Calcoli precisi"},
]
ALL_TOOL_IDS = [t["id"] for t in AVAILABLE]


def schemas_for(enabled: list[str]) -> list[dict]:
    out: list[dict] = []
    for key in enabled:
        if key in SERVER_TOOLS:
            out.append(SERVER_TOOLS[key])
        for schema, _ in REGISTRY.get(key, []):
            out.append(schema)
    return out


def run_tool(ctx: Ctx, name: str, args: dict):  # -> str | list (blocchi immagine)
    for entries in REGISTRY.values():
        for schema, fn in entries:
            if schema["name"] == name:
                try:
                    return fn(ctx, **args)
                except TypeError as exc:
                    return f"Argomenti non validi: {exc}"
                except Exception as exc:  # noqa: BLE001
                    return f"Errore durante {name}: {exc}"
    return f"Strumento sconosciuto: {name}"
