"""Philips Hue via Bridge (API locale sulla tua rete di casa).

Abbinamento: premi il pulsante rotondo sul Bridge, poi "Collega" in AXEL → Integrazioni.
L'IP del Bridge viene trovato da solo (discovery Philips) oppure impostato con HUE_BRIDGE_IP nel .env.
"""
from __future__ import annotations

import os
import re

import httpx

from . import db

TIMEOUT = 6

COLORS = {
    "rosso": (255, 0, 0), "arancione": (255, 120, 0), "giallo": (255, 220, 0), "verde": (0, 255, 60),
    "azzurro": (60, 200, 255), "ciano": (0, 255, 255), "blu": (0, 60, 255), "viola": (140, 0, 255),
    "lilla": (190, 130, 255), "rosa": (255, 90, 170), "magenta": (255, 0, 200), "bianco": (255, 255, 255),
    "turchese": (0, 220, 190), "oro": (255, 180, 40),
}
WHITE_CT = {"caldo": 454, "calda": 454, "naturale": 300, "neutro": 300, "freddo": 200, "fredda": 200, "lettura": 230}


class HueError(RuntimeError):
    pass


# ---------- connessione ----------

def bridge_ip() -> str | None:
    ip = os.getenv("HUE_BRIDGE_IP", "").strip() or db.get_setting("hue_ip")
    if ip:
        return ip
    try:
        found = httpx.get("https://discovery.meethue.com/", timeout=TIMEOUT).json()
        if found:
            db.set_setting("hue_ip", found[0]["internalipaddress"])
            return found[0]["internalipaddress"]
    except Exception:  # noqa: BLE001
        pass
    return None


def status() -> dict:
    return {"linked": bool(db.get_setting("hue_user")), "ip": db.get_setting("hue_ip") or os.getenv("HUE_BRIDGE_IP")}


def pair() -> dict:
    """Da chiamare subito dopo aver premuto il pulsante del Bridge."""
    ip = bridge_ip()
    if not ip:
        raise HueError("Bridge Hue non trovato in rete. Imposta HUE_BRIDGE_IP nel .env (lo trovi nell'app Hue → "
                       "Impostazioni → Bridge Hue → info).")
    r = httpx.post(f"http://{ip}/api", json={"devicetype": "axel#mac"}, timeout=TIMEOUT).json()
    item = r[0] if isinstance(r, list) and r else {}
    if "success" in item:
        db.set_setting("hue_user", item["success"]["username"])
        db.set_setting("hue_ip", ip)
        return {"ok": True, "ip": ip}
    if item.get("error", {}).get("type") == 101:
        return {"ok": False, "need_button": True, "ip": ip}
    raise HueError(f"Risposta inattesa dal Bridge: {r}")


def unlink() -> None:
    db.del_setting("hue_user")


def _base() -> str:
    user = db.get_setting("hue_user")
    ip = bridge_ip()
    if not user or not ip:
        raise HueError("Luci Hue non collegate: premi il pulsante sul Bridge e poi Collega in Integrazioni.")
    return f"http://{ip}/api/{user}"


def _get(path: str) -> dict:
    return httpx.get(_base() + path, timeout=TIMEOUT).json()


def _put(path: str, body: dict) -> list:
    return httpx.put(_base() + path, json=body, timeout=TIMEOUT).json()


# ---------- conversioni ----------

def _rgb_to_xy(r: int, g: int, b: int) -> list[float]:
    def lin(c: float) -> float:
        c /= 255
        return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92

    R, G, B = lin(r), lin(g), lin(b)
    X = R * 0.664511 + G * 0.154324 + B * 0.162028
    Y = R * 0.283881 + G * 0.668433 + B * 0.047685
    Z = R * 0.000088 + G * 0.072310 + B * 0.986039
    s = X + Y + Z
    return [round(X / s, 4), round(Y / s, 4)] if s else [0.3227, 0.329]


def _color_state(color: str) -> dict:
    c = color.strip().lower()
    if c in WHITE_CT:
        return {"ct": WHITE_CT[c]}
    if c in COLORS:
        return {"xy": _rgb_to_xy(*COLORS[c])}
    m = re.fullmatch(r"#?([0-9a-f]{6})", c)
    if m:
        h = m.group(1)
        return {"xy": _rgb_to_xy(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))}
    raise HueError(f"Colore non riconosciuto: {color}. Prova: {', '.join(list(COLORS)[:8])}, caldo, freddo…")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


# ---------- funzioni usate dagli strumenti ----------

def overview() -> str:
    groups = _get("/groups")
    lights = _get("/lights")
    lines = []
    for gid, g in groups.items():
        if g.get("type") not in ("Room", "Zone"):
            continue
        st = g.get("state", {})
        on = "accesa" if st.get("any_on") else "spenta"
        names = [lights[i]["name"] for i in g.get("lights", []) if i in lights]
        lines.append(f"- {g['name']} ({g['type'] == 'Room' and 'stanza' or 'zona'}): {on} — luci: {', '.join(names)}")
    for lid, l in lights.items():
        st = l.get("state", {})
        if st.get("on"):
            bri = round(st.get("bri", 0) / 254 * 100)
            lines.append(f"  · {l['name']} accesa al {bri}%{'' if st.get('reachable', True) else ' (non raggiungibile)'}")
    return "\n".join(lines) or "Nessuna luce trovata sul Bridge."


def _resolve(target: str) -> tuple[str, str]:
    """Restituisce ('group', id) o ('light', id) partendo dal nome detto a voce."""
    t = _norm(target)
    if t in ("", "tutte", "tutto", "tutte le luci", "casa", "ovunque"):
        return "group", "0"
    groups = _get("/groups")
    for gid, g in groups.items():
        if _norm(g["name"]) == t:
            return "group", gid
    lights = _get("/lights")
    for lid, l in lights.items():
        if _norm(l["name"]) == t:
            return "light", lid
    for gid, g in groups.items():  # corrispondenza parziale
        if t in _norm(g["name"]) or _norm(g["name"]) in t:
            return "group", gid
    for lid, l in lights.items():
        if t in _norm(l["name"]) or _norm(l["name"]) in t:
            return "light", lid
    raise HueError(f"Non trovo «{target}» tra stanze e luci. " + overview())


def set_lights(target: str = "tutte", on: bool | None = None, brightness: int | None = None,
               color: str = "", transition_s: float = 0.4) -> str:
    kind, ident = _resolve(target)
    body: dict = {"transitiontime": int(transition_s * 10)}
    if on is not None:
        body["on"] = on
    if brightness is not None:
        b = max(0, min(100, int(brightness)))
        if b == 0:
            body["on"] = False
        else:
            body["on"] = True
            body["bri"] = max(1, round(b / 100 * 254))
    if color:
        body.update(_color_state(color))
        body["on"] = True
    path = f"/groups/{ident}/action" if kind == "group" else f"/lights/{ident}/state"
    res = _put(path, body)
    errors = [e["error"]["description"] for e in res if isinstance(e, dict) and "error" in e]
    if errors and len(errors) == len(res):
        raise HueError("; ".join(errors))
    label = "tutte le luci" if ident == "0" and kind == "group" else target
    parts = []
    if body.get("on") is False:
        parts.append("spente")
    elif "bri" in body:
        parts.append(f"al {brightness}%")
    elif body.get("on"):
        parts.append("accese")
    if color:
        parts.append(f"colore {color}")
    return f"Fatto: {label} {' e '.join(parts) or 'aggiornate'}."


def scenes(room: str = "") -> str:
    sc = _get("/scenes")
    groups = _get("/groups")
    out = []
    for sid, s in sc.items():
        gname = groups.get(s.get("group", ""), {}).get("name", "")
        if room and _norm(room) not in _norm(gname):
            continue
        out.append(f"- {s['name']}" + (f" ({gname})" if gname else ""))
    return "\n".join(sorted(set(out))) or "Nessuna scena."


def activate_scene(name: str, room: str = "") -> str:
    sc = _get("/scenes")
    groups = _get("/groups")
    cand = []
    for sid, s in sc.items():
        gid = s.get("group")
        gname = groups.get(gid or "", {}).get("name", "")
        if _norm(name) in _norm(s["name"]) and (not room or _norm(room) in _norm(gname)):
            cand.append((sid, s, gid, gname))
    if not cand:
        raise HueError(f"Scena «{name}» non trovata. Scene disponibili:\n{scenes(room)}")
    sid, s, gid, gname = cand[0]
    _put(f"/groups/{gid or '0'}/action", {"scene": sid})
    return f"Scena «{s['name']}» attivata" + (f" in {gname}" if gname else "") + "."
