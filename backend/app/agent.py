"""Loop agentico con streaming: testo → eventuali strumenti → testo, fino alla risposta finale."""
from __future__ import annotations

import asyncio
import copy
import os
import re
import time
from datetime import datetime
from typing import AsyncIterator

from anthropic import AsyncAnthropic

from . import db, documents, mcp_client, memory, store, tools
from .google_api import tz

MAX_STEPS = 10
GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]

CHANNEL_STYLE = {
    "ui": "Le tue risposte vengono lette ad alta voce: frasi brevi e naturali, niente markdown, niente elenchi lunghi.",
    "telegram": "Rispondi su Telegram: conciso, puoi usare elenchi brevi con trattini, niente tabelle.",
    "briefing": "Stai scrivendo il briefing mattutino da inviare su Telegram: chiaro, ordinato, con brevi sezioni.",
    "background": "Stai svolgendo un compito in background: il risultato verrà letto con calma su Telegram e nell'app.",
}


def system_blocks(agent: store.AgentConfig, channel: str, last_user_text: str) -> list[dict]:
    """Prompt di sistema in due blocchi: la parte fissa va in cache, quella variabile (ora, memoria) no."""
    static = _static_prompt(agent, channel)
    dynamic = _dynamic_prompt(agent, last_user_text)
    blocks = [{"type": "text", "text": static, "cache_control": {"type": "ephemeral"}}]
    if dynamic:
        blocks.append({"type": "text", "text": dynamic})
    return blocks


def system_prompt(agent: store.AgentConfig, channel: str, last_user_text: str) -> str:
    return "\n\n".join(b["text"] for b in system_blocks(agent, channel, last_user_text))


def _static_prompt(agent: store.AgentConfig, channel: str) -> str:
    parts = [
        agent.persona.strip(),
        CHANNEL_STYLE.get(channel, ""),
        "L'ora e la data locali sono nell'orologio di sistema in fondo a queste istruzioni (affidabile, aggiornato a ogni "
        "messaggio): usalo direttamente, senza strumenti; usa get_time solo per altri fusi orari. Interpreta date relative "
        "('domani', 'venerdì') rispetto a quel momento e passa agli strumenti date ISO locali.",
        "Lo storico della conversazione contiene solo i testi finali: gli strumenti usati nei turni precedenti non sono visibili, "
        "ma quelle risposte erano basate su dati reali. Non rimetterle in dubbio, non correggerle e non scusarti per esse "
        "a meno che l'utente segnali un errore. Quando usi uno strumento, non anticipare la risposta prima di averne letto il risultato.",
        "Azioni che inviano o creano qualcosa per conto dell'utente (email, eventi) richiedono la sua conferma: "
        "preparale con lo strumento e lascia che l'utente approvi. Non dire mai che sono state eseguite prima della conferma.",
        "Giri sul Mac dell'utente (cartella Home ~). Con gli strumenti mac_* puoi aprire app e file, cercare e leggere "
        "documenti, creare note, regolare il volume, guardare lo schermo e usare i Comandi rapidi. Per trovare un file "
        "cerca prima con mac_find_files, poi leggi il risultato più pertinente. Per compiti che si ripetono nel tempo usa task_create. "
        "Per YouTube ('apri YouTube e cerca X', 'metti su YouTube X') usa lo strumento youtube.",
    ]
    if "mcp" in agent.tools and mcp_client.manager.total():
        parts.append(
            "Collegamenti MCP attivi (strumenti con prefisso mcp__): " + mcp_client.manager.describe_servers() + ". "
            "Se ti serve uno strumento di questi servizi che non vedi nella tua lista, usa find_tools. Gli strumenti MCP "
            "che modificano dati possono richiedere la conferma dell'utente: in quel caso non dire che è già fatto."
        )
    return "\n\n".join(p for p in parts if p)


def _dynamic_prompt(agent: store.AgentConfig, last_user_text: str) -> str:
    now = datetime.now(tz())
    parts = [f"Orologio di sistema: {GIORNI[now.weekday()]} {now:%d/%m/%Y}, ore {now:%H:%M} (fuso {tz()})."]
    if "memory" in agent.tools:
        ctx = memory.context_for(agent.id, last_user_text)
        if ctx:
            parts.append("Cosa ricordi dell'utente (pertinente):\n" + ctx)
    vocab = db.get_setting("vocabulary") or []
    if vocab:
        parts.append("Vocabolario personale dell'utente (nomi propri che il riconoscimento vocale può storpiare): "
                     + ", ".join(vocab) + ". Se nella richiesta compare una parola dal suono simile, intendi la voce del "
                     "vocabolario (es. nelle ricerche email usa il nome corretto). In generale, le richieste a voce possono "
                     "contenere errori di trascrizione: interpreta l'intenzione.")
    g = db.get_setting("google_email")
    if g and ({"calendar", "gmail"} & set(agent.tools)):
        parts.append(f"Account Google collegato: {g}.")
    return "\n\n".join(p for p in parts if p)


# ---------- velocità: scelta del modello e cache ----------

SPEED_DEFAULTS = {"fastlane": True, "router": True, "fast_model": os.getenv("FAST_MODEL", "claude-haiku-4-5-20251001"),
                  "code_tools": True}

CODE_EXEC_PTC = {"type": "code_execution_20260120", "name": "code_execution"}  # + programmatic tool calling
CODE_EXEC_BASIC = {"type": "code_execution_20250825", "name": "code_execution"}  # per Haiku (niente PTC)


def _has_container_upload(messages: list[dict]) -> bool:
    for m in messages:
        c = m.get("content")
        if isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "container_upload" for b in c):
            return True
    return False

# richieste che meritano il modello principale anche se brevi
_HEAVY = re.compile(
    r"\b(analizz|confront|riassum|spieg|perch[eé]|scriv|redig|prepar|bozza|email|mail|rispondi a|pianific|organizz|"
    r"strategi|codice|programm|calcol|ricerc|cerca (su|in) (internet|web|rete)|documento|file|pdf|leggi|consigli|"
    r"valut|pro e contro|differenz|traduc|elenc|lista|report|piano|progett|schermo|guarda|briefing|riepilog)",
    re.I,
)


def speed_settings() -> dict:
    return {**SPEED_DEFAULTS, **(db.get_setting("speed") or {})}


def pick_model(agent: store.AgentConfig, history: list[dict], channel: str) -> str:
    """Haiku per le richieste brevi e semplici a voce/chat, il modello dell'agente per tutto il resto."""
    main = agent.model or os.getenv("DEFAULT_MODEL", "claude-sonnet-5-5")
    s = speed_settings()
    if channel not in ("ui", "telegram") or not s["router"] or not history:
        return main
    last = history[-1].get("content", "")
    if not isinstance(last, str):
        return main
    words = len(last.split())
    if words <= 14 and not _HEAVY.search(last):
        return s["fast_model"] or main
    return main


def _cached_tools(schemas: list[dict]) -> list[dict]:
    """Segna l'ultimo strumento come punto di cache: tutte le definizioni restano in cache tra un messaggio e l'altro."""
    if not schemas:
        return schemas
    out = [dict(t) for t in schemas]
    idx = max((i for i, t in enumerate(out) if "input_schema" in t), default=None)  # ultimo strumento "nostro"
    if idx is not None:
        out[idx] = {**out[idx], "cache_control": {"type": "ephemeral"}}
    return out


def _mark_last_message(messages: list[dict]) -> list[dict]:
    """Cache incrementale della conversazione: il punto di cache segue l'ultimo messaggio."""
    msgs = copy.copy(messages)
    if not msgs:
        return msgs
    last = dict(msgs[-1])
    content = last["content"]
    if isinstance(content, str):
        if not content.strip():
            return msgs
        content = [{"type": "text", "text": content}]
    else:
        content = [dict(b) if isinstance(b, dict) else b for b in content]
    for i in range(len(content) - 1, -1, -1):
        if isinstance(content[i], dict) and content[i].get("type") in ("text", "tool_result", "image"):
            content[i] = {**content[i], "cache_control": {"type": "ephemeral"}}
            break
    last["content"] = content
    msgs[-1] = last
    return msgs


def log_usage(channel: str, model: str, usage, ms: int) -> None:
    if not usage:
        return
    u = usage if isinstance(usage, dict) else usage.model_dump()
    try:
        db.execute(
            "INSERT INTO usage(day, channel, model, input, output, cache_read, cache_write, ms) VALUES (?,?,?,?,?,?,?,?)",
            (datetime.now(tz()).date().isoformat(), channel, model, u.get("input_tokens") or 0, u.get("output_tokens") or 0,
             u.get("cache_read_input_tokens") or 0, u.get("cache_creation_input_tokens") or 0, ms),
        )
    except Exception:  # noqa: BLE001
        pass


async def run(agent: store.AgentConfig, history: list[dict], ctx: tools.Ctx, max_steps: int = MAX_STEPS) -> AsyncIterator[dict]:
    """Produce eventi: {type: text|tool_use|tool_result|confirm|done|error, ...}."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        async for ev in _demo(history):
            yield ev
        return

    client = AsyncAnthropic()
    model = pick_model(agent, history, ctx.channel)
    messages = [{"role": m["role"], "content": m["content"]} for m in history]
    last_user = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")
    tool_schemas = tools.schemas_for(agent.tools)
    # code execution: analisi di Excel/CSV, calcoli, grafici e programmatic tool calling (il modello scrive un piccolo
    # programma che chiama più strumenti di lettura in serie, senza un giro di risposta per ognuno)
    is_haiku = "haiku" in model
    needs_code = _has_container_upload(messages)
    code_on = speed_settings().get("code_tools", True) and os.getenv("ANTHROPIC_CODE_EXECUTION", "1") != "0"
    if needs_code or (code_on and not is_haiku):
        if is_haiku and needs_code:
            model = agent.model or os.getenv("DEFAULT_MODEL", "claude-sonnet-5-5")  # documenti: modello principale
            is_haiku = "haiku" in model
        code_tool = CODE_EXEC_BASIC if is_haiku else CODE_EXEC_PTC
        if not is_haiku:
            tool_schemas = [({**t, "allowed_callers": ["direct", CODE_EXEC_PTC["type"]]} if t.get("name") in tools.PTC_SAFE else t)
                            for t in tool_schemas]
        tool_schemas = tool_schemas + [code_tool]
    mcp = mcp_client.manager
    use_mcp = "mcp" in agent.tools and mcp.total() > 0
    mcp_active: list[str] = mcp.select(last_user if isinstance(last_user, str) else "") if use_mcp else []

    def build_tools() -> list[dict]:
        out = _cached_tools(tool_schemas)  # strumenti fissi in cache, poi quelli MCP (variabili)
        if use_mcp:
            out += [mcp.schema(n) for n in mcp_active if n in mcp.index]
            if len(mcp_active) < mcp.total():
                out.append(mcp_client.FIND_TOOLS)
        return out

    params: dict = {"model": model, "max_tokens": agent.max_tokens,
                    "system": system_blocks(agent, ctx.channel, last_user if isinstance(last_user, str) else "")}
    if tool_schemas or use_mcp:
        params["tools"] = build_tools()
    if agent.temperature is not None:
        params["temperature"] = agent.temperature
    params["model"] = model
    yield {"type": "meta", "model": model}

    final = None
    totals: dict = {}
    t0 = time.perf_counter()
    first_ms = 0
    for _ in range(max_steps):
        async with client.messages.stream(messages=_mark_last_message(messages), **params) as stream:
            async for event in stream:
                if event.type == "content_block_start" and event.content_block.type in ("tool_use", "server_tool_use"):
                    yield {"type": "tool_use", "name": event.content_block.name}
                elif event.type == "content_block_delta" and event.delta.type == "text_delta":
                    if not first_ms:
                        first_ms = int((time.perf_counter() - t0) * 1000)
                    yield {"type": "text", "delta": event.delta.text}
            final = await stream.get_final_message()
        cont = getattr(final, "container", None)
        if cont is not None and getattr(cont, "id", None):
            params["container"] = cont.id  # stesso contenitore per i passi successivi (file, variabili, chiamate dal codice)
        for f in await asyncio.to_thread(documents.collect_outputs, final.content):
            yield {"type": "file", "file": {k: f[k] for k in ("id", "name", "mime", "url")}}
            ctx.outputs.append(f)
        if final.usage:
            for k, v in final.usage.model_dump().items():
                if isinstance(v, int):
                    totals[k] = totals.get(k, 0) + v

        messages.append({"role": "assistant", "content": final.content})
        if final.stop_reason == "pause_turn":
            continue
        if final.stop_reason != "tool_use":
            break

        results = []
        for block in final.content:
            if block.type == "tool_use":
                if block.name == "find_tools":
                    found = mcp.search((block.input or {}).get("query", ""), 8)
                    new = [n for n, _ in found if n not in mcp_active]
                    mcp_active.extend(new)
                    params["tools"] = build_tools()
                    output = ("Strumenti ora disponibili:\n" + "\n".join(
                        f"- {n}: {mcp.schema(n)['description'][:160]}" for n, _ in found)) if found else \
                        "Nessuno strumento trovato: prova con altre parole (in inglese) o con il nome del servizio."
                elif block.name.startswith("mcp__"):
                    if block.name not in mcp_active:
                        mcp_active.append(block.name)
                    if block.name in mcp.index and mcp.needs_approval(block.name):
                        output = tools._confirm(ctx, "mcp_call", {"tool": block.name, "arguments": block.input or {}})
                    else:
                        output = await mcp.call(block.name, block.input or {})
                else:
                    output = await asyncio.to_thread(tools.run_tool, ctx, block.name, block.input or {})
                preview = output if isinstance(output, str) else "(immagine dello schermo)"
                yield {"type": "tool_result", "name": block.name, "output": preview[:400]}
                while ctx.events:
                    yield ctx.events.pop(0)
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
        messages.append({"role": "user", "content": results})

    log_usage(ctx.channel, model, totals, first_ms)
    yield {"type": "done", "usage": totals or None}


async def run_once(agent: store.AgentConfig, history: list[dict], ctx: tools.Ctx) -> tuple[str, list[dict]]:
    """Versione non-streaming (Telegram, briefing): restituisce testo finale + richieste di conferma."""
    text, confirms = "", []
    async for ev in run(agent, history, ctx):
        if ev["type"] == "text":
            text += ev["delta"]
        elif ev["type"] == "confirm":
            confirms.append(ev["action"])
        elif ev["type"] == "error":
            text += f"\nErrore: {ev.get('message')}"
    return text.strip(), confirms


async def _demo(history: list[dict]) -> AsyncIterator[dict]:
    last = history[-1]["content"] if history else ""
    reply = (
        "Modalità dimostrativa attiva. Il mio nucleo dati non è ancora collegato: "
        "aggiungi la variabile ANTHROPIC_API_KEY nel file punto env del backend e riavviami. "
        f"Hai detto: {str(last)[:120]}"
    )
    yield {"type": "tool_use", "name": "demo_core"}
    await asyncio.sleep(0.6)
    for word in reply.split(" "):
        yield {"type": "text", "delta": word + " "}
        await asyncio.sleep(0.04)
    yield {"type": "done", "usage": None}
