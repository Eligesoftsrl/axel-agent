"""Corsia veloce: comandi semplici eseguiti subito, senza passare da Claude.

Riconosce solo frasi brevi e inequivocabili (l'intera frase deve corrispondere a uno schema):
  luci  · "accendi/spegni le luci (in cucina)", "luci al 30%", "luci della sala blu", "abbassa/alza le luci"
  musica· "pausa", "riprendi la musica", "prossima canzone", "brano precedente", "volume spotify al 40"
  Mac   · "volume al 30", "alza/abbassa il volume", "muto", "togli il muto"
  ora   · "che ore sono", "che giorno è oggi"
Tutto il resto (anche "spegni le luci tra 10 minuti") va a Claude come sempre.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from . import hue, mac, spotify, store
from .google_api import tz

GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre",
        "novembre", "dicembre"]

COLORS = r"rosso|rossa|blu|verde|viola|rosa|arancione|giallo|gialla|azzurro|azzurra|bianco|bianca|caldo|calda|freddo|fredda|naturale"
_COLOR_NORM = {"rossa": "rosso", "gialla": "giallo", "azzurra": "azzurro", "bianca": "bianco", "calda": "caldo",
               "fredda": "freddo"}

NUMBERS = {"zero": 0, "dieci": 10, "venti": 20, "trenta": 30, "quaranta": 40, "cinquanta": 50, "sessanta": 60,
           "settanta": 70, "ottanta": 80, "novanta": 90, "cento": 100, "metà": 50, "meta": 50, "massimo": 100,
           "minimo": 5}


@dataclass
class Result:
    tool: str  # gruppo di strumenti richiesto (hue, spotify, mac, base)
    text: str
    widget: dict | None = None
    ok: bool = True
    events: list = field(default_factory=list)


def _clean(text: str) -> str:
    t = text.lower().strip()
    t = re.sub(r"^(ehi |hey |ok )?(axel|aksel|axl)[,.!:]?\s*", "", t)
    t = re.sub(r"[.!?]+$", "", t).strip()
    t = re.sub(r"\b(per favore|per piacere|grazie|dai)\b", "", t)
    t = re.sub(r"^(puoi|potresti|mi|me)\s+", "", t)
    t = re.sub(r"\s+", " ", t).strip(" ,")
    return t


def _num(s: str | None) -> int | None:
    if not s:
        return None
    s = s.strip().rstrip("%").replace("per cento", "").strip()
    if s.isdigit():
        return max(0, min(100, int(s)))
    return NUMBERS.get(s)


NUM = r"(\d{1,3}|zero|dieci|venti|trenta|quaranta|cinquanta|sessanta|settanta|ottanta|novanta|cento|metà|meta|massimo|minimo)\s*(?:%|per ?cento)?"
ROOM = r"(?:\s+(?:in|nel|nella|nello|del|della|dello|di|dei|delle|a)\s+(?:la |il |lo |l')?([a-zà-ù' ]{2,30}?))?"
LIGHTS = r"(?:le |la )?(?:luci|luce|lampade|lampada)"


def _room(r: str | None) -> str:
    r = (r or "").strip()
    return r if r and r not in ("casa", "tutta casa", "tutta la casa", "tutte") else "tutte"


# ---------- handler ----------

def _lights(on: bool | None = None, bri: int | None = None, color: str = "", room: str | None = None) -> Result:
    target = _room(room)
    try:
        return Result("hue", hue.set_lights(target, on=on, brightness=bri, color=color))
    except Exception as exc:  # noqa: BLE001
        return Result("hue", str(exc), ok=False)


def _lights_relative(up: bool, room: str | None) -> Result:
    return _lights(bri=80 if up else 25, room=room)


def _spotify(action: str, value: int | None = None) -> Result:
    text = spotify.control(action, value)
    ok = not spotify.is_error(text)
    widget = None
    if ok and action != "volume":
        try:
            st = spotify.wait_state(timeout=3.0)
            widget = {"type": "widget", "widget": "spotify", "data": st} if st else None
        except Exception:  # noqa: BLE001
            pass
    return Result("spotify", text, widget=widget, ok=ok)


def _volume(level: int | None = None, delta: int = 0, mute: bool | None = None) -> Result:
    try:
        if mute is not None:
            return Result("mac", mac.volume(mute=mute))
        if delta:
            cur = int(re.sub(r"\D", "", mac.volume()) or 50)
            level = cur + delta
        return Result("mac", mac.volume(level=level))
    except Exception as exc:  # noqa: BLE001
        return Result("mac", str(exc), ok=False)


def _time() -> Result:
    now = datetime.now(tz())
    return Result("base", f"Sono le {now:%H:%M}.")


def _date() -> Result:
    now = datetime.now(tz())
    return Result("base", f"Oggi è {GIORNI[now.weekday()]} {now.day} {MESI[now.month - 1]}.")


Rule = tuple[re.Pattern, Callable[[re.Match], Result]]

RULES: list[Rule] = [
    # ---- luci ----
    (re.compile(rf"^(?:accendi|accendere|accendimi) {LIGHTS}{ROOM}$"), lambda m: _lights(on=True, room=m.group(1))),
    (re.compile(rf"^(?:spegni|spegnere|spegnimi) {LIGHTS}{ROOM}$"), lambda m: _lights(on=False, room=m.group(1))),
    (re.compile(rf"^{LIGHTS}{ROOM} (?:accese|on)$"), lambda m: _lights(on=True, room=m.group(1))),
    (re.compile(rf"^{LIGHTS}{ROOM} (?:spente|off)$"), lambda m: _lights(on=False, room=m.group(1))),
    (re.compile(rf"^(?:metti |porta |imposta )?{LIGHTS}{ROOM} (?:al|a) {NUM}$"),
     lambda m: _lights(bri=_num(m.group(2)), room=m.group(1))),
    (re.compile(rf"^(?:metti |fai |colora )?{LIGHTS}{ROOM} (?:di |in |color[ei] )?({COLORS})$"),
     lambda m: _lights(color=_COLOR_NORM.get(m.group(2), m.group(2)), room=m.group(1))),
    (re.compile(rf"^(abbassa|alza|aumenta|diminuisci) {LIGHTS}{ROOM}$"),
     lambda m: _lights_relative(m.group(1) in ("alza", "aumenta"), m.group(2))),
    # ---- musica ----
    (re.compile(r"^(?:metti in |fai )?pausa(?: la musica| spotify| la canzone)?$|^(?:ferma|stoppa) (?:la musica|spotify|la canzone)$"),
     lambda m: _spotify("pause")),
    (re.compile(r"^(?:riprendi|fai ripartire|rimetti|riattiva|play)(?: la musica| spotify| la canzone)?$"),
     lambda m: _spotify("play")),
    (re.compile(r"^(?:prossim[ao]|successiv[ao]|salta|avanti|cambia)(?: canzone| brano| pezzo| traccia)?$|"
                r"^(?:la |il |metti la |metti il |passa alla |passa al )?(?:prossim[ao]|successiv[ao]) (?:canzone|brano|pezzo|traccia)$|"
                r"^(?:salta|cambia) (?:questa |la |il )?(?:canzone|brano|pezzo|traccia)$"),
     lambda m: _spotify("next")),
    (re.compile(r"^(?:precedente|torna indietro|indietro)(?: canzone| brano| traccia)?$|"
                r"^(?:la |il |metti la |metti il |torna alla |torna al )?(?:canzone|brano|pezzo|traccia) precedente$"),
     lambda m: _spotify("previous")),
    (re.compile(rf"^(?:metti |imposta )?(?:il )?volume (?:di |della |del )?(?:spotify|musica) (?:al|a) {NUM}$"),
     lambda m: _spotify("volume", _num(m.group(1)))),
    # ---- volume del Mac ----
    (re.compile(rf"^(?:metti |imposta |porta )?(?:il )?volume(?: del mac)? (?:al|a) {NUM}$"),
     lambda m: _volume(level=_num(m.group(1)))),
    (re.compile(r"^(alza|aumenta) (?:il )?volume(?: del mac)?$"), lambda m: _volume(delta=15)),
    (re.compile(r"^(abbassa|diminuisci) (?:il )?volume(?: del mac)?$"), lambda m: _volume(delta=-15)),
    (re.compile(r"^(?:metti |attiva )?(?:il )?muto$|^(?:silenzia|disattiva) (?:l'audio|il mac|l'audio del mac)$"),
     lambda m: _volume(mute=True)),
    (re.compile(r"^(?:togli|disattiva) (?:il )?muto$|^riattiva (?:l'audio|il suono)$"), lambda m: _volume(mute=False)),
    # ---- ora e data ----
    (re.compile(r"^(?:che ore sono|che ora è|che ora e|mi dici l'ora|dimmi l'ora|ora)$"), lambda m: _time()),
    (re.compile(r"^(?:che giorno è|che giorno e|che giorno è oggi|che data è oggi|che data è|quanti ne abbiamo(?: oggi)?)$"),
     lambda m: _date()),
]

_REQUIRES = {"hue": "hue", "spotify": "spotify", "mac": "mac", "base": None}


def match(text: str, agent: store.AgentConfig) -> tuple[re.Match, Callable[[re.Match], Result]] | None:
    """Trova una regola per la frase; None se il comando non è semplice o lo strumento non è attivo."""
    if not isinstance(text, str) or len(text) > 80:
        return None
    t = _clean(text)
    for rx, fn in RULES:
        m = rx.match(t)
        if m:
            group = _group_of(fn, m)
            if group and group not in agent.tools:
                return None
            if group == "mac" and not mac.IS_MAC:
                return None
            if group == "hue" and not hue.status().get("connected"):
                return None
            if group == "spotify" and not spotify.status().get("connected"):
                return None
            return m, fn
    return None


def _group_of(fn: Callable, m: re.Match) -> str | None:
    """Gruppo di strumenti di una regola, ricavato dal nome della funzione chiamata."""
    code = fn.__code__.co_names
    if "_lights" in code or "_lights_relative" in code:
        return "hue"
    if "_spotify" in code:
        return "spotify"
    if "_volume" in code:
        return "mac"
    return None
