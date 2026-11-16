"""
Analog reasoning: Gemini reads the measured numbers for a target and an Earth site and writes
where the analogy holds, where it breaks, and what the site is good for testing.

It only sees the values the search measured (no imagery, no site names it could recall facts
about), and is told to cite them, so every claim traces back to data on screen.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for line in (ROOT / ".env").read_text().splitlines() if (ROOT / ".env").exists() else []:
    k, _, v = line.partition("=")
    if k.strip() and v.strip():
        os.environ.setdefault(k.strip(), v.strip())

KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = os.environ.get("GEMINI_MODEL") or "gemini-3.5-flash"
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

SYSTEM = """You are a planetary scientist on a NASA analog-site selection team. You compare one Earth site with one place on the Moon or Mars using only the measurements given.

Rules:
- Each point is an object: "point" is a plain claim of 2 to 5 words (e.g. "Same relief", "Far warmer", "Carbonate soils"), no numbers; "evidence" is the supporting figures only, at most 10 words, site value first then the target's, e.g. "16.1 m here, 16.2 m at the target" or "17.9 °C against -49.6 °C".
- Soil is a soil classification, not bedrock geology or measured mineralogy. Link it to lunar or Martian materials only as a hedged inference ("may resemble", "shares"), never as a match.
- Never invent measurements, place facts, missions, or history. Do not name the Earth site.
- Plain, exact language for an expert reader. No hype, no hedging filler, no exclamation marks.
- "holds": the 3 strongest reasons this site is a useful analog, strongest first. Terrain shape first if the match is good.
- "breaks": the 3 most important ways the analogy fails, worst first. Use the measured gaps; at most one point may be about what Earth cannot reproduce (gravity, vacuum or thin CO2 air, radiation).
- "test": one sentence of at most 24 words naming the single most useful exploration activity to rehearse here (landing, rover mobility, navigation, construction, ISRU, EVA, instruments, dust mitigation), justified by the numbers.
- "verdict": at most 10 words, a crisp summary of what kind of analog this is."""

POINT = {"type": "OBJECT", "properties": {"point": {"type": "STRING"}, "evidence": {"type": "STRING"}}, "required": ["point", "evidence"]}
SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "verdict": {"type": "STRING"},
        "holds": {"type": "ARRAY", "items": POINT},
        "breaks": {"type": "ARRAY", "items": POINT},
        "test": {"type": "STRING"},
    },
    "required": ["verdict", "holds", "breaks", "test"],
}

LABELS = {
    "slope": ("mean slope", "°"), "slopeMax": ("steepest 10% slope", "°"), "flatGround": ("ground under 5° slope", "%"),
    "relief": ("relief (RMS height)", "m"), "heightRange": ("height range", "m"), "roughness": ("roughness (200 m step)", "m"),
    "concavity": ("centre minus rim height (negative = bowl)", "m"), "elevation": ("elevation", "m"),
    "meanTemp": ("mean temperature", "°C"), "coldMin": ("coldest low", "°C"), "hotMax": ("hottest high", "°C"),
    "dayNight": ("surface day-night swing", "°C"), "airDayNight": ("air day-night swing", "°C"),
    "solar": ("sunlight", "kWh/m²/day"), "wind": ("wind", "m/s"), "humidity": ("humidity", "%"), "cloud": ("cloud cover", "%"),
    "dust": ("dust optical depth", ""), "dustConc": ("near-surface dust", "µg/m³"), "pressure": ("air pressure", "kPa"),
}

_cache: dict[str, dict] = {}
_locks: dict[str, threading.Lock] = {}


def _facts(body: str, target_name: str, tm: dict, site: dict) -> str:
    sm, sh = site.get("metrics") or {}, site.get("shape") or {}
    rows = []
    for k, (label, unit) in LABELS.items():
        if k not in sm:
            continue
        t = f"{tm[k]:.3g} {unit}" if k in tm else "not measured"
        rows.append(f"- {label}: site {sm[k]:.3g} {unit}; target {t}")
    soil = site.get("soil")
    return "\n".join([
        f"Target: {target_name} on the {body.capitalize()}, {site.get('targetLat', 0):.3f}, {site.get('targetLon', 0):.3f}.",
        f"Earth site: latitude {site['lat']:.3f}, longitude {site['lon']:.3f}.",
        f"Terrain shape over the same 5.16 km² disk at 200 m pixels: RMSE {sh.get('rmseM')} m after turning the target "
        f"{sh.get('rotationDeg')}°, match score {round(100 * sh.get('score', 0))}% (score = exp(-(RMSE/target relief)^2)); "
        f"site relief {sh.get('reliefM')} m, target relief {sh.get('targetReliefM')} m.",
        f"Most common soil group (WRB 2006 soil map, 0.02° grid): {soil['group']} over {round(100 * soil['share'])}% of the cell, defined as: {soil['note']}." if soil else "Soil: no data.",
        "Measured values:",
        *rows,
        "Climate on Earth is from a coarse 10° reanalysis grid; Moon and Mars temperatures are surface temperatures.",
    ])


def compare(body: str, target_name: str, target_metrics: dict, site: dict) -> dict:
    if not KEY:
        raise RuntimeError("GEMINI_API_KEY is not set")
    key = f"{body}:{site.get('targetLat')}:{site.get('targetLon')}:{site['id']}"
    with _locks.setdefault(key, threading.Lock()):
        if key in _cache:
            return _cache[key]
        body_json = {
            "systemInstruction": {"parts": [{"text": SYSTEM}]},
            "contents": [{"role": "user", "parts": [{"text": _facts(body, target_name, target_metrics, site)}]}],
            "generationConfig": {"temperature": 0.3, "responseMimeType": "application/json", "responseSchema": SCHEMA,
                                 "thinkingConfig": {"thinkingLevel": "minimal"}},
        }
        req = urllib.request.Request(URL, data=json.dumps(body_json).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "x-goog-api-key": KEY})
        r = json.loads(urllib.request.urlopen(req, timeout=40).read())
        out = json.loads(next(p["text"] for p in r["candidates"][0]["content"]["parts"] if "text" in p and not p.get("thought")))
        out = {"verdict": out["verdict"].strip().rstrip("."), "holds": out["holds"][:3], "breaks": out["breaks"][:3],
               "test": out["test"].strip(), "model": MODEL}
        _cache[key] = out
        return out
