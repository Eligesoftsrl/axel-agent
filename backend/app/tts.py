"""Voce di AXEL generata dal backend (per l'app e per i vocali di Telegram).

Motori:
- google:<voce>  Google Cloud Text-to-Speech, voci neurali anche maschili (es. it-IT-Chirp3-HD-Charon).
                  Serve una chiave API con "Cloud Text-to-Speech API" abilitata: GOOGLE_TTS_API_KEY nel .env
                  (va bene anche la stessa chiave delle Mappe, GOOGLE_MAPS_API_KEY, se ha questa API abilitata).
                  Quota gratuita mensile: 1 milione di caratteri per Chirp 3 HD, 4 milioni per WaveNet.
- mac:<voce>     voci di macOS (comando `say`), gratis e offline. Le voci "Premium/Enhanced" (es. Luca) si
                  scaricano da Impostazioni di Sistema → Accessibilità → Contenuti letti → Voce di sistema.
Le frasi già sintetizzate restano in cache (in memoria) per non consumare quota.
"""
from __future__ import annotations

import base64
import hashlib
import io
import os
from collections import OrderedDict
import platform
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

PREFERRED = ["Luca (Premium)", "Luca (Enhanced)", "Luca", "Paola (Premium)", "Paola (Enhanced)", "Alice (Premium)",
             "Alice (Enhanced)", "Federica (Premium)", "Federica (Enhanced)", "Alice", "Federica", "Paola"]


GOOGLE_DEFAULT = "it-IT-Chirp3-HD-Charon"
_cache: "OrderedDict[str, tuple[bytes, str]]" = OrderedDict()


class TTSError(RuntimeError):
    pass


def google_key() -> str:
    return (os.getenv("GOOGLE_TTS_API_KEY") or os.getenv("GOOGLE_MAPS_API_KEY") or "").strip()


def _cache_get(k: str):
    if k in _cache:
        _cache.move_to_end(k)
        return _cache[k]
    return None


def _cache_put(k: str, v: tuple[bytes, str]) -> None:
    _cache[k] = v
    if len(_cache) > 300:
        _cache.popitem(last=False)


def google_voices() -> list[dict]:
    """Voci italiane di Google Cloud (nome, genere, tipo)."""
    import httpx

    if not google_key():
        return []
    r = httpx.get("https://texttospeech.googleapis.com/v1/voices", params={"languageCode": "it-IT", "key": google_key()}, timeout=15)
    if r.status_code != 200:
        raise TTSError(_google_error(r))
    out = []
    for v in r.json().get("voices", []):
        name = v["name"]
        kind = next((k for k in ("Chirp3-HD", "Chirp-HD", "Studio", "Neural2", "Wavenet", "Standard", "Polyglot") if k in name), "altro")
        out.append({"name": name, "gender": v.get("ssmlGender", "").lower(), "type": kind})
    order = {"Chirp3-HD": 0, "Neural2": 1, "Wavenet": 2, "Studio": 3, "Chirp-HD": 4, "Standard": 5}
    out.sort(key=lambda v: (v["gender"] != "male", order.get(v["type"], 9), v["name"]))
    return out


def _google_error(r) -> str:
    try:
        msg = r.json().get("error", {}).get("message", "")
    except Exception:  # noqa: BLE001
        msg = r.text[:200]
    if "has not been used" in msg or "disabled" in msg:
        return "Abilita 'Cloud Text-to-Speech API' nel tuo progetto Google Cloud (vedi README)."
    if r.status_code in (401, 403):
        return f"Chiave Google non valida o non abilitata per Text-to-Speech: {msg}"
    return f"Google Text-to-Speech: {msg or r.status_code}"


def synth_google(text: str, voice: str = "", rate: float = 1.0, encoding: str = "MP3") -> bytes:
    import httpx

    if not google_key():
        raise TTSError("Manca la chiave Google: aggiungi GOOGLE_TTS_API_KEY nel .env (vedi README).")
    voice = voice or GOOGLE_DEFAULT
    k = hashlib.sha1(f"g|{voice}|{rate}|{encoding}|{text}".encode()).hexdigest()
    hit = _cache_get(k)
    if hit:
        return hit[0]
    body = {"input": {"text": text[:4500]}, "voice": {"languageCode": "-".join(voice.split("-")[:2]), "name": voice},
            "audioConfig": {"audioEncoding": encoding, "speakingRate": max(0.5, min(2.0, rate))}}
    r = httpx.post("https://texttospeech.googleapis.com/v1/text:synthesize", params={"key": google_key()}, json=body, timeout=30)
    if r.status_code != 200:
        raise TTSError(_google_error(r))
    audio = base64.b64decode(r.json()["audioContent"])
    _cache_put(k, (audio, encoding))
    return audio


def synth_mac_wav(text: str, voice: str = "", rate: float = 1.0) -> bytes:
    """Voce del Mac in WAV (riproducibile dal browser)."""
    if not available():
        raise TTSError("Le voci del Mac funzionano solo se il backend gira su macOS.")
    voice = voice or pick_voice() or ""
    k = hashlib.sha1(f"m|{voice}|{rate}|{text}".encode()).hexdigest()
    hit = _cache_get(k)
    if hit:
        return hit[0]
    with tempfile.TemporaryDirectory() as d:
        aiff, wav = Path(d) / "a.aiff", Path(d) / "a.wav"
        cmd = ["say", "-o", str(aiff), "-r", str(int(185 * rate))] + (["-v", voice] if voice else []) + [clean_for_speech(text)]
        subprocess.run(cmd, check=True, timeout=60, capture_output=True)
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@24000", str(aiff), str(wav)], check=True, timeout=60,
                       capture_output=True)
        audio = wav.read_bytes()
    _cache_put(k, (audio, "wav"))
    return audio


def synth_for_app(voice_spec: str, text: str, rate: float = 1.0) -> tuple[bytes, str]:
    """voice_spec: 'google:<nome>' o 'mac:<nome>'. Restituisce (audio, content-type)."""
    engine, _, name = voice_spec.partition(":")
    text = clean_for_speech(text)
    if not text:
        raise TTSError("testo vuoto")
    if engine == "google":
        return synth_google(text, name, rate, "MP3"), "audio/mpeg"
    if engine == "mac":
        return synth_mac_wav(text, name, rate), "audio/wav"
    raise TTSError(f"motore sconosciuto: {engine}")


def available() -> bool:
    return platform.system() == "Darwin" and bool(shutil.which("say"))


def italian_voices() -> list[str]:
    if not available():
        return []
    out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=10).stdout
    voices = []
    for line in out.splitlines():
        m = re.match(r"^(.+?)\s{2,}(\w\w_\w\w)", line)
        if m and m.group(2).startswith("it_"):
            voices.append(m.group(1).strip())
    return voices


def pick_voice() -> str | None:
    env = os.getenv("MAC_VOICE", "").strip()
    if env:
        return env
    its = italian_voices()
    for v in PREFERRED:
        if v in its:
            return v
    return its[0] if its else None


def clean_for_speech(text: str) -> str:
    t = re.sub(r"https?://\S+", "link", text)
    t = re.sub(r"[*_`#>|]+", "", t)
    t = re.sub(r"^\s*[-•]\s*", "", t, flags=re.M)
    return re.sub(r"\s+", " ", t).strip()[:2500]


def synthesize(text: str, voice_spec: str = "") -> tuple[bytes, str]:
    """Restituisce (audio, tipo) con tipo 'voice' (ogg/opus) o 'audio' (m4a)."""
    if voice_spec.startswith("google:") and google_key():
        try:
            return synth_google(clean_for_speech(text), voice_spec.split(":", 1)[1], 1.0, "OGG_OPUS"), "voice"
        except TTSError:
            pass  # ripiega sulla voce del Mac
    if voice_spec.startswith("mac:"):
        os.environ.setdefault("MAC_VOICE", voice_spec.split(":", 1)[1])
    if not available():
        raise RuntimeError("La voce funziona solo sul Mac (comando say).")
    voice = pick_voice()
    with tempfile.TemporaryDirectory() as d:
        aiff = Path(d) / "axel.aiff"
        cmd = ["say", "-o", str(aiff)] + (["-v", voice] if voice else []) + [clean_for_speech(text)]
        subprocess.run(cmd, check=True, timeout=120, capture_output=True)
        try:
            return _to_ogg_opus(aiff.read_bytes()), "voice"
        except Exception:  # noqa: BLE001
            m4a = Path(d) / "axel.m4a"
            subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", str(aiff), str(m4a)], check=True, timeout=60,
                           capture_output=True)
            return m4a.read_bytes(), "audio"


def _to_ogg_opus(data: bytes) -> bytes:
    import av

    out = io.BytesIO()
    with av.open(io.BytesIO(data)) as src, av.open(out, "w", format="ogg") as dst:
        stream = dst.add_stream("libopus", rate=48000)
        stream.layout = "mono"
        res = av.AudioResampler(format="s16", layout="mono", rate=48000)
        for frame in src.decode(audio=0):
            for f in res.resample(frame):
                for p in stream.encode(f):
                    dst.mux(p)
        for f in res.resample(None):
            for p in stream.encode(f):
                dst.mux(p)
        for p in stream.encode(None):
            dst.mux(p)
    return out.getvalue()
