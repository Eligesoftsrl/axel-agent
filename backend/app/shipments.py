"""Spedizioni: AXEL legge le email di ordini e corrieri, tiene traccia dei pacchi e avvisa quando arrivano.

Non serve collegare i corrieri: lo stato si aggiorna dalle email che mandano (Amazon, BRT, GLS, SDA, Poste,
DHL, UPS…). Un modello veloce estrae corriere, numero di tracking, oggetto e stato da ogni email.
Avvisi: "in consegna oggi", "consegnato", "problema con la consegna".
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime

from . import db, google_api, llm
from .google_api import tz

log = logging.getLogger("axel.shipments")

STATUSES = ["ordered", "shipped", "in_transit", "out_for_delivery", "delivered", "exception"]
LABEL = {"ordered": "ordinato", "shipped": "spedito", "in_transit": "in viaggio", "out_for_delivery": "in consegna oggi",
         "delivered": "consegnato", "exception": "problema"}
TRACK_URLS = {
    "brt": "https://vas.brt.it/vas/sped_det_show.hsm?referer=sped_numspe_par.htm&Nspediz={t}",
    "gls": "https://www.gls-italy.com/it/servizi-online/ricerca-spedizioni?match={t}",
    "sda": "https://www.sda.it/wps/portal/Servizi_online/dettaglio-spedizione?locale=it&tracing.letteraVettura={t}",
    "poste": "https://www.poste.it/cerca/index.html#/risultati-spedizioni/{t}",
    "dhl": "https://www.dhl.com/it-it/home/tracciabilita.html?tracking-id={t}",
    "ups": "https://www.ups.com/track?loc=it_IT&tracknum={t}",
    "fedex": "https://www.fedex.com/fedextrack/?trknbr={t}",
    "tnt": "https://www.tnt.it/tracking/Tracking.do?wt=1&consigNos={t}",
    "inpost": "https://inpost.it/trova-il-tuo-pacco?number={t}",
}
QUERY = ("newer_than:4d -in:spam -in:trash (spedizione OR spedito OR spedita OR consegna OR consegnato OR tracking OR "
         "\"in transito\" OR corriere OR pacco OR shipped OR delivered OR \"out for delivery\" OR ordine OR order)")

SCHEMA = """
CREATE TABLE IF NOT EXISTS shipments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  key TEXT UNIQUE NOT NULL,
  item TEXT, merchant TEXT, carrier TEXT, tracking TEXT,
  status TEXT NOT NULL DEFAULT 'shipped', eta TEXT, link TEXT,
  last_email TEXT, updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  archived INTEGER NOT NULL DEFAULT 0
);
"""


def _ensure() -> None:
    with db.tx() as c:
        c.executescript(SCHEMA)


def track_url(carrier: str | None, tracking: str | None) -> str:
    if not tracking:
        return ""
    key = (carrier or "").lower()
    for name, url in TRACK_URLS.items():
        if name in key:
            return url.format(t=tracking)
    return f"https://www.google.com/search?q=tracking+{tracking}"


def active() -> list[dict]:
    _ensure()
    return db.query("SELECT * FROM shipments WHERE archived=0 AND (status!='delivered' OR updated_at > datetime('now','-2 days')) "
                    "ORDER BY CASE status WHEN 'out_for_delivery' THEN 0 WHEN 'exception' THEN 1 ELSE 2 END, updated_at DESC")


def archive(sid: int) -> bool:
    _ensure()
    with db.tx() as c:
        return c.execute("UPDATE shipments SET archived=1 WHERE id=?", (sid,)).rowcount > 0


def as_text() -> str:
    rows = active()
    if not rows:
        return "Nessuna spedizione in corso (le rilevo dalle email di ordini e corrieri)."
    out = []
    for r in rows:
        eta = f", arrivo previsto {r['eta']}" if r.get("eta") and r["status"] != "delivered" else ""
        who = " · ".join(x for x in (r.get("carrier"), r.get("tracking")) if x)
        out.append(f"- {r.get('item') or 'Pacco'}{' da ' + r['merchant'] if r.get('merchant') else ''}: "
                   f"{LABEL.get(r['status'], r['status'])}{eta}{' (' + who + ')' if who else ''}")
    return "\n".join(out)


def _fetch_candidates() -> list[dict]:
    svc = google_api._svc("gmail", "v1")
    ids = [m["id"] for m in svc.users().messages().list(userId="me", q=QUERY, maxResults=20).execute().get("messages", [])]
    stored = db.get_setting("seen_ship_emails")
    seen = set(stored or [])
    fresh = [i for i in ids if i not in seen]
    if stored is None:  # primo avvio: guarda solo le ultime 6 per partire con lo stato attuale
        fresh = ids[:6]
    out = []
    for mid in fresh:
        m = svc.users().messages().get(userId="me", id=mid, format="full").execute()
        body = google_api._body_text(m.get("payload", {}))
        out.append({"id": mid, "from": google_api._header(m, "From"), "subject": google_api._header(m, "Subject"),
                    "text": re.sub(r"\s+", " ", body)[:1800] or m.get("snippet", "")})
    db.set_setting("seen_ship_emails", (list(seen) + fresh)[-400:])
    return out


async def extract(emails: list[dict]) -> list[dict]:
    if not emails:
        return []
    listing = "\n\n".join(f"[{e['id']}] Da: {e['from']}\nOggetto: {e['subject']}\n{e['text']}" for e in emails)
    data = await llm.ask_json(
        "Queste sono email recenti. Individua SOLO quelle che riguardano una spedizione o un ordine di un oggetto fisico "
        "(conferme d'ordine, spedizioni, aggiornamenti del corriere, consegne). Ignora newsletter, promozioni, fatture "
        "di servizi, ordini di cibo a domicilio.\n"
        f"Per ognuna estrai: id, item (cosa, breve), merchant (negozio), carrier (corriere, es. BRT, GLS, Poste, Amazon), "
        f"tracking (numero di tracking o null), status (uno tra {', '.join(STATUSES)}), "
        "eta (data prevista di consegna YYYY-MM-DD o null).\n\n"
        f"Email:\n{listing}\n\n"
        'Formato: {"shipments": [{"id": "...", "item": "...", "merchant": "...", "carrier": "...", "tracking": null, '
        '"status": "shipped", "eta": null}]}',
        max_tokens=1500,
    )
    return [s for s in (data or {}).get("shipments", []) if s.get("status") in STATUSES]


def _key(s: dict) -> str:
    if s.get("tracking"):
        return "t:" + re.sub(r"\W", "", str(s["tracking"])).upper()
    base = f"{s.get('merchant') or ''}|{s.get('item') or ''}".lower()
    return "m:" + re.sub(r"[^a-z0-9|]", "", base)[:80]


def upsert(found: list[dict]) -> list[tuple[dict, str | None]]:
    """Aggiorna la tabella; restituisce (spedizione, stato precedente) per quelle cambiate."""
    _ensure()
    changes = []
    rank = {s: i for i, s in enumerate(STATUSES)}
    for s in found:
        key = _key(s)
        old = db.query("SELECT * FROM shipments WHERE key=?", (key,))
        if not old and not s.get("tracking"):  # stesso oggetto senza tracking: cerca per negozio+oggetto simile
            old = db.query("SELECT * FROM shipments WHERE archived=0 AND merchant=? AND item=?", (s.get("merchant"), s.get("item")))
        link = track_url(s.get("carrier"), s.get("tracking"))
        if old:
            o = old[0]
            # lo stato va solo avanti (tranne i problemi)
            new_status = s["status"] if (s["status"] == "exception" or rank[s["status"]] >= rank.get(o["status"], 0)) else o["status"]
            with db.tx() as c:
                c.execute("UPDATE shipments SET status=?, eta=COALESCE(?, eta), carrier=COALESCE(?, carrier), "
                          "tracking=COALESCE(?, tracking), link=COALESCE(NULLIF(?, ''), link), last_email=?, updated_at=datetime('now') WHERE id=?",
                          (new_status, s.get("eta"), s.get("carrier"), s.get("tracking"), link, s.get("id"), o["id"]))
            if new_status != o["status"]:
                changes.append(({**o, **{k: v for k, v in s.items() if v}, "status": new_status}, o["status"]))
        else:
            with db.tx() as c:
                c.execute("INSERT OR IGNORE INTO shipments(key, item, merchant, carrier, tracking, status, eta, link, last_email) "
                          "VALUES (?,?,?,?,?,?,?,?,?)",
                          (key, s.get("item"), s.get("merchant"), s.get("carrier"), s.get("tracking"), s["status"], s.get("eta"),
                           link, s.get("id")))
            changes.append((s, None))
    return changes


def message_for(s: dict, prev: str | None) -> str | None:
    what = s.get("item") or "il tuo pacco"
    who = f" ({s['carrier']})" if s.get("carrier") else ""
    if s["status"] == "out_for_delivery":
        return f"📦 Oggi arriva {what}{who}: è in consegna."
    if s["status"] == "delivered":
        return f"✅ Consegnato: {what}{who}."
    if s["status"] == "exception":
        return f"⚠️ Problema con la spedizione di {what}{who}: controlla l'email del corriere."
    if prev is None and s["status"] in ("shipped", "in_transit"):
        eta = f", arrivo previsto {s['eta']}" if s.get("eta") else ""
        return f"🚚 Spedito {what}{who}{eta}."
    return None


async def check(deliver) -> None:
    emails = await asyncio.to_thread(_fetch_candidates)
    found = await extract(emails)
    for s, prev in await asyncio.to_thread(upsert, found):
        msg = message_for(s, prev)
        if msg:
            await deliver("shipment", msg, subject=msg[:60])
    log.info("spedizioni: %d email, %d rilevate", len(emails), len(found))


def today_hint() -> str:
    """Una riga per il briefing: cosa arriva oggi."""
    today = datetime.now(tz()).date().isoformat()
    rows = [r for r in active() if r["status"] == "out_for_delivery" or (r.get("eta") == today and r["status"] != "delivered")]
    return "; ".join(r.get("item") or "un pacco" for r in rows)
