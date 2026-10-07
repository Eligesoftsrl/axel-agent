"""Mappe e traffico: tempi di viaggio e avviso "parti ora" prima degli appuntamenti con un indirizzo.

- Con GOOGLE_MAPS_API_KEY nel .env usa Google (Routes API + Geocoding): tempi con il traffico reale.
- Senza chiave usa OpenStreetMap (Nominatim + OSRM), gratis ma senza traffico.
Indirizzi di casa e ufficio si impostano in Integrazioni → Mappe ("casa" e "ufficio" diventano scorciatoie).
"""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timedelta
from urllib.parse import quote_plus

import httpx

from . import db
from .google_api import tz

log = logging.getLogger("axel.maps")

DEFAULTS = {"home": "", "work": "", "mode": "drive", "leave_alerts": True, "buffer_min": 10}
MODES = {"drive": "DRIVE", "walk": "WALK", "bike": "BICYCLE", "transit": "TRANSIT", "moto": "TWO_WHEELER"}
LABEL = {"drive": "in auto", "walk": "a piedi", "bike": "in bici", "transit": "con i mezzi", "moto": "in moto"}
GMAPS_MODE = {"drive": "driving", "walk": "walking", "bike": "bicycling", "transit": "transit", "moto": "driving"}
ONLINE = re.compile(r"(https?://|meet\.google|zoom\.us|teams\.microsoft|webex|online|videochiamata|call)", re.I)
UA = {"User-Agent": "AXEL-assistente-personale/1.0"}
_geo_cache: dict[str, tuple[float, float, str]] = {}
_route_cache: dict[str, tuple[float, dict]] = {}


class MapsError(RuntimeError):
    pass


def settings() -> dict:
    return {**DEFAULTS, **(db.get_setting("maps") or {})}


def save(s: dict) -> dict:
    cur = settings()
    cur.update({k: v for k, v in s.items() if k in DEFAULTS})
    db.set_setting("maps", cur)
    return cur


def key() -> str:
    return os.getenv("GOOGLE_MAPS_API_KEY", "").strip()


def status() -> dict:
    s = settings()
    return {"provider": "google" if key() else "openstreetmap", "traffic": bool(key()), "home_set": bool(s["home"]),
            "work_set": bool(s["work"])}


def _resolve_alias(place: str) -> str:
    s = settings()
    p = (place or "").strip()
    low = p.lower()
    if low in ("casa", "a casa", "home", "da casa") or not p:
        if not s["home"]:
            raise MapsError("Non conosco l'indirizzo di casa: impostalo in Integrazioni → Mappe.")
        return s["home"]
    if low in ("ufficio", "lavoro", "in ufficio", "al lavoro", "work"):
        if not s["work"]:
            raise MapsError("Non conosco l'indirizzo dell'ufficio: impostalo in Integrazioni → Mappe.")
        return s["work"]
    return p


def geocode(address: str) -> tuple[float, float, str]:
    a = address.strip()
    if a in _geo_cache:
        return _geo_cache[a]
    if key():
        r = httpx.get("https://maps.googleapis.com/maps/api/geocode/json",
                      params={"address": a, "key": key(), "language": "it", "region": "it"}, timeout=10).json()
        if r.get("status") != "OK":
            raise MapsError(f"Indirizzo non trovato: {a} ({r.get('status')})")
        g = r["results"][0]
        res = (g["geometry"]["location"]["lat"], g["geometry"]["location"]["lng"], g["formatted_address"])
    else:
        r = httpx.get("https://nominatim.openstreetmap.org/search", params={"q": a, "format": "json", "limit": 1,
                      "accept-language": "it"}, headers=UA, timeout=10).json()
        if not r:
            raise MapsError(f"Indirizzo non trovato: {a}")
        res = (float(r[0]["lat"]), float(r[0]["lon"]), r[0].get("display_name", a))
    _geo_cache[a] = res
    return res


def _fmt(seconds: float) -> str:
    m = max(1, round(seconds / 60))
    return f"{m} min" if m < 60 else f"{m // 60} h {m % 60:02d} min"


def route(origin: str, destination: str, mode: str = "", depart: datetime | None = None) -> dict:
    """Restituisce durata (s), durata senza traffico, distanza (m) e link a Google Maps."""
    mode = mode if mode in MODES else settings()["mode"]
    o, d = _resolve_alias(origin), _resolve_alias(destination)
    ck = f"{o}|{d}|{mode}|{(depart or datetime.now()).strftime('%Y%m%d%H')}{(depart or datetime.now()).minute // 15}"
    if ck in _route_cache and time.time() - _route_cache[ck][0] < 600:
        return _route_cache[ck][1]
    link = (f"https://www.google.com/maps/dir/?api=1&origin={quote_plus(o)}&destination={quote_plus(d)}"
            f"&travelmode={GMAPS_MODE[mode]}")
    if key():
        body: dict = {"origin": {"address": o}, "destination": {"address": d}, "travelMode": MODES[mode],
                      "languageCode": "it", "regionCode": "it", "units": "METRIC"}
        if mode in ("drive", "moto"):
            body["routingPreference"] = "TRAFFIC_AWARE"
        if depart and depart > datetime.now(tz()) + timedelta(minutes=1):
            body["departureTime"] = depart.astimezone(tz()).isoformat()
        r = httpx.post("https://routes.googleapis.com/directions/v2:computeRoutes", json=body, timeout=15, headers={
            "X-Goog-Api-Key": key(), "X-Goog-FieldMask": "routes.duration,routes.staticDuration,routes.distanceMeters"})
        data = r.json()
        if r.status_code != 200 or not data.get("routes"):
            msg = (data.get("error") or {}).get("message", "") if isinstance(data, dict) else ""
            raise MapsError(f"Percorso non trovato ({msg or r.status_code})")
        rt = data["routes"][0]
        dur = float(rt["duration"].rstrip("s"))
        static = float(rt.get("staticDuration", rt["duration"]).rstrip("s"))
        out = {"seconds": dur, "no_traffic": static, "meters": rt.get("distanceMeters", 0), "traffic": mode in ("drive", "moto")}
    else:
        la1, lo1, _ = geocode(o)
        la2, lo2, _ = geocode(d)
        profile = {"walk": "foot", "bike": "bike"}.get(mode, "car")
        base = "https://router.project-osrm.org" if profile == "car" else "https://routing.openstreetmap.de/routed-" + profile
        r = httpx.get(f"{base}/route/v1/{'driving' if profile == 'car' else profile}/{lo1},{la1};{lo2},{la2}",
                      params={"overview": "false"}, headers=UA, timeout=15).json()
        if r.get("code") != "Ok":
            raise MapsError("Percorso non trovato")
        rt = r["routes"][0]
        dur = float(rt["duration"])
        if mode == "transit":  # senza Google non ci sono gli orari dei mezzi: stima prudente
            dur *= 1.8
        out = {"seconds": dur, "no_traffic": dur, "meters": rt["distance"], "traffic": False}
    out.update({"origin": o, "destination": d, "mode": mode, "link": link})
    _route_cache[ck] = (time.time(), out)
    return out


def travel_text(destination: str, origin: str = "", mode: str = "", arrive_by: str = "", depart_at: str = "") -> str:
    try:
        depart = None
        if depart_at:
            depart = _parse(depart_at)
        r = route(origin, destination, mode, depart)
        if arrive_by and not depart:  # ricalcola con la partenza stimata, così il traffico è quello giusto
            target = _parse(arrive_by)
            r = route(origin, destination, mode, target - timedelta(seconds=r["seconds"]))
    except MapsError as e:
        return str(e)
    except Exception as e:  # noqa: BLE001
        return f"Non riesco a calcolare il percorso: {e}"
    km = r["meters"] / 1000
    parts = [f"{LABEL[r['mode']].capitalize()} da {r['origin']} a {r['destination']}: {_fmt(r['seconds'])}"]
    if r["traffic"]:
        extra = r["seconds"] - r["no_traffic"]
        parts.append(f"con il traffico attuale ({'+' + _fmt(extra) + ' rispetto al normale' if extra > 120 else 'traffico regolare'})")
    else:
        parts.append("(stima senza traffico)")
    text = " ".join(parts) + f", {km:.1f} km."
    if arrive_by:
        target = _parse(arrive_by)
        leave = target - timedelta(seconds=r["seconds"]) - timedelta(minutes=int(settings()["buffer_min"]))
        text += f" Per arrivare alle {target:%H:%M} parti entro le {leave:%H:%M} (margine di {settings()['buffer_min']} minuti)."
    return text + f"\nPercorso: {r['link']}"


def _parse(s: str) -> datetime:
    s = s.strip()
    now = datetime.now(tz())
    if re.fullmatch(r"\d{1,2}[:.]\d{2}", s):
        h, m = (int(x) for x in re.split(r"[:.]", s))
        return now.replace(hour=h, minute=m, second=0, microsecond=0)
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=tz())


# ---------- avviso "parti ora" ----------

async def check_leave(deliver, events: list[dict]) -> None:
    """events: appuntamenti delle prossime ore con 'id', 'title', 'start' (datetime), 'location'."""
    import asyncio

    s = settings()
    if not s["leave_alerts"] or not s["home"]:
        return
    sent = set(db.get_setting("leave_alerts_sent") or [])
    now = datetime.now(tz())
    for e in events:
        loc = (e.get("location") or "").strip()
        if not loc or ONLINE.search(loc) or e["id"] in sent:
            continue
        try:
            r = await asyncio.to_thread(route, "casa", loc, s["mode"], now)
        except Exception as exc:  # noqa: BLE001
            log.info("percorso per %s non calcolabile: %s", e["title"], exc)
            sent.add(e["id"])  # non riprovare all'infinito
            continue
        leave_at = e["start"] - timedelta(seconds=r["seconds"]) - timedelta(minutes=int(s["buffer_min"]))
        if now >= leave_at - timedelta(minutes=2):
            late = now > e["start"] - timedelta(seconds=r["seconds"])
            head = "🚗 Sei in ritardo" if late else "🚗 Parti ora"
            traffic = " con il traffico" if r["traffic"] else ""
            await deliver("alert", f"{head} per «{e['title']}» alle {e['start']:%H:%M}: {_fmt(r['seconds'])}{traffic} "
                                   f"fino a {loc}.\n{r['link']}", subject=f"Parti ora: {e['title']}")
            sent.add(e["id"])
    db.set_setting("leave_alerts_sent", list(sent)[-200:])
