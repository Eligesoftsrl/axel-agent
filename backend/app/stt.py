"""Riconoscimento vocale locale con Whisper: niente audio inviato a Google, nomi propri riconosciuti meglio.

Motori (scelti in automatico, il primo disponibile):
  - mlx-whisper   → Mac con chip Apple (M1/M2/M3/M4): velocissimo, modello predefinito large-v3-turbo
  - faster-whisper → qualsiasi computer (CPU), modello predefinito "small"
Installazione: `uv pip install -r requirements-voice.txt` (vedi README, "Voce locale").
Il modello si scarica da Hugging Face al primo utilizzo (qualche centinaio di MB), poi resta in cache.
Variabili opzionali nel .env: WHISPER_ENGINE (mlx|faster), WHISPER_MODEL (es. small, medium, large-v3-turbo).
"""
from __future__ import annotations

import io
import logging
import os
import platform
import re
import threading
import time
import wave
from collections import deque

from . import db

log = logging.getLogger("axel.stt")


class STTUnavailable(RuntimeError):
    pass


_lock = threading.Lock()
_model = None
_engine: str | None = None
_model_name: str | None = None
_load_error: str | None = None
_timings: deque = deque(maxlen=12)  # ms delle ultime trascrizioni

# Qualità: "fast" = modello small (risposta in pochi decimi di secondo), "accurate" = large-v3-turbo (più preciso, più lento)
QUALITY_MODELS = {"fast": "small", "accurate": "large-v3-turbo"}

MLX_MODELS = {
    "tiny": "mlx-community/whisper-tiny", "base": "mlx-community/whisper-base-mlx",
    "small": "mlx-community/whisper-small-mlx", "medium": "mlx-community/whisper-medium-mlx",
    "large-v3": "mlx-community/whisper-large-v3-mlx", "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    "turbo": "mlx-community/whisper-large-v3-turbo",
}

# Frasi che Whisper "inventa" sul rumore o sul silenzio (soprattutto in italiano)
HALLUCINATIONS = re.compile(
    r"(sottotitoli|amara\.org|qtss|grazie per la visione|grazie per l'ascolto|grazie a tutti per la visione|"
    r"iscriviti al canale|iscrivetevi|al prossimo video|alla prossima puntata|musica di sottofondo|\[musica\]|"
    r"^\W*(grazie|ciao|buona visione)\W*$)",
    re.I,
)


def _detect_engine() -> str | None:
    pref = os.getenv("WHISPER_ENGINE", "").strip().lower()
    order = [pref] if pref in ("mlx", "faster") else []
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        order += ["mlx", "faster"]
    else:
        order += ["faster"]
    for eng in order:
        try:
            if eng == "mlx":
                import mlx_whisper  # noqa: F401
            else:
                import faster_whisper  # noqa: F401
            return eng
        except Exception:  # noqa: BLE001
            continue
    return None


def quality() -> str:
    q = db.get_setting("stt_quality") or "fast"
    return q if q in QUALITY_MODELS else "fast"


def set_quality(q: str) -> dict:
    """Cambia qualità: il modello nuovo si carica (e se serve si scarica) alla prossima frase o con warmup."""
    global _model, _model_name
    if q not in QUALITY_MODELS:
        raise ValueError("qualità non valida")
    db.set_setting("stt_quality", q)
    with _lock:
        _model, _model_name = None, None
        _timings.clear()
    return status()


def status() -> dict:
    eng = _engine or _detect_engine()
    t = list(_timings)
    return {
        "available": eng is not None,
        "engine": eng,
        "model": _model_name or _default_model(eng),
        "quality": quality(),
        "loaded": _model is not None,
        "error": _load_error,
        "last_ms": t[-1] if t else None,
        "avg_ms": int(sum(t) / len(t)) if t else None,
    }


def _default_model(eng: str | None) -> str:
    env = os.getenv("WHISPER_MODEL", "").strip()
    if env:
        return env
    return QUALITY_MODELS[quality()]


def load():
    """Carica il modello (al primo uso lo scarica). Thread-safe."""
    global _model, _engine, _model_name, _load_error
    with _lock:
        if _model is not None:
            return _model
        eng = _detect_engine()
        if not eng:
            raise STTUnavailable("Whisper non è installato: esegui `uv pip install -r requirements-voice.txt` nel backend.")
        name = _default_model(eng)
        t0 = time.time()
        try:
            if eng == "mlx":
                repo = MLX_MODELS.get(name, name)
                _model = {"repo": repo}  # mlx-whisper carica il modello alla prima trascrizione: lo scaldiamo ora
                _transcribe_mlx(_model, _silence(), "")
            else:
                from faster_whisper import WhisperModel

                _model = WhisperModel(name, device="auto", compute_type="int8", cpu_threads=max(2, (os.cpu_count() or 4) - 2))
                _transcribe_faster(_model, _silence(), "")  # riscaldamento: la prima frase vera non paga l'avvio
        except Exception as exc:  # noqa: BLE001
            _model = None
            _load_error = str(exc)
            log.exception("caricamento Whisper")
            raise STTUnavailable(f"Non riesco a caricare Whisper ({name}): {exc}") from exc
        _engine, _model_name, _load_error = eng, name, None
        log.info("Whisper pronto: %s %s in %.1fs", eng, name, time.time() - t0)
        return _model


def _silence():
    import numpy as np

    return np.zeros(16000, dtype=np.float32)


def _decode_wav(data: bytes):
    import numpy as np

    with wave.open(io.BytesIO(data)) as w:
        sr, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        frames = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError("serve audio WAV a 16 bit")
    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        audio = audio.reshape(-1, ch).mean(axis=1)
    if sr != 16000:  # ricampionamento lineare (il frontend manda già 16 kHz)
        n = int(len(audio) * 16000 / sr)
        audio = np.interp(np.linspace(0, len(audio), n, endpoint=False), np.arange(len(audio)), audio).astype(np.float32)
    return audio


def _prompt() -> str:
    vocab = [w for w in (db.get_setting("vocabulary") or [])][:40]
    base = "Conversazione in italiano con Axel, l'assistente personale."
    return base + (" Nomi: " + ", ".join(vocab) + "." if vocab else "")


def _transcribe_mlx(model: dict, audio, prompt: str) -> dict:
    import mlx_whisper

    r = mlx_whisper.transcribe(audio, path_or_hf_repo=model["repo"], language="it", initial_prompt=prompt or None,
                               condition_on_previous_text=False, temperature=0.0)
    segs = r.get("segments") or []
    return {
        "text": (r.get("text") or "").strip(),
        "no_speech": max((s.get("no_speech_prob", 0) for s in segs), default=0.0),
        "logprob": min((s.get("avg_logprob", 0) for s in segs), default=0.0),
    }


def _transcribe_faster(model, audio, prompt: str) -> dict:
    segments, _info = model.transcribe(audio, language="it", beam_size=1, initial_prompt=prompt or None,
                                       condition_on_previous_text=False, without_timestamps=True, vad_filter=False)
    segs = list(segments)
    return {
        "text": " ".join(s.text.strip() for s in segs).strip(),
        "no_speech": max((s.no_speech_prob for s in segs), default=0.0),
        "logprob": min((s.avg_logprob for s in segs), default=0.0),
    }


def clean(result: dict, duration: float) -> dict:
    """Scarta le trascrizioni inaffidabili: rumore, silenzio, allucinazioni tipiche di Whisper."""
    text = re.sub(r"\s+", " ", result.get("text", "")).strip()
    reason = ""
    if duration < 0.35:
        reason = "troppo breve"
    elif not re.search(r"[a-zà-ù]", text, re.I):
        reason = "vuoto"
    elif HALLUCINATIONS.search(text) and len(text.split()) <= 8:
        reason = "allucinazione"
    elif result.get("no_speech", 0) > 0.6 and result.get("logprob", 0) < -0.8:
        reason = "rumore"
    elif result.get("logprob", 0) < -1.4:
        reason = "incerto"
    confidence = max(0.0, min(1.0, 1.0 + float(result.get("logprob", 0)) / 1.5))
    return {"text": "" if reason else text, "raw": text, "confidence": round(confidence, 2),
            "discarded": reason or None, "duration": round(duration, 2)}


def to_wav16k(data: bytes) -> bytes:
    """Qualsiasi audio (ogg/opus di Telegram, m4a, mp3…) → WAV 16 kHz mono 16 bit.

    Usa PyAV (pacchetto 'av', include ffmpeg) oppure, se manca, ffmpeg installato sul Mac.
    """
    try:
        import av  # noqa: F401

        return _to_wav_av(data)
    except ImportError:
        pass
    import shutil
    import subprocess

    if not shutil.which("ffmpeg"):
        raise STTUnavailable("Per i vocali serve il pacchetto 'av' (uv pip install av) oppure ffmpeg (brew install ffmpeg).")
    p = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-ar", "16000", "-ac", "1", "-f", "wav", "pipe:1"],
                       input=data, capture_output=True, timeout=60)
    if p.returncode:
        raise ValueError(p.stderr.decode(errors="ignore")[:200])
    return p.stdout


def _to_wav_av(data: bytes) -> bytes:
    import av
    import numpy as np

    pcm = []
    with av.open(io.BytesIO(data)) as c:
        res = av.AudioResampler(format="s16", layout="mono", rate=16000)
        for frame in c.decode(audio=0):
            for f in res.resample(frame):
                pcm.append(f.to_ndarray().reshape(-1))
        for f in res.resample(None):
            pcm.append(f.to_ndarray().reshape(-1))
    samples = np.concatenate(pcm).astype(np.int16) if pcm else np.zeros(0, dtype=np.int16)
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(samples.tobytes())
    return out.getvalue()


def transcribe_any(data: bytes) -> dict:
    """Trascrive un file audio qualsiasi (es. nota vocale), senza i filtri per frasi brevi del microfono."""
    model = load()
    audio = _decode_wav(to_wav16k(data))
    duration = len(audio) / 16000
    t0 = time.time()
    with _lock:
        r = _transcribe_mlx(model, audio, _prompt()) if _engine == "mlx" else _transcribe_faster(model, audio, _prompt())
    text = re.sub(r"\s+", " ", r.get("text", "")).strip()
    if HALLUCINATIONS.search(text) and len(text.split()) <= 8:
        text = ""
    return {"text": text, "duration": round(duration, 1), "ms": int((time.time() - t0) * 1000)}


def transcribe(wav_bytes: bytes) -> dict:
    model = load()
    try:
        audio = _decode_wav(wav_bytes)
    except Exception as exc:  # noqa: BLE001
        return {"text": "", "raw": "", "confidence": 0, "discarded": f"audio non valido: {exc}", "duration": 0}
    duration = len(audio) / 16000
    if duration > 30:
        audio = audio[: 30 * 16000]
    t0 = time.time()
    with _lock:
        r = _transcribe_mlx(model, audio, _prompt()) if _engine == "mlx" else _transcribe_faster(model, audio, _prompt())
    out = clean(r, duration)
    out["ms"] = int((time.time() - t0) * 1000)
    _timings.append(out["ms"])
    log.info("whisper %.1fs audio -> %d ms: %r%s", duration, out["ms"], out["raw"][:60],
             f" (scartata: {out['discarded']})" if out["discarded"] else "")
    return out
