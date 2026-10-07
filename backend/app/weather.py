"""Meteo da Open-Meteo (gratuito, senza chiave). Dati strutturati per il widget + testo per AXEL."""
from __future__ import annotations

import httpx

CODES = {
    0: "sereno", 1: "prevalentemente sereno", 2: "parzialmente nuvoloso", 3: "coperto", 45: "nebbia", 48: "nebbia",
    51: "pioviggine", 53: "pioviggine", 55: "pioviggine intensa", 61: "pioggia debole", 63: "pioggia",
    65: "pioggia forte", 71: "neve debole", 73: "neve", 75: "neve forte", 77: "nevischio", 80: "rovesci", 81: "rovesci",
    82: "rovesci violenti", 85: "rovesci di neve", 86: "rovesci di neve", 95: "temporale", 96: "temporale con grandine",
    99: "temporale con grandine",
}


def kind(code: int) -> str:
    """Categoria per l'icona del widget."""
    if code == 0:
        return "clear"
    if code in (1, 2):
        return "partly"
    if code == 3:
        return "cloudy"
    if code in (45, 48):
        return "fog"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code >= 95:
        return "storm"
    return "rain"


class WeatherError(RuntimeError):
    pass


def data(city: str, days: int = 4) -> dict:
    with httpx.Client(timeout=10) as c:
        g = c.get("https://geocoding-api.open-meteo.com/v1/search",
                  params={"name": city, "count": 1, "language": "it"}).json()
        if not g.get("results"):
            raise WeatherError(f"Città non trovata: {city}")
        loc = g["results"][0]
        f = c.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": loc["latitude"], "longitude": loc["longitude"], "timezone": "auto",
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,is_day",
            "hourly": "temperature_2m,weather_code,precipitation_probability",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
            "forecast_days": max(2, min(days, 7)),
        }).json()
    cur = f["current"]
    d = f["daily"]
    h = f["hourly"]
    now = cur["time"][:13]  # "YYYY-MM-DDTHH"
    start = next((i for i, t in enumerate(h["time"]) if t[:13] >= now), 0)
    return {
        "city": loc["name"],
        "region": loc.get("admin1") or loc.get("country", ""),
        "current": {
            "temp": round(cur["temperature_2m"]), "feels": round(cur["apparent_temperature"]),
            "humidity": cur["relative_humidity_2m"], "wind": round(cur["wind_speed_10m"]),
            "code": cur["weather_code"], "desc": CODES.get(cur["weather_code"], "—"),
            "kind": kind(cur["weather_code"]), "is_day": bool(cur.get("is_day", 1)),
        },
        "today": {"sunrise": d["sunrise"][0][-5:], "sunset": d["sunset"][0][-5:]},
        "daily": [
            {"date": day, "code": d["weather_code"][i], "desc": CODES.get(d["weather_code"][i], "—"),
             "kind": kind(d["weather_code"][i]), "tmin": round(d["temperature_2m_min"][i]),
             "tmax": round(d["temperature_2m_max"][i]), "rain": d["precipitation_probability_max"][i]}
            for i, day in enumerate(d["time"])
        ],
        "hourly": [
            {"time": h["time"][i][-5:], "temp": round(h["temperature_2m"][i]), "kind": kind(h["weather_code"][i]),
             "rain": h["precipitation_probability"][i]}
            for i in range(start, min(start + 24, len(h["time"])))
        ],
    }


def as_text(w: dict, days: int = 2) -> str:
    c = w["current"]
    lines = [f"{w['city']}: ora {c['temp']}°C (percepiti {c['feels']}°), {c['desc']}, umidità {c['humidity']}%, "
             f"vento {c['wind']} km/h. Alba {w['today']['sunrise']}, tramonto {w['today']['sunset']}."]
    for day in w["daily"][:max(1, days)]:
        lines.append(f"{day['date']}: {day['desc']}, {day['tmin']}–{day['tmax']}°C, pioggia {day['rain']}%")
    return "\n".join(lines)


def forecast(city: str, days: int = 2) -> str:
    try:
        return as_text(data(city, max(days, 4)), days)
    except WeatherError as e:
        return str(e)
