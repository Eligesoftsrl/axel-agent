"""Spotify: cosa stai ascoltando, controllo riproduzione, ricerca e avvio di brani/playlist.

Setup: crea un'app su https://developer.spotify.com/dashboard con Redirect URI
  http://127.0.0.1:8010/api/spotify/callback
e metti SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET nel .env (vedi README).
Il controllo della riproduzione richiede Spotify Premium.
"""
from __future__ import annotations

import base64
import os
import re
import secrets
import time
from urllib.parse import urlencode

import logging

import httpx

from . import db

log = logging.getLogger("axel.spotify")

SCOPES = " ".join([
    "user-read-private",  # tipo di abbonamento (se Spotify lo fornisce)
    "user-read-playback-state", "user-modify-playback-state", "user-read-currently-playing",
    "playlist-read-private", "playlist-read-collaborative", "user-library-read", "user-read-recently-played",
])
API = "https://api.spotify.com/v1"
_states: set[str] = set()


def _client() -> tuple[str, str]:
    return os.getenv("SPOTIFY_CLIENT_ID", "").strip(), os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()


def _redirect() -> str:
    return os.getenv("SPOTIFY_REDIRECT_URI", f"http://127.0.0.1:{os.getenv('PORT', '8010')}/api/spotify/callback")


def status() -> dict:
    cid, sec = _client()
    tok = db.get_setting("spotify_token")
    return {"configured": bool(cid and sec), "connected": bool(tok), "user": db.get_setting("spotify_user")}


def auth_url() -> str:
    state = secrets.token_urlsafe(12)
    _states.add(state)
    return "https://accounts.spotify.com/authorize?" + urlencode({
        "client_id": _client()[0], "response_type": "code", "redirect_uri": _redirect(),
        "scope": SCOPES, "state": state,
    })


def _token_request(data: dict) -> dict:
    cid, sec = _client()
    basic = base64.b64encode(f"{cid}:{sec}".encode()).decode()
    r = httpx.post("https://accounts.spotify.com/api/token", data=data,
                   headers={"Authorization": f"Basic {basic}"}, timeout=15)
    r.raise_for_status()
    return r.json()


def finish_auth(code: str, state: str) -> None:
    if state not in _states:
        raise RuntimeError("stato OAuth non valido, riprova")
    _states.discard(state)
    tok = _token_request({"grant_type": "authorization_code", "code": code, "redirect_uri": _redirect()})
    tok["expires_at"] = time.time() + tok.get("expires_in", 3600) - 60
    db.set_setting("spotify_token", tok)
    try:
        me = _api("GET", "/me")
        db.set_setting("spotify_user", me.get("display_name") or me.get("id"))
        db.set_setting("spotify_product", me.get("product"))
    except Exception:  # noqa: BLE001
        pass


def diagnose() -> dict:
    """Controlla passo passo cosa non va con Spotify e restituisce un rapporto leggibile."""
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str):
        checks.append({"name": name, "ok": ok, "detail": detail})

    cid, sec = _client()
    add("Credenziali app nel .env", bool(cid and sec), "SPOTIFY_CLIENT_ID e SECRET presenti" if cid and sec else "mancano nel .env")
    if not db.get_setting("spotify_token"):
        add("Collegamento", False, "Spotify non collegato: premi Collega")
        return {"checks": checks}
    try:
        me = _api("GET", "/me")
        product = me.get("product")
        db.set_setting("spotify_product", product)
        add("Account collegato", True, f"{me.get('display_name') or me.get('id')}")
        if product:
            add("Abbonamento", product == "premium",
                "Premium" if product == "premium" else f"risulta «{product}»: il controllo della riproduzione richiede Premium")
    except SpotifyError as e:
        add("Account collegato", False, f"{e.status}: {e} — probabile account non aggiunto in User Management dell'app")
        return {"checks": checks}
    except Exception as e:  # noqa: BLE001
        add("Account collegato", False, str(e))
        return {"checks": checks}
    devs: list = []
    try:
        devs = _api("GET", "/me/player/devices").get("devices", [])
        add("Dispositivi", bool(devs), ", ".join(f"{d['name']}{' (attivo)' if d.get('is_active') else ''}" for d in devs)
            or "nessuno: apri Spotify sul Mac")
    except SpotifyError as e:
        add("Dispositivi", False, f"{e.status}: {e}")
    try:
        _api("GET", "/search", params={"q": "queen", "type": "track", "limit": 1})
        add("Ricerca brani", True, "ok")
    except SpotifyError as e:
        add("Ricerca brani", False, f"{e.status}: {e}")
    try:
        p = _api("GET", "/me/player")
        if p and p.get("device"):
            # comando innocuo: rimette lo stesso volume
            vol = (p.get("device") or {}).get("volume_percent")
            if vol is not None:
                _api("PUT", "/me/player/volume", params={"volume_percent": vol})
            add("Controllo riproduzione", True, "Spotify accetta i comandi di AXEL")
        elif devs:
            # niente in riproduzione: seleziona il Mac come dispositivo senza far partire l'audio
            target = next((d for d in devs if d.get("type") == "Computer"), devs[0])
            _api("PUT", "/me/player", json={"device_ids": [target["id"]], "play": False})
            add("Controllo riproduzione", True, f"Spotify accetta i comandi di AXEL (provato su {target['name']}, senza audio)")
        else:
            add("Controllo riproduzione", False, "nessun dispositivo: apri Spotify sul Mac e riprova")
    except SpotifyError as e:
        hint = ""
        if e.reason == "PREMIUM_REQUIRED" or e.status == 403:
            hint = (" — se il tuo account è Premium: l'account che ha CREATO l'app su developer.spotify.com deve essere "
                    "Premium (regola Spotify dal febbraio 2026) e il tuo account deve essere in User Management")
        add("Controllo riproduzione", False, f"{e.status} {e.reason}: {e}{hint}")
    return {"checks": checks}


def disconnect() -> None:
    for k in ("spotify_token", "spotify_user", "spotify_product"):
        db.del_setting(k)


def _access() -> str:
    tok = db.get_setting("spotify_token")
    if not tok:
        raise RuntimeError("Spotify non collegato. Collegalo da Integrazioni.")
    if time.time() > tok.get("expires_at", 0):
        new = _token_request({"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]})
        tok.update(new)
        tok["expires_at"] = time.time() + new.get("expires_in", 3600) - 60
        db.set_setting("spotify_token", tok)
    return tok["access_token"]


class SpotifyError(RuntimeError):
    def __init__(self, status: int, reason: str, message: str):
        super().__init__(message)
        self.status, self.reason = status, reason


def _api(method: str, path: str, params: dict | None = None, json: dict | None = None) -> dict:
    r = httpx.request(method, API + path, params=params, json=json, timeout=15,
                      headers={"Authorization": f"Bearer {_access()}"})
    if r.status_code == 204 or not r.content:
        return {}
    data = r.json()
    if r.status_code >= 400:
        err = data.get("error", {}) if isinstance(data, dict) else {}
        raise SpotifyError(r.status_code, err.get("reason", ""), err.get("message", r.text))
    return data


_ERROR_PREFIXES = ("Spotify dice", "Il tuo account", "Nessun dispositivo", "Spotify non permette", "Permessi Spotify",
                   "Errore Spotify", "Azione sconosciuta", "Non riesco", "Nessun dispositivo Spotify")


def is_error(text: str) -> bool:
    return text.startswith(_ERROR_PREFIXES)


def _friendly(exc: SpotifyError) -> str:
    """Messaggio chiaro per l'utente, basato sul motivo vero restituito da Spotify."""
    msg = str(exc)
    low = msg.lower()
    log.warning("Spotify %s %s: %s", exc.status, exc.reason, msg)
    if exc.reason == "PREMIUM_REQUIRED":
        return ("Spotify dice che serve Premium. Se il tuo account è Premium, il problema è l'app sviluppatore: "
                "dal febbraio 2026 deve essere Premium anche l'account che l'ha creata su developer.spotify.com. "
                "Apri Integrazioni → Spotify → Diagnostica.")
    if exc.status == 403 and ("registered" in low or "not been registered" in low or "user may not" in low):
        return ("Il tuo account Spotify non è abilitato nell'app sviluppatore: su developer.spotify.com apri l'app → "
                "Settings → User Management e aggiungi il tuo nome ed email Spotify, poi ricollega Spotify.")
    if exc.reason == "NO_ACTIVE_DEVICE" or exc.status == 404:
        return "Nessun dispositivo Spotify attivo: apri Spotify sul Mac o sul telefono e riprova."
    if exc.reason in ("UNKNOWN", "") and "restriction" in low:
        return "Spotify non permette questa azione adesso (es. è già in pausa, o non c'è un brano precedente)."
    if exc.status == 401 or "scope" in low:
        return "Permessi Spotify scaduti o incompleti: scollega e ricollega Spotify da Integrazioni."
    return f"Errore Spotify ({exc.status}{' ' + exc.reason if exc.reason else ''}): {msg}"


def _launch_mac_app() -> bool:
    """Apre l'app Spotify sul Mac (in background) se è chiusa. True se è stata lanciata."""
    import platform
    import subprocess

    if platform.system() != "Darwin":
        return False
    try:
        subprocess.run(["open", "-g", "-a", "Spotify"], capture_output=True, timeout=10, check=True)
        return True
    except Exception:  # noqa: BLE001
        return False


def _ensure_device() -> str | None:
    """Trova un dispositivo su cui suonare.

    Se non c'è un dispositivo attivo trasferisce la riproduzione al primo disponibile (il Mac per primo);
    se Spotify è chiuso ovunque, apre l'app sul Mac e aspetta che si registri (fino a ~15 s).
    """
    devs = _api("GET", "/me/player/devices").get("devices", [])
    if not devs and _launch_mac_app():
        for _ in range(15):
            time.sleep(1)
            devs = _api("GET", "/me/player/devices").get("devices", [])
            if devs:
                time.sleep(1.0)  # l'app appena aperta ha bisogno di un attimo prima di accettare comandi
                break
    if not devs:
        return None
    active = next((d for d in devs if d.get("is_active")), None)
    if active:
        return active["id"]
    target = next((d for d in devs if d.get("type") == "Computer"), devs[0])
    _api("PUT", "/me/player", json={"device_ids": [target["id"]], "play": False})
    time.sleep(0.6)
    return target["id"]


# ---------- funzioni usate dagli strumenti ----------

def state() -> dict | None:
    """Stato strutturato per il widget olografico (copertina inclusa). None se non suona niente."""
    p = _api("GET", "/me/player", params={"additional_types": "episode"})
    if not p or not p.get("item"):
        return None
    it = p["item"]
    album = it.get("album") or {}
    images = album.get("images") or it.get("images") or (it.get("show") or {}).get("images") or []
    art = images[0]["url"] if images else ""
    artists = ", ".join(a["name"] for a in it.get("artists", [])) or (it.get("show") or {}).get("name", "")
    dev = p.get("device") or {}
    return {
        "track": it.get("name", ""),
        "artists": artists,
        "album": album.get("name", ""),
        "art": art,
        "url": (it.get("external_urls") or {}).get("spotify", ""),
        "uri": it.get("uri", ""),
        "context_uri": (p.get("context") or {}).get("uri", ""),
        "is_playing": bool(p.get("is_playing")),
        "progress_ms": int(p.get("progress_ms") or 0),
        "duration_ms": int(it.get("duration_ms") or 0),
        "device": dev.get("name", ""),
        "volume": dev.get("volume_percent"),
        "shuffle": bool(p.get("shuffle_state")),
    }


def now_playing() -> str:
    p = _api("GET", "/me/player")
    if not p or not p.get("item"):
        return "In questo momento non sta suonando niente su Spotify."
    it = p["item"]
    artists = ", ".join(a["name"] for a in it.get("artists", [])) or it.get("show", {}).get("name", "")
    state = "in riproduzione" if p.get("is_playing") else "in pausa"
    pos = p.get("progress_ms", 0) // 1000
    dur = it.get("duration_ms", 0) // 1000
    return (f"{it['name']} — {artists} ({it.get('album', {}).get('name', '')}), {state} "
            f"{pos // 60}:{pos % 60:02d}/{dur // 60}:{dur % 60:02d} su {p.get('device', {}).get('name', '?')}, "
            f"volume {p.get('device', {}).get('volume_percent', '?')}%.")


def _play_retry(dev: str | None, body: dict | None) -> None:
    """Avvia la riproduzione; se l'app appena aperta non è ancora pronta riprova un paio di volte."""
    for attempt in range(3):
        try:
            _api("PUT", "/me/player/play", params={"device_id": dev} if dev else None, json=body)
            return
        except SpotifyError as e:
            if e.status != 404 and e.reason != "NO_ACTIVE_DEVICE" or attempt == 2:
                raise
            time.sleep(1.5)


def control(action: str, value: int | None = None) -> str:
    try:
        if action in ("play", "resume"):
            dev = _ensure_device()
            _play_retry(dev, None)
            return "Riproduzione ripresa."
        if action == "pause":
            _api("PUT", "/me/player/pause")
            return "In pausa."
        if action == "next":
            _api("POST", "/me/player/next")
            return "Brano successivo."
        if action == "previous":
            _api("POST", "/me/player/previous")
            return "Brano precedente."
        if action == "volume":
            v = max(0, min(100, int(value if value is not None else 50)))
            _api("PUT", "/me/player/volume", params={"volume_percent": v})
            return f"Volume al {v}%."
        if action in ("shuffle_on", "shuffle_off"):
            _api("PUT", "/me/player/shuffle", params={"state": "true" if action == "shuffle_on" else "false"})
            return "Riproduzione casuale " + ("attiva." if action == "shuffle_on" else "disattivata.")
        return f"Azione sconosciuta: {action}"
    except SpotifyError as e:
        return _friendly(e)


def _norm(t: str) -> str:
    import unicodedata

    t = unicodedata.normalize("NFD", t.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"\b(the|i|gli|le|la|il|lo)\b", " ", t)
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def _sim(a: str, b: str) -> float:
    from difflib import SequenceMatcher

    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.85
    return SequenceMatcher(None, a, b).ratio()


def _search(q: str, kind: str, limit: int = 10) -> list[dict]:
    res = _api("GET", "/search", params={"q": q, "type": kind, "limit": limit, "market": "from_token"})
    return [i for i in res.get(f"{kind}s", {}).get("items", []) if i]


def _best_artist(name: str) -> dict | None:
    """L'artista con il nome più simile (non il primo risultato, che a volte è un altro)."""
    items = _search(name, "artist")
    if not items:
        return None
    scored = sorted(items, key=lambda a: _sim(name, a["name"]), reverse=True)
    best = scored[0]
    return best if _sim(name, best["name"]) >= 0.6 else None


def _artist_tracks(artist: dict) -> list[str]:
    """Brani dell'artista (dalla ricerca filtrata: gli endpoint 'top tracks' non sono più disponibili)."""
    items = _search(f'artist:"{artist["name"]}"', "track")
    uris = [t["uri"] for t in items if any(a.get("id") == artist["id"] for a in t.get("artists", []))]
    return uris


def resolve(query: str, kind: str = "track", artist: str = "") -> tuple[dict, str]:
    """Trova cosa suonare. Restituisce (corpo della richiesta play, etichetta leggibile)."""
    q = query.strip()
    if kind == "playlist":  # prima le playlist dell'utente
        mine = _api("GET", "/me/playlists", params={"limit": 50}).get("items", [])
        hit = max((p for p in mine if p), key=lambda p: _sim(q, p["name"]), default=None)
        if hit and _sim(q, hit["name"]) >= 0.7:
            return {"context_uri": hit["uri"]}, f"la tua playlist «{hit['name']}»"
        items = _search(q, "playlist")
        if not items:
            raise LookupError(q)
        return {"context_uri": items[0]["uri"]}, f"la playlist «{items[0]['name']}»"

    if kind == "artist":
        a = _best_artist(artist or q)
        if not a:
            raise LookupError(artist or q)
        uris = _artist_tracks(a)
        if len(uris) >= 3:  # una scaletta dei suoi brani più noti
            return {"uris": uris}, f"un po' di {a['name']}"
        return {"context_uri": a["uri"]}, f"un po' di {a['name']}"

    if kind == "album":
        q2 = f'album:"{q}"' + (f' artist:"{artist}"' if artist else "")
        items = _search(q2, "album") or _search(f"{q} {artist}".strip(), "album")
        if not items:
            raise LookupError(q)
        best = max(items, key=lambda x: _sim(q, x["name"]) + (_sim(artist, x["artists"][0]["name"]) if artist else 0))
        who = ", ".join(x["name"] for x in best.get("artists", []))
        return {"context_uri": best["uri"]}, f"l'album «{best['name']}» di {who}"

    # brano: se il "titolo" è in realtà il nome di un artista, suona l'artista
    if not artist:
        a = _best_artist(q)
        if a and _sim(q, a["name"]) >= 0.92:
            return resolve(q, "artist")
    q2 = f'track:"{q}" artist:"{artist}"' if artist else q
    items = _search(q2, "track") or (_search(f"{q} {artist}", "track") if artist else [])
    if not items:
        raise LookupError(q)

    def score(t: dict) -> float:
        names = [x["name"] for x in t.get("artists", [])]
        full = f"{t['name']} {' '.join(names)}"
        sc = max(_sim(q, t["name"]), _sim(q, full))
        if artist:
            sc += max((_sim(artist, n) for n in names), default=0)
        return sc

    best = max(items, key=score)
    who = ", ".join(x["name"] for x in best.get("artists", []))
    return {"uris": [best["uri"]]}, f"«{best['name']}» di {who}"


last_target: set[str] = set()  # cosa abbiamo appena chiesto di suonare (per sapere quando Spotify è pronto)


def wait_state(timeout: float = 5.0, need_target: bool = False) -> dict | None:
    """Stato del player appena si è aggiornato: dopo play/cambio dispositivo Spotify impiega 1-3 secondi."""
    deadline = time.time() + timeout
    st = None
    while time.time() < deadline:
        time.sleep(0.6)
        try:
            st = state()
        except Exception:  # noqa: BLE001
            st = None
        if not st:
            continue
        if not need_target or not last_target:
            return st
        if st.get("uri") in last_target or st.get("context_uri") in last_target:
            return st
    return st


def play(query: str, kind: str = "track", artist: str = "") -> str:
    kind = kind if kind in ("track", "album", "artist", "playlist") else "track"
    try:
        try:
            body, label = resolve(query, kind, artist)
        except LookupError:
            return f"Non ho trovato niente su Spotify per «{query}»."
        log.info("spotify play %r (%s, artista %r) -> %s", query, kind, artist, label)
        dev = _ensure_device()
        if dev is None:
            return "Non riesco a raggiungere Spotify: ho provato ad aprirlo sul Mac ma non risponde. Aprilo tu e riprova."
        _play_retry(dev, body)
        global last_target
        last_target = set(body.get("uris", [])) | ({body["context_uri"]} if body.get("context_uri") else set())
        return f"Metto {label}."
    except SpotifyError as e:
        return _friendly(e)


def queue(query: str) -> str:
    try:
        res = _api("GET", "/search", params={"q": query, "type": "track", "limit": 1, "market": "from_token"})
        items = res.get("tracks", {}).get("items", [])
        if not items:
            return f"Brano non trovato: {query}"
        _api("POST", "/me/player/queue", params={"uri": items[0]["uri"]})
        return f"Aggiunto in coda: «{items[0]['name']}» di {items[0]['artists'][0]['name']}."
    except SpotifyError as e:
        return _friendly(e)


def devices() -> str:
    devs = _api("GET", "/me/player/devices").get("devices", [])
    return "\n".join(f"- {d['name']} ({d['type']}){' · attivo' if d['is_active'] else ''}" for d in devs) \
        or "Nessun dispositivo: apri Spotify su un dispositivo."


def transfer(device_name: str) -> str:
    devs = _api("GET", "/me/player/devices").get("devices", [])
    d = next((x for x in devs if device_name.lower() in x["name"].lower()), None)
    if not d:
        return "Dispositivo non trovato. " + devices()
    try:
        _api("PUT", "/me/player", json={"device_ids": [d["id"]], "play": True})
        return f"Riproduzione spostata su {d['name']}."
    except SpotifyError as e:
        return _friendly(e)


def my_playlists() -> str:
    items = _api("GET", "/me/playlists", params={"limit": 30}).get("items", [])
    def count(p: dict):  # da feb 2026 il campo "tracks" diventa "items"
        return (p.get("items") or p.get("tracks") or {}).get("total", "?")
    return "\n".join(f"- {p['name']} ({count(p)} brani)" for p in items if p) \
        or "Nessuna playlist."
