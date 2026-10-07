"""Notizie su misura: fonti RSS scelte da te + i tuoi interessi → poche notizie davvero rilevanti, riassunte.

Impostazioni (Integrazioni → Notizie): elenco di feed RSS/Atom e una frase con i tuoi interessi.
Un modello veloce sceglie le notizie più pertinenti delle ultime 36 ore e le riassume in una riga.
Usato dal briefing del mattino e dallo strumento news_digest ("Axel, novità sull'intelligenza artificiale?").
"""
from __future__ import annotations

import asyncio
import calendar
import logging
import re
import time

import httpx

from . import db, llm

log = logging.getLogger("axel.news")

DEFAULTS = {"feeds": [], "custom": [], "interests": "", "in_briefing": True, "count": 5}
PRESETS = [
    {"name": "ANSA", "url": "https://www.ansa.it/sito/ansait_rss.xml"},
    {"name": "Il Post", "url": "https://www.ilpost.it/feed/"},
    {"name": "Wired Italia", "url": "https://www.wired.it/feed/rss"},
    {"name": "Il Sole 24 Ore", "url": "https://www.ilsole24ore.com/rss/italia.xml"},
    {"name": "Hacker News", "url": "https://hnrss.org/frontpage"},
    {"name": "The Verge", "url": "https://www.theverge.com/rss/index.xml"},
]
_cache: dict[str, tuple[float, str]] = {}


def settings() -> dict:
    return {**DEFAULTS, **(db.get_setting("news") or {})}


def save(s: dict) -> dict:
    cur = settings()
    if "feeds" in s:
        feeds = []
        for f in s["feeds"]:
            url = str(f.get("url", "")).strip()
            if url.startswith(("http://", "https://")):
                feeds.append({"name": str(f.get("name") or url.split("/")[2])[:40], "url": url})
        cur["feeds"] = feeds[:30]
    if "custom" in s:
        cur["custom"] = [{"name": str(f.get("name") or "")[:40], "url": str(f.get("url"))} for f in s["custom"]
                         if str(f.get("url", "")).startswith(("http://", "https://"))][:40]
    for k in ("interests", "in_briefing", "count"):
        if k in s:
            cur[k] = s[k]
    db.set_setting("news", cur)
    _cache.clear()
    return cur


async def inspect_feed(url: str) -> dict:
    """Controlla che l'indirizzo sia un feed (o una pagina che ne indica uno) e ne ricava il nome."""
    import feedparser

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    headers = {"User-Agent": "Mozilla/5.0 AXEL/1.0 (lettore RSS personale)"}
    async with httpx.AsyncClient(timeout=12, follow_redirects=True, headers=headers) as c:
        try:
            r = await c.get(url)
        except httpx.HTTPError as exc:
            raise ValueError(f"indirizzo non raggiungibile ({type(exc).__name__})") from exc
        if r.status_code >= 400:
            raise ValueError(f"il sito risponde con errore {r.status_code}: controlla l'indirizzo")
        parsed = feedparser.parse(r.content)
        if not parsed.entries and "html" in r.headers.get("content-type", ""):
            # pagina di un sito: cerca il feed indicato nell'HTML (<link rel="alternate" type="application/rss+xml">)
            m = re.search(r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]*>', r.text, re.I)
            href = re.search(r'href=["\']([^"\']+)', m.group(0)).group(1) if m else None
            if not href:
                raise ValueError("questa pagina non sembra avere un feed RSS")
            url = str(httpx.URL(str(r.url)).join(href))
            r = await c.get(url)
            r.raise_for_status()
            parsed = feedparser.parse(r.content)
    if not parsed.entries:
        raise ValueError("non sembra un feed RSS valido (nessuna notizia trovata)")
    title = (parsed.feed.get("title") or httpx.URL(url).host or "Feed").strip()
    title = re.split(r"\s+[|\-–—:]\s+", title)[0][:40]  # "Repubblica.it - Home" → "Repubblica.it"
    return {"name": title, "url": url, "items": len(parsed.entries)}


async def _fetch(client: httpx.AsyncClient, feed: dict) -> list[dict]:
    import feedparser

    try:
        r = await client.get(feed["url"], timeout=12, follow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0 AXEL/1.0 (lettore RSS personale)"})
        r.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        log.warning("feed %s: %s", feed["url"], exc)
        return []
    parsed = feedparser.parse(r.content)
    items = []
    cutoff = time.time() - 36 * 3600
    for e in parsed.entries[:40]:
        ts = e.get("published_parsed") or e.get("updated_parsed")
        when = calendar.timegm(ts) if ts else time.time()
        if when < cutoff:
            continue
        summary = re.sub(r"<[^>]+>", " ", e.get("summary", "") or "")
        items.append({"source": feed["name"], "title": (e.get("title") or "").strip(), "link": e.get("link", ""),
                      "summary": re.sub(r"\s+", " ", summary).strip()[:280], "ts": when})
    return items


async def collect() -> list[dict]:
    feeds = settings()["feeds"]
    if not feeds:
        return []
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*(_fetch(client, f) for f in feeds))
    seen, items = set(), []
    for it in sorted((i for r in results for i in r), key=lambda x: -x["ts"]):
        key = re.sub(r"\W", "", it["title"].lower())[:60]
        if key and key not in seen:
            seen.add(key)
            items.append(it)
    return items[:150]


async def digest(topic: str = "", count: int | None = None) -> str:
    s = settings()
    if not s["feeds"]:
        return "Non hai ancora scelto fonti di notizie: aggiungile in Integrazioni → Notizie su misura."
    n = int(count or s.get("count") or 5)
    key = f"{topic}|{n}"
    if key in _cache and time.time() - _cache[key][0] < 1800:
        return _cache[key][1]
    items = await collect()
    if not items:
        return "Nessuna notizia nelle ultime 36 ore dalle tue fonti (o fonti non raggiungibili)."
    listing = "\n".join(f"[{i}] ({it['source']}) {it['title']} — {it['summary'][:160]}" for i, it in enumerate(items))
    focus = f"Argomento richiesto ora: {topic}." if topic else ""
    data = await llm.ask_json(
        f"Sei il redattore personale dell'utente. Interessi dell'utente: {s['interests'] or 'non indicati (scegli le più importanti)'}. "
        f"{focus}\nScegli le {n} notizie più rilevanti e diverse tra loro tra queste (ultime 36 ore). Per ognuna scrivi "
        "una riga di riassunto in italiano, concreta (chi, cosa, perché conta), massimo 25 parole.\n\n"
        f"{listing}\n\n"
        'Formato: {"picks": [{"i": 0, "line": "..."}]}',
        max_tokens=1200,
    )
    picks = (data or {}).get("picks") or [{"i": i, "line": it["title"]} for i, it in enumerate(items[:n])]
    lines = []
    for p in picks[:n]:
        try:
            it = items[int(p["i"])]
        except (ValueError, IndexError, KeyError, TypeError):
            continue
        lines.append(f"- {p.get('line') or it['title']} ({it['source']}) {it['link']}")
    out = "\n".join(lines) or "Nessuna notizia pertinente."
    _cache[key] = (time.time(), out)
    return out
