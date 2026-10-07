"""Chiamate veloci a Haiku per lavori di sfondo (estrarre dati, filtrare, riassumere) con risposta JSON."""
from __future__ import annotations

import json
import logging
import os

log = logging.getLogger("axel.llm")
FAST_MODEL = os.getenv("TRIAGE_MODEL", "claude-haiku-4-5-20251001")


async def ask_json(prompt: str, max_tokens: int = 1200, model: str | None = None) -> dict | None:
    """Chiede una risposta JSON; None se manca la chiave o la risposta non è valida."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None
    from anthropic import AsyncAnthropic

    try:
        msg = await AsyncAnthropic().messages.create(
            model=model or FAST_MODEL, max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt + "\n\nRispondi SOLO con JSON valido, senza testo prima o dopo."}],
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("chiamata Haiku fallita: %s", exc)
        return None
    text = "".join(b.text for b in msg.content if b.type == "text")
    try:
        return json.loads(text[text.index("{"): text.rindex("}") + 1])
    except ValueError:
        log.warning("JSON non valido da Haiku: %s", text[:200])
        return None


async def ask_text(prompt: str, max_tokens: int = 800, model: str | None = None) -> str:
    if not os.getenv("ANTHROPIC_API_KEY"):
        return ""
    from anthropic import AsyncAnthropic

    try:
        msg = await AsyncAnthropic().messages.create(model=model or FAST_MODEL, max_tokens=max_tokens,
                                                     messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in msg.content if b.type == "text").strip()
    except Exception as exc:  # noqa: BLE001
        log.warning("chiamata Haiku fallita: %s", exc)
        return ""
