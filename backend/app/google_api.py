"""Google Calendar + Gmail per il tuo account, via OAuth.

Setup (una volta): crea un client OAuth "Applicazione web" su Google Cloud Console con
URI di reindirizzamento  http://localhost:8010/api/google/callback , scarica il JSON e
salvalo come  backend/data/google_client_secret.json  (vedi README).
Il token viene salvato nel database locale; non lascia mai il tuo Mac.
"""
from __future__ import annotations

import base64
import os
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo

from . import db

# localhost in http: consentito solo per sviluppo locale
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]


def _secret_file() -> Path:
    p = os.getenv("GOOGLE_CLIENT_SECRET_FILE")
    return Path(p) if p else db.DATA_DIR / "google_client_secret.json"


def _redirect_uri() -> str:
    port = os.getenv("PORT", "8010")
    return os.getenv("GOOGLE_REDIRECT_URI", f"http://localhost:{port}/api/google/callback")


def tz() -> ZoneInfo:
    return ZoneInfo(os.getenv("TZ_NAME", "Europe/Rome"))


# ---------- OAuth ----------

_pending_verifiers: dict[str, str | None] = {}


def status() -> dict:
    if not _secret_file().exists():
        return {"configured": False, "connected": False, "email": None}
    tok = db.get_setting("google_token")
    return {"configured": True, "connected": bool(tok), "email": db.get_setting("google_email")}


def auth_url() -> str:
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_secrets_file(str(_secret_file()), scopes=SCOPES, redirect_uri=_redirect_uri())
    url, state = flow.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="true")
    _pending_verifiers[state] = getattr(flow, "code_verifier", None)
    return url


def finish_auth(full_url: str, state: str) -> str:
    from google_auth_oauthlib.flow import Flow
    from googleapiclient.discovery import build

    flow = Flow.from_client_secrets_file(str(_secret_file()), scopes=SCOPES, redirect_uri=_redirect_uri(), state=state)
    verifier = _pending_verifiers.pop(state, None)
    if verifier:
        flow.code_verifier = verifier
    flow.fetch_token(authorization_response=full_url)
    creds = flow.credentials
    db.set_setting("google_token", creds.to_json())
    try:
        info = build("oauth2", "v2", credentials=creds, cache_discovery=False).userinfo().get().execute()
        db.set_setting("google_email", info.get("email"))
    except Exception:  # noqa: BLE001
        pass
    return db.get_setting("google_email") or ""


def disconnect() -> None:
    db.del_setting("google_token")
    db.del_setting("google_email")


def _creds():
    import json

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    raw = db.get_setting("google_token")
    if not raw:
        raise RuntimeError("Google non collegato. Collegalo dal pannello Integrazioni.")
    creds = Credentials.from_authorized_user_info(json.loads(raw), SCOPES)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
        db.set_setting("google_token", creds.to_json())
    return creds


def _svc(name: str, version: str):
    from googleapiclient.discovery import build

    return build(name, version, credentials=_creds(), cache_discovery=False)


# ---------- Calendario ----------

def _parse_local(s: str) -> datetime:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=tz())


def calendar_list(start: str | None = None, end: str | None = None, query: str | None = None, max_results: int = 20) -> str:
    now = datetime.now(tz())
    t0 = _parse_local(start) if start else now.replace(hour=0, minute=0, second=0, microsecond=0)
    t1 = _parse_local(end) if end else t0 + timedelta(days=1)
    res = (
        _svc("calendar", "v3")
        .events()
        .list(calendarId="primary", timeMin=t0.isoformat(), timeMax=t1.isoformat(), singleEvents=True,
              orderBy="startTime", maxResults=max_results, q=query or None)
        .execute()
    )
    items = res.get("items", [])
    if not items:
        return f"Nessun evento tra {t0:%d/%m %H:%M} e {t1:%d/%m %H:%M}."
    out = []
    for e in items:
        s = e["start"].get("dateTime", e["start"].get("date"))
        en = e["end"].get("dateTime", e["end"].get("date"))
        when = s if "T" not in s else f"{_parse_local(s):%a %d/%m %H:%M}–{_parse_local(en):%H:%M}"
        loc = f" @ {e['location']}" if e.get("location") else ""
        out.append(f"- {when}: {e.get('summary', '(senza titolo)')}{loc} [id {e['id']}]")
    return "\n".join(out)


def calendar_create(title: str, start: str, end: str | None = None, description: str = "", location: str = "",
                    attendees: list[str] | None = None) -> str:
    t0 = _parse_local(start)
    t1 = _parse_local(end) if end else t0 + timedelta(hours=1)
    body = {
        "summary": title,
        "description": description,
        "location": location,
        "start": {"dateTime": t0.isoformat(), "timeZone": str(tz())},
        "end": {"dateTime": t1.isoformat(), "timeZone": str(tz())},
    }
    if attendees:
        body["attendees"] = [{"email": a} for a in attendees]
    ev = _svc("calendar", "v3").events().insert(calendarId="primary", body=body).execute()
    return f"Evento creato: {title} il {t0:%d/%m alle %H:%M}. Link: {ev.get('htmlLink', '')}"


def calendar_delete(event_id: str) -> str:
    _svc("calendar", "v3").events().delete(calendarId="primary", eventId=event_id).execute()
    return "Evento eliminato."


# ---------- Gmail ----------

def _header(msg: dict, name: str) -> str:
    for h in msg.get("payload", {}).get("headers", []):
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def gmail_search(query: str = "is:unread newer_than:2d", max_results: int = 10) -> str:
    svc = _svc("gmail", "v1")
    res = svc.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    ids = [m["id"] for m in res.get("messages", [])]
    if not ids:
        return "Nessuna email trovata."
    out = []
    for mid in ids:
        m = svc.users().messages().get(userId="me", id=mid, format="metadata",
                                        metadataHeaders=["From", "Subject", "Date"]).execute()
        out.append(f"- [{mid}] {_header(m, 'Date')[:22]} | {_header(m, 'From')} | {_header(m, 'Subject')}\n  {m.get('snippet', '')[:160]}")
    return "\n".join(out)


def _body_text(payload: dict) -> str:
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", "ignore")
    for p in payload.get("parts", []) or []:
        t = _body_text(p)
        if t:
            return t
    if payload.get("body", {}).get("data"):
        import re

        html = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", "ignore")
        return re.sub(r"<[^>]+>", " ", html)
    return ""


def gmail_read(message_id: str) -> str:
    m = _svc("gmail", "v1").users().messages().get(userId="me", id=message_id, format="full").execute()
    body = " ".join(_body_text(m.get("payload", {})).split())
    return (f"Da: {_header(m, 'From')}\nA: {_header(m, 'To')}\nData: {_header(m, 'Date')}\n"
            f"Oggetto: {_header(m, 'Subject')}\nThread: {m.get('threadId')}\n\n{body[:6000]}")


def _mime(to: str, subject: str, body: str, thread_id: str | None = None) -> dict:
    msg = MIMEText(body, "plain", "utf-8")
    msg["to"] = to
    msg["subject"] = subject
    raw = {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}
    if thread_id:
        raw["threadId"] = thread_id
    return raw


def gmail_draft(to: str, subject: str, body: str, thread_id: str | None = None) -> str:
    d = _svc("gmail", "v1").users().drafts().create(userId="me", body={"message": _mime(to, subject, body, thread_id)}).execute()
    return f"Bozza salvata in Gmail (id {d['id']}) per {to}: «{subject}»."


def gmail_send(to: str, subject: str, body: str, thread_id: str | None = None) -> str:
    _svc("gmail", "v1").users().messages().send(userId="me", body=_mime(to, subject, body, thread_id)).execute()
    return f"Email inviata a {to}: «{subject}»."


def send_to_self(subject: str, body: str) -> bool:
    """Notifica via email a te stesso (fallback se Telegram non è collegato)."""
    email = db.get_setting("google_email")
    if not email or not db.get_setting("google_token"):
        return False
    gmail_send(email, subject, body)
    return True
