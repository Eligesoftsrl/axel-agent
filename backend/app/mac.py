"""Controllo del Mac: app, file, documenti, Note, volume, screenshot, Comandi rapidi, terminale.

Tutto passa da strumenti nativi di macOS (open, mdfind, osascript, screencapture, shortcuts).
Sicurezza:
- i percorsi sono limitati alla tua cartella Home;
- spostare, cestinare e lanciare comandi richiedono conferma (vedi actions.py);
- la prima volta macOS può chiedere permessi (Automazione per Note/Finder, Registrazione schermo
  per gli screenshot) all'app da cui avvii il backend (Terminale o VS Code).
"""
from __future__ import annotations

import base64
import os
import platform
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

HOME = Path.home()
IS_MAC = platform.system() == "Darwin"
TEXT_EXT = {".txt", ".md", ".csv", ".json", ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".html", ".css", ".xml",
            ".yml", ".yaml", ".sql", ".log", ".sh", ".ini", ".toml", ".env.example", ".kt", ".go", ".rs", ".php"}
APP_ALIASES = {
    "vscode": "Visual Studio Code", "vs code": "Visual Studio Code", "code": "Visual Studio Code",
    "chrome": "Google Chrome", "terminale": "Terminal", "terminal": "Terminal", "finder": "Finder",
    "note": "Notes", "notes": "Notes", "mail": "Mail", "calendario": "Calendar", "musica": "Music",
    "spotify": "Spotify", "safari": "Safari", "impostazioni": "System Settings", "messaggi": "Messages",
}


class MacError(RuntimeError):
    pass


def _need_mac() -> None:
    if not IS_MAC:
        raise MacError("Questa funzione è disponibile solo quando AXEL gira su macOS.")


def _run(cmd: list[str], timeout: int = 20, input_text: str | None = None) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input=input_text)
    if p.returncode != 0:
        raise MacError((p.stderr or p.stdout or f"comando fallito ({p.returncode})").strip()[:500])
    return p.stdout.strip()


def _osa(script: str, timeout: int = 20) -> str:
    return _run(["osascript", "-e", script], timeout=timeout)


def _q(s: str) -> str:
    """Stringa sicura per AppleScript."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def safe_path(p: str) -> Path:
    path = Path(os.path.expanduser(p.strip())).resolve()
    if path != HOME and HOME not in path.parents:
        raise MacError("Per sicurezza posso lavorare solo dentro la tua cartella Home.")
    return path


# ---------- app e apertura ----------

def open_app(app: str, path: str = "") -> str:
    _need_mac()
    name = APP_ALIASES.get(app.strip().lower(), app.strip())
    cmd = ["open", "-a", name]
    if path:
        cmd.append(str(safe_path(path)))
    _run(cmd)
    return f"Ho aperto {name}" + (f" su {path}" if path else "") + "."


def open_target(target: str) -> str:
    _need_mac()
    if target.startswith(("http://", "https://")):
        _run(["open", target])
        return f"Ho aperto {target}."
    p = safe_path(target)
    if not p.exists():
        raise MacError(f"Non trovo {p}")
    _run(["open", str(p)])
    return f"Ho aperto {p.name}."


def youtube(query: str = "", play: bool = False) -> str:
    """Apre YouTube: home, risultati di ricerca o direttamente il primo video."""
    _need_mac()
    from urllib.parse import quote_plus

    q = query.strip()
    if not q:
        _run(["open", "https://www.youtube.com"])
        return "Ho aperto YouTube."
    search = f"https://www.youtube.com/results?search_query={quote_plus(q)}"
    if play:
        vid = _first_video(search)
        if vid:
            _run(["open", f"https://www.youtube.com/watch?v={vid[0]}"])
            return f"Ho fatto partire su YouTube: «{vid[1]}»." if vid[1] else f"Ho fatto partire il primo video per «{q}»."
    _run(["open", search])
    return f"Ho aperto YouTube con la ricerca «{q}»."


def _first_video(search_url: str) -> tuple[str, str] | None:
    """Primo video dei risultati (senza chiave API: legge la pagina dei risultati)."""
    import re

    import httpx

    try:
        html = httpx.get(search_url, timeout=10, follow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 "
                                                "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
                                  "Accept-Language": "it-IT,it;q=0.9"}).text
    except Exception:  # noqa: BLE001
        return None
    m = re.search(r'"videoRenderer":\{"videoId":"([\w-]{11})".{0,1500}?"title":\{"runs":\[\{"text":"((?:[^"\\]|\\.)*)"', html)
    if m:
        title = m.group(2).encode().decode("unicode_escape", errors="ignore")
        try:
            title = title.encode("latin-1").decode("utf-8")
        except UnicodeError:
            pass
        return m.group(1), title
    m = re.search(r'"videoId":"([\w-]{11})"', html)
    return (m.group(1), "") if m else None


# ---------- ricerca e lettura file ----------

def find_files(query: str, kind: str = "", folder: str = "", limit: int = 15) -> str:
    _need_mac()
    root = safe_path(folder) if folder else HOME
    kinds = {
        "pdf": "com.adobe.pdf", "cartella": "public.folder", "folder": "public.folder",
        "immagine": "public.image", "image": "public.image", "word": "org.openxmlformats.wordprocessingml.document",
        "excel": "org.openxmlformats.spreadsheetml.sheet", "testo": "public.text",
    }
    q = f'kMDItemDisplayName == "*{query}*"cd'
    if kind and kind.lower() in kinds:
        q += f' && kMDItemContentTypeTree == "{kinds[kind.lower()]}"'
    out = _run(["mdfind", "-onlyin", str(root), q], timeout=25)
    paths = [p for p in out.splitlines() if p and "/Library/" not in p and "/." not in p]
    if not paths:  # ripiego: anche nel contenuto
        out = _run(["mdfind", "-onlyin", str(root), query], timeout=25)
        paths = [p for p in out.splitlines() if p and "/Library/" not in p and "/." not in p]
    if not paths:
        return f"Nessun file trovato per «{query}»."

    def mtime(p: str) -> float:
        try:
            return os.path.getmtime(p)
        except OSError:
            return 0

    paths.sort(key=mtime, reverse=True)
    lines = []
    for p in paths[:limit]:
        t = time.strftime("%d/%m/%Y", time.localtime(mtime(p)))
        lines.append(f"- {p.replace(str(HOME), '~')} (modificato {t})")
    return "\n".join(lines)


def read_file(path: str, max_chars: int = 15000) -> str:
    p = safe_path(path)
    if not p.exists() or p.is_dir():
        raise MacError(f"File non trovato: {p}")
    ext = p.suffix.lower()
    text = ""
    if ext == ".pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(p))
            text = "\n".join((pg.extract_text() or "") for pg in reader.pages[:60])
        except ImportError:
            raise MacError("Per leggere i PDF installa pypdf: uv pip install pypdf") from None
        if not text.strip():
            text = "(PDF senza testo selezionabile: probabilmente è una scansione.)"
    elif ext in (".docx", ".doc", ".rtf", ".pages", ".odt") and IS_MAC:
        text = _run(["textutil", "-convert", "txt", "-stdout", str(p)], timeout=30)
    elif ext in TEXT_EXT or p.stat().st_size < 400_000:
        text = p.read_text("utf-8", errors="replace")
    else:
        raise MacError(f"Non so leggere i file {ext}.")
    head = f"File: {str(p).replace(str(HOME), '~')}\n\n"
    return head + (text[:max_chars] + ("\n…(troncato)" if len(text) > max_chars else ""))


def list_folder(path: str = "~/Desktop") -> str:
    p = safe_path(path)
    if not p.is_dir():
        raise MacError(f"Non è una cartella: {p}")
    items = sorted(p.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)[:40]
    return "\n".join(f"- {'📁 ' if i.is_dir() else ''}{i.name}" for i in items if not i.name.startswith(".")) or "Cartella vuota."


# ---------- azioni su file (eseguite solo dopo conferma) ----------

def trash(path: str) -> str:
    _need_mac()
    p = safe_path(path)
    if not p.exists():
        raise MacError(f"Non trovo {p}")
    _osa(f'tell application "Finder" to delete POSIX file {_q(str(p))}')
    return f"{p.name} spostato nel Cestino (puoi recuperarlo da lì)."


def move(src: str, dst: str) -> str:
    s, d = safe_path(src), safe_path(dst)
    if not s.exists():
        raise MacError(f"Non trovo {s}")
    if d.is_dir():
        d = d / s.name
    if d.exists():
        raise MacError(f"Esiste già {d}")
    shutil.move(str(s), str(d))
    return f"Spostato in {str(d).replace(str(HOME), '~')}."


def run_command(command: str, cwd: str = "~") -> str:
    workdir = safe_path(cwd)
    p = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=120, cwd=str(workdir),
                       env={**os.environ, "PAGER": "cat"})
    out = (p.stdout + ("\n" + p.stderr if p.stderr else "")).strip()
    return f"(exit {p.returncode})\n{out[-6000:]}" if out else f"(exit {p.returncode}) nessun output"


# ---------- Note ----------

def notes_add(title: str, body: str) -> str:
    _need_mac()
    html = "<div><h1>" + title + "</h1></div>" + "".join(f"<div>{line or '<br>'}</div>" for line in body.split("\n"))
    _osa(
        'tell application "Notes"\n'
        "  set f to folder 1 of default account\n"
        f"  make new note at f with properties {{name:{_q(title)}, body:{_q(html)}}}\n"
        "end tell"
    )
    return f"Nota «{title}» creata in Note."


def notes_search(query: str) -> str:
    _need_mac()
    script = (
        "on minimo(a, b)\n  if a < b then return a\n  return b\nend minimo\n"
        'set out to ""\n'
        'tell application "Notes"\n'
        f"  repeat with n in (notes whose name contains {_q(query)} or plaintext contains {_q(query)})\n"
        "    set t to plaintext of n\n"
        '    set out to out & "### " & (name of n) & linefeed\n'
        "    if (length of t) > 0 then set out to out & (text 1 thru (my minimo(600, length of t)) of t) & linefeed & linefeed\n"
        "  end repeat\n"
        "end tell\n"
        "return out"
    )
    out = _osa(script, timeout=30)
    return out[:8000] or "Nessuna nota trovata."


# ---------- sistema ----------

def volume(level: int | None = None, mute: bool | None = None) -> str:
    _need_mac()
    if mute is not None:
        _osa(f"set volume output muted {'true' if mute else 'false'}")
        return "Audio disattivato." if mute else "Audio riattivato."
    if level is None:
        v = _osa("output volume of (get volume settings)")
        return f"Volume attuale: {v}%."
    lv = max(0, min(100, int(level)))
    _osa(f"set volume output volume {lv}")
    return f"Volume impostato al {lv}%."


def brightness(level: int) -> str:
    _need_mac()
    if not shutil.which("brightness"):
        return ("Per regolare la luminosità serve il piccolo programma 'brightness': installalo con "
                "`brew install brightness`, oppure crea un Comando rapido e chiedimi di eseguirlo.")
    lv = max(0, min(100, int(level))) / 100
    _run(["brightness", f"{lv:.2f}"])
    return f"Luminosità al {int(lv * 100)}%."


def battery() -> str:
    _need_mac()
    return _run(["pmset", "-g", "batt"]).replace("Now drawing from", "Alimentazione:")


def clipboard_get() -> str:
    _need_mac()
    return _run(["pbpaste"])[:6000] or "Appunti vuoti."


def clipboard_set(text: str) -> str:
    _need_mac()
    _run(["pbcopy"], input_text=text)
    return "Copiato negli appunti."


def shortcuts_list() -> str:
    _need_mac()
    return _run(["shortcuts", "list"]) or "Nessun Comando rapido."


def shortcut_run(name: str, text_input: str = "") -> str:
    """Esegue un Comando rapido e ne restituisce l'output (es. lo stato degli accessori di Casa)."""
    _need_mac()
    tmpdir = Path(tempfile.mkdtemp(prefix="axel_sc_"))
    out_path = tmpdir / "out.txt"
    cmd = ["shortcuts", "run", name, "--output-path", str(out_path), "--output-type", "public.plain-text"]
    if text_input:
        in_path = tmpdir / "in.txt"
        in_path.write_text(text_input, "utf-8")
        cmd += ["--input-path", str(in_path)]
    try:
        _run(cmd, timeout=90)
        out = out_path.read_text("utf-8", errors="replace").strip() if out_path.exists() else ""
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return f"Comando rapido «{name}» eseguito." + (f"\nRisultato:\n{out[:3000]}" if out else "")


def notify(title: str, message: str) -> str:
    _need_mac()
    _osa(f"display notification {_q(message)} with title {_q(title)} sound name \"Glass\"")
    return "Notifica mostrata."


# ---------- schermo ----------

def screenshot() -> list[dict]:
    """Restituisce lo screenshot come immagine per Claude (che così 'vede' lo schermo)."""
    _need_mac()
    tmp = Path(tempfile.gettempdir()) / f"axel_screen_{int(time.time())}.png"
    _run(["screencapture", "-x", "-C", str(tmp)], timeout=15)
    if not tmp.exists() or tmp.stat().st_size < 1000:
        raise MacError("Screenshot vuoto: concedi 'Registrazione schermo' all'app da cui avvii il backend "
                       "(Impostazioni di Sistema → Privacy e sicurezza).")
    jpg = tmp.with_suffix(".jpg")
    try:  # ridimensiona per contenere i token
        _run(["sips", "-Z", "1600", "-s", "format", "jpeg", "-s", "formatOptions", "70", str(tmp), "--out", str(jpg)])
        data, mt = jpg.read_bytes(), "image/jpeg"
    except MacError:
        data, mt = tmp.read_bytes(), "image/png"
    for f in (tmp, jpg):
        f.unlink(missing_ok=True)
    return [
        {"type": "text", "text": "Screenshot dello schermo dell'utente in questo momento:"},
        {"type": "image", "source": {"type": "base64", "media_type": mt, "data": base64.b64encode(data).decode()}},
    ]


def describe_command(command: str, cwd: str) -> str:
    return f"Eseguire nel terminale (in {cwd}):\n$ {command}"

