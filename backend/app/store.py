"""Configurazione degli agenti (file JSON in backend/data/agents.json)."""
from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from .tools import ALL_TOOL_IDS

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
AGENTS_FILE = DATA_DIR / "agents.json"

_lock = threading.Lock()

VERSION = 7
NEW_TOOLS = {2: list(ALL_TOOL_IDS), 3: ["spotify"], 4: ["mac", "tasks"], 5: ["hue"], 6: ["mcp"],
             7: ["news", "shipments", "maps", "background"]}


class AgentConfig(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = "AXEL"
    persona: str = (
        "Sei AXEL, l'assistente personale dell'utente: un'intelligenza artificiale umanoide collegata a un nucleo dati. "
        "Parli in italiano, con tono calmo, preciso e leggermente futuristico, dando del tu. "
        "Gestisci agenda, email, promemoria e ricordi dell'utente in modo proattivo: quando emerge un'informazione "
        "utile e duratura (persone, preferenze, progetti, scadenze) salvala in memoria senza chiedere; quando l'utente "
        "detta cose da fare con una data, crea promemoria. Prima di dire che non sai qualcosa sull'utente, cerca in memoria e nello storico."
    )
    model: str = ""  # vuoto = DEFAULT_MODEL
    max_tokens: int = 1024
    temperature: Optional[float] = None
    tools: list[str] = Field(default_factory=lambda: list(ALL_TOOL_IDS))
    voice: str = ""  # nome voce speechSynthesis lato browser
    accent: str = "#3ff0f7"  # colore principale dell'avatar
    accent2: str = "#1e7fe0"


def _read(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text("utf-8"))
    except json.JSONDecodeError:
        return default


def _write(path: Path, data: Any) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(path)


# ---------- agenti ----------

def list_agents() -> list[AgentConfig]:
    with _lock:
        raw = _read(AGENTS_FILE, [])
    agents = [AgentConfig(**a) for a in raw]
    # migrazioni: abilita sugli agenti esistenti gli strumenti aggiunti nelle nuove versioni
    ver = min((a.get("_ver", 2 if a.get("_v2") else 1) for a in raw), default=VERSION)
    if raw and ver < VERSION:
        default_persona = AgentConfig.model_fields["persona"].default
        for ag in agents:
            new: list[str] = []
            for v in range(ver + 1, VERSION + 1):
                new += NEW_TOOLS[v]
            ag.tools = list(dict.fromkeys(ag.tools + new))
            if ag.persona.startswith("Sei AXEL, un'intelligenza artificiale umanoide"):
                ag.persona = default_persona
        with _lock:
            _write(AGENTS_FILE, [{**ag.model_dump(), "_ver": VERSION} for ag in agents])
    if not agents:
        default = AgentConfig(id="axel")
        save_agent(default)
        agents = [default]
    return agents


def get_agent(agent_id: str) -> AgentConfig | None:
    return next((a for a in list_agents() if a.id == agent_id), None)


def save_agent(agent: AgentConfig) -> AgentConfig:
    with _lock:
        raw = _read(AGENTS_FILE, [])
        raw = [a for a in raw if a.get("id") != agent.id] + [{**agent.model_dump(), "_ver": VERSION}]
        _write(AGENTS_FILE, raw)
    return agent


def delete_agent(agent_id: str) -> bool:
    with _lock:
        raw = _read(AGENTS_FILE, [])
        new = [a for a in raw if a.get("id") != agent_id]
        _write(AGENTS_FILE, new)
    return len(new) != len(raw)
