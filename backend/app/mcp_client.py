"""Client MCP: AXEL usa gli strumenti di qualsiasi server MCP (Notion, GitHub, filesystem, database…).

Configurazione in backend/data/mcp.json (stesso formato di Claude Desktop, più due campi facoltativi):

{
  "mcpServers": {
    "filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/Users/io/Documents"]},
    "github": {"url": "https://api.githubcopilot.com/mcp/", "headers": {"Authorization": "Bearer ghp_..."}},
    "notion": {"command": "npx", "args": ["-y", "@notionhq/notion-mcp-server"], "env": {"NOTION_TOKEN": "ntn_..."},
               "approval": "auto-read", "enabled": true}
  }
}

approval:  "auto-read" (predefinito) → gli strumenti di sola lettura partono subito, gli altri chiedono conferma
           "ask"  → chiede sempre conferma        "auto" → non chiede mai (solo per server di cui ti fidi)
Si gestisce anche da Integrazioni → Collegamenti MCP.

Ricerca strumenti: se i server espongono tanti strumenti, a Claude vengono passati solo quelli pertinenti alla
richiesta, più lo strumento find_tools per cercarne altri al volo. Così il prompt resta leggero e veloce.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import unicodedata
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from . import db

log = logging.getLogger("axel.mcp")

CONFIG = db.DATA_DIR / "mcp.json"
LOG_DIR = db.DATA_DIR / "mcp-logs"
ALL_TOOLS_LIMIT = int(os.getenv("MCP_ALL_TOOLS_LIMIT", "20"))  # fino a qui li passa tutti, oltre usa la ricerca
SELECT_LIMIT = int(os.getenv("MCP_SELECT_LIMIT", "12"))
CALL_TIMEOUT = 120
APPROVALS = ("auto-read", "ask", "auto")


def available() -> bool:
    try:
        import mcp  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


# ---------- configurazione ----------

def load_config() -> dict[str, dict]:
    if not CONFIG.exists():
        return {}
    try:
        data = json.loads(CONFIG.read_text("utf-8"))
        return dict(data.get("mcpServers", {}))
    except Exception as exc:  # noqa: BLE001
        log.error("mcp.json non valido: %s", exc)
        return {}


def save_config(servers: dict[str, dict]) -> None:
    CONFIG.write_text(json.dumps({"mcpServers": servers}, indent=2, ensure_ascii=False), "utf-8")
    try:
        os.chmod(CONFIG, 0o600)  # può contenere token
    except OSError:
        pass


def _slug(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", s)


def _qualify(server: str, tool: str) -> str:
    return f"mcp__{_slug(server)}__{_slug(tool)}"[:64]


def _get(obj: Any, *names: str, default=None):
    """Legge un campo sia dallo stile 2.x (snake_case) sia 1.x (camelCase)."""
    for n in names:
        v = getattr(obj, n, None)
        if v is not None:
            return v
        if isinstance(obj, dict) and obj.get(n) is not None:
            return obj[n]
    return default


# ---------- server ----------

@dataclass
class Server:
    name: str
    cfg: dict
    status: str = "idle"  # idle | connecting | connected | error | disabled
    error: str = ""
    tools: list = field(default_factory=list)
    session: Any = None
    task: asyncio.Task | None = None
    stop: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def approval(self) -> str:
        a = self.cfg.get("approval", "auto-read")
        return a if a in APPROVALS else "auto-read"

    def info(self) -> dict:
        safe = {k: v for k, v in self.cfg.items() if k not in ("env", "headers")}
        safe["env_keys"] = sorted((self.cfg.get("env") or {}).keys())
        safe["header_keys"] = sorted((self.cfg.get("headers") or {}).keys())
        return {
            "name": self.name, "status": self.status, "error": self.error, "approval": self.approval,
            "enabled": self.cfg.get("enabled", True), "config": safe,
            "tools": [{"name": _get(t, "name"), "description": (_get(t, "description") or "")[:200],
                       "read_only": _read_only(t)} for t in self.tools],
        }


def _read_only(tool) -> bool:
    ann = _get(tool, "annotations")
    return bool(ann is not None and _get(ann, "read_only_hint", "readOnlyHint"))


class Manager:
    def __init__(self) -> None:
        self.servers: dict[str, Server] = {}
        self.loop: asyncio.AbstractEventLoop | None = None
        self.index: dict[str, tuple[str, Any]] = {}  # nome qualificato -> (server, tool)

    # ----- ciclo di vita -----
    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        if not available():
            if load_config():
                log.warning("Ci sono server in mcp.json ma il pacchetto 'mcp' non è installato (pip install mcp)")
            return
        for name, cfg in load_config().items():
            self._spawn(name, cfg)

    async def stop_all(self) -> None:
        for s in list(self.servers.values()):
            await self._stop(s)
        self.servers.clear()
        self._reindex()

    async def reload(self) -> None:
        await self.stop_all()
        await self.start()

    async def _stop(self, s: Server) -> None:
        s.stop.set()
        if s.task:
            try:
                await asyncio.wait_for(s.task, 8)
            except (asyncio.TimeoutError, Exception):  # noqa: BLE001
                s.task.cancel()

    def _spawn(self, name: str, cfg: dict) -> None:
        s = Server(name=name, cfg=cfg)
        self.servers[name] = s
        if not cfg.get("enabled", True):
            s.status = "disabled"
            return
        s.task = asyncio.create_task(self._run(s), name=f"mcp-{name}")

    async def _run(self, s: Server) -> None:
        backoff = 5
        while not s.stop.is_set():
            s.status, s.error = "connecting", ""
            try:
                async with AsyncExitStack() as stack:
                    session = await self._connect(s, stack)
                    s.session = session
                    s.tools = await self._list_tools(session)
                    s.status = "connected"
                    backoff = 5
                    self._reindex()
                    log.info("MCP %s collegato: %d strumenti", s.name, len(s.tools))
                    await s.stop.wait()
            except asyncio.CancelledError:
                break
            except BaseException as exc:  # noqa: BLE001 (anche ExceptionGroup di anyio)
                msg = _err_text(exc)
                if "FileNotFoundError" in msg and not s.cfg.get("url"):
                    cmd = s.cfg.get("command", "")
                    need = {"npx": "Node.js (brew install node)", "uvx": "uv", "docker": "Docker"}.get(cmd, "il programma")
                    msg = f"Comando «{cmd}» non trovato: serve {need} installato sul Mac."
                s.status, s.error = "error", msg
                log.warning("MCP %s: %s", s.name, msg)
            finally:
                s.session = None
                self._reindex()
            if s.stop.is_set():
                break
            try:  # riprova con attesa crescente
                await asyncio.wait_for(s.stop.wait(), backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, 300)
        if s.status != "error":
            s.status = "idle"

    async def _connect(self, s: Server, stack: AsyncExitStack):
        from mcp import ClientSession

        cfg = s.cfg
        if cfg.get("url"):
            headers = {k: str(v) for k, v in (cfg.get("headers") or {}).items()}
            if cfg.get("transport") == "sse":
                from mcp.client.sse import sse_client

                streams = await stack.enter_async_context(sse_client(cfg["url"], headers=headers))
            else:
                from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

                client = await stack.enter_async_context(create_mcp_http_client(headers=headers))
                streams = await stack.enter_async_context(streamable_http_client(cfg["url"], http_client=client))
        else:
            from mcp import StdioServerParameters
            from mcp.client.stdio import stdio_client

            if not cfg.get("command"):
                raise ValueError("manca 'command' (o 'url')")
            env = {**os.environ, **{k: str(v) for k, v in (cfg.get("env") or {}).items()}}
            args = [os.path.expanduser(str(a)) if str(a).startswith("~") else str(a) for a in cfg.get("args", [])]
            params = StdioServerParameters(command=os.path.expanduser(cfg["command"]), args=args,
                                           env=env, cwd=os.path.expanduser(cfg["cwd"]) if cfg.get("cwd") else None)
            LOG_DIR.mkdir(exist_ok=True)
            errlog = stack.enter_context(open(LOG_DIR / f"{_slug(s.name)}.log", "a", encoding="utf-8"))
            try:
                streams = await stack.enter_async_context(stdio_client(params, errlog=errlog))
            except TypeError:
                streams = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(streams[0], streams[1]))
        await asyncio.wait_for(session.initialize(), 45)
        return session

    @staticmethod
    async def _list_tools(session) -> list:
        tools, cursor = [], None
        for _ in range(20):
            res = await session.list_tools(cursor) if cursor else await session.list_tools()
            tools += list(_get(res, "tools", default=[]))
            cursor = _get(res, "next_cursor", "nextCursor")
            if not cursor:
                break
        return tools

    def _reindex(self) -> None:
        idx = {}
        for s in self.servers.values():
            if s.status == "connected":
                for t in s.tools:
                    idx[_qualify(s.name, _get(t, "name"))] = (s.name, t)
        self.index = idx

    # ----- strumenti per Claude -----
    def schema(self, qualified: str) -> dict:
        server, t = self.index[qualified]
        params = dict(_get(t, "input_schema", "inputSchema", default=None) or {"type": "object", "properties": {}})
        params.pop("$schema", None)
        params.setdefault("type", "object")
        desc = (_get(t, "description") or _get(t, "title") or _get(t, "name") or "").strip()
        return {"name": qualified, "description": f"[{server}] {desc}"[:1024], "input_schema": params}

    def total(self) -> int:
        return len(self.index)

    def select(self, query: str) -> list[str]:
        """Strumenti MCP da passare a Claude per questa richiesta (tutti se sono pochi)."""
        names = list(self.index)
        if len(names) <= ALL_TOOLS_LIMIT:
            return names
        return [n for n, _ in self.search(query, SELECT_LIMIT)]

    def search(self, query: str, limit: int = 8) -> list[tuple[str, float]]:
        q = _tokens(query)
        qtext = _plain(query)
        scored = []
        for name, (server, t) in self.index.items():
            words = _tokens(f"{_get(t, 'name')} {_get(t, 'title') or ''} {_get(t, 'description') or ''}")
            sc = len(q & words) * 1.0 + 0.5 * len(q & _tokens(_get(t, "name")))
            if _plain(server) in qtext:
                sc += 3
            if sc > 0:
                scored.append((name, sc))
        scored.sort(key=lambda x: -x[1])
        return scored[:limit]

    def describe_servers(self) -> str:
        parts = []
        for s in self.servers.values():
            if s.status == "connected":
                d = s.cfg.get("description") or ", ".join(_get(t, "name") for t in s.tools[:6])
                parts.append(f"{s.name} ({len(s.tools)} strumenti: {d})")
        return "; ".join(parts)

    def needs_approval(self, qualified: str) -> bool:
        server, t = self.index[qualified]
        mode = self.servers[server].approval
        if mode == "auto":
            return False
        if mode == "ask":
            return True
        return not _read_only(t)

    async def call(self, qualified: str, args: dict) -> str | list:
        if qualified not in self.index:
            return f"Strumento {qualified} non disponibile (server MCP scollegato?)."
        server, t = self.index[qualified]
        s = self.servers[server]
        if not s.session:
            return f"Il server MCP «{server}» non è collegato in questo momento."
        try:
            res = await asyncio.wait_for(s.session.call_tool(_get(t, "name"), args or {}), CALL_TIMEOUT)
        except asyncio.TimeoutError:
            return f"Il server MCP «{server}» non ha risposto entro {CALL_TIMEOUT} secondi."
        except BaseException as exc:  # noqa: BLE001
            return f"Errore dal server MCP «{server}»: {_err_text(exc)}"
        return _convert(res)

    def call_sync(self, qualified: str, args: dict) -> str:
        """Per le azioni approvate (eseguite in un thread)."""
        if not self.loop:
            return "Client MCP non avviato."
        out = asyncio.run_coroutine_threadsafe(self.call(qualified, args), self.loop).result(CALL_TIMEOUT + 10)
        return out if isinstance(out, str) else "\n".join(b.get("text", "[immagine]") for b in out)

    def status(self) -> list[dict]:
        return [s.info() for s in self.servers.values()]


def _convert(res) -> str | list:
    """Risultato MCP → testo (o blocchi immagine) per Claude."""
    blocks: list[dict] = []
    texts: list[str] = []
    for c in _get(res, "content", default=[]) or []:
        kind = _get(c, "type")
        if kind == "text":
            texts.append(_get(c, "text") or "")
        elif kind == "image":
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": _get(c, "mime_type", "mimeType"),
                                                        "data": _get(c, "data")}})
        elif kind == "resource":
            r = _get(c, "resource")
            texts.append(_get(r, "text") or f"[risorsa {_get(r, 'uri')}]")
        elif kind == "resource_link":
            texts.append(f"[link {_get(c, 'uri')}]")
    structured = _get(res, "structured_content", "structuredContent")
    if not texts and structured is not None:
        texts.append(json.dumps(structured, ensure_ascii=False)[:20000])
    text = "\n".join(texts).strip()
    if len(text) > 20000:
        text = text[:20000] + "\n…(troncato)"
    if _get(res, "is_error", "isError"):
        text = "Errore dallo strumento: " + (text or "nessun dettaglio")
    if blocks:
        return ([{"type": "text", "text": text}] if text else []) + blocks
    return text or "(nessun risultato)"


def _err_text(exc: BaseException) -> str:
    subs = getattr(exc, "exceptions", None)
    if subs:
        return "; ".join(_err_text(e) for e in subs)[:400]
    return (f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__)[:400]


def _plain(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


# poche traduzioni italiano → inglese per la ricerca degli strumenti (le descrizioni sono quasi sempre in inglese)
_IT_EN = {
    "cerca": "search find query", "trova": "search find", "leggi": "read get", "apri": "read get open",
    "crea": "create add new", "aggiungi": "add create append", "elimina": "delete remove", "cancella": "delete remove",
    "modifica": "update edit", "aggiorna": "update", "elenca": "list", "lista": "list", "file": "file files",
    "cartella": "directory folder", "pagina": "page pages", "pagine": "page pages", "database": "database query sql",
    "tabella": "table", "tabelle": "tables", "commento": "comment", "problema": "issue", "repository": "repository repo",
    "progetto": "project", "attivita": "task issue", "scrivi": "write create", "invia": "send post", "messaggio": "message",
    "canale": "channel", "documento": "document doc", "foglio": "sheet spreadsheet", "evento": "event", "utente": "user",
}
_STOP = {"the", "and", "for", "with", "una", "uno", "per", "che", "del", "della", "dei", "delle", "nel", "nella",
         "sul", "sulla", "con", "mio", "mia", "miei", "mie", "this", "from", "into", "dal", "alla", "allo"}


def _tokens(s: str) -> set[str]:
    s = s or ""
    split = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    words = re.findall(r"[a-z0-9]+", _plain(f"{s} {split}".replace("_", " ").replace("-", " ")))
    out = set()
    for w in words:
        if len(w) < 3 or w in _STOP:
            continue
        out.add(w)
        if w.endswith("s") and len(w) > 4:
            out.add(w[:-1])
        base = w[:-2] if len(w) > 5 and w[-2:] in ("mi", "ti", "ci", "lo", "la", "le", "li", "ne") else w
        for x in {w, base}:  # "leggimi" → "leggi"
            if x in _IT_EN:
                out.add(x)
                out.update(_IT_EN[x].split())
    return out


FIND_TOOLS = {
    "name": "find_tools",
    "description": ("Cerca tra gli strumenti dei collegamenti MCP che non vedi ancora nella tua lista e li rende disponibili "
                    "subito. Usalo quando ti serve una capacità di un servizio collegato (es. 'notion search pages', "
                    "'github list issues'). Query meglio in inglese, con il nome del servizio."),
    "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
}

manager = Manager()
