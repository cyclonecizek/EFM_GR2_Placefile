#!/usr/bin/env python3
"""Live MERLIN CC/CG placefiles, matching LaunchWeatherReplay rendering."""
from __future__ import annotations
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import time
import requests

UTC = timezone.utc
KM_LAT = 111.195
KM_LON = KM_LAT * math.cos(math.radians(28.5))
COLORS = ["50 120 240", "30 205 230", "115 225 100", "245 220 60", "250 145 35", "240 60 80"]
TRAIL = int(os.getenv("MERLIN_TRAIL_MINUTES", "15"))
HISTORY = int(os.getenv("MERLIN_HISTORY_MINUTES", "60"))

@dataclass(frozen=True)
class Event:
    dt: datetime
    lat: float
    lon: float
    signal: str
    original_time: str
    identity: str
    subsecond: bool


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def parse_api(payload):
    if not isinstance(payload, list):
        raise ValueError("MERLIN API response must be a JSON array")
    events = []
    rejected = 0
    for row in payload:
        try:
            lat, lon = number(row.get("lat_decimal")), number(row.get("lon_decimal"))
            if lat is None or lon is None or not -90 <= lat <= 90 or not -180 <= lon <= 180:
                raise ValueError("Invalid coordinates")
            dt = datetime.fromisoformat(row["event_datetime"].replace("Z", "+00:00"))
            dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
            original = str(row.get("event_time") or dt.strftime("%H:%M:%S.%f"))
            fraction = original.partition(".")[2].rstrip("Z")
            subsecond = any(c in "123456789" for c in fraction)
            signal = number(row.get("signal_strength"))
            # IDs preserve distinct detections separated by less than a microsecond.
            identity = str(row.get("id") or (str(row.get("event_date")), original, lat, lon, signal))
            events.append(Event(dt, lat, lon, str(signal) if signal is not None else "unknown",
                                original, identity, subsecond))
        except (ValueError, KeyError, TypeError, AttributeError):
            rejected += 1
    if payload and not events:
        raise ValueError("MERLIN response contained no usable events")
    return events, rejected


def get_json(kind, path, params):
    host = os.getenv(f"MERLIN_{kind.upper()}_API_BASE_URL",
                     f"https://codiapi-lightning{kind}.rad.spaceforce.mil").rstrip("/")
    for attempt in range(3):
        try:
            r = requests.get(host + path, params=params, timeout=45,
                             headers={"Accept": "application/json", "User-Agent": "MERLIN-GRLevelX/1.0"})
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as exc:
            status = exc.response.status_code if exc.response is not None else None
            if attempt == 2 or (status is not None and status < 500 and status != 429):
                raise
            time.sleep(2 ** attempt)


def fetch_window(kind, start, end):
    def chunk(a, b):
        fmt = "%Y-%m-%dT%H:%M:%S"
        try:
            payload = get_json(kind, f"/lightning_{kind}/range", {
                "date>": a.strftime(fmt), "date<": b.strftime(fmt), "sort": "asc"})
            # Encoded query keys date> and date< with '=' mean >= and <=.
            return parse_api(payload)
        except requests.exceptions.HTTPError as exc:
            body = exc.response.text.lower() if exc.response is not None else ""
            if ("100000" in body.replace(",", "") or "too many" in body) and b-a > timedelta(seconds=2):
                mid = a + timedelta(seconds=int((b-a).total_seconds())//2)
                x, xr = chunk(a, mid)
                y, yr = chunk(mid, b)
                return x+y, xr+yr
            raise
    events, rejected = [], 0
    a = start
    while a < end:
        b = min(end, a + timedelta(minutes=5))
        parsed, count = chunk(a, b)
        events.extend(parsed)
        rejected += count
        a = b
    unique = {e.identity: e for e in events if start <= e.dt < end}
    return sorted(unique.values(), key=lambda e: e.dt), rejected


def grtime(dt):
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")


def escape(text):
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "").replace("\n", "\\n")


def cell_key(e):
    return math.floor((e.lon+80.6)*KM_LON), math.floor((e.lat-28.5)*KM_LAT)


def density_color(count):
    return COLORS[next((i for i, edge in enumerate([5,20,50,100,250]) if count < edge), 5)]


def cg_placefile(events, now, trail, history):
    start = now - timedelta(minutes=history)
    lines = [f"Title: MERLIN CG / trailing {trail} min", "RefreshSeconds: 60", "Threshold: 999",
             'Font: 1, 13, 1, "Arial"', f"; Generated UTC: {grtime(now)}",
             "; Gold CG crosses match LaunchWeatherReplay. Counts are detections, not flashes."]
    for e in events:
        a = max(start, e.dt.replace(microsecond=0) + timedelta(seconds=1 if e.subsecond else 0))
        b = (e.dt + timedelta(minutes=trail)).replace(microsecond=0)
        if b <= a:
            continue
        hover = escape(f"CG detection / {e.dt:%Y-%m-%d}T{e.original_time}Z / signal strength {e.signal} (source units)")
        lines += [f"TimeRange: {grtime(a)} {grtime(b)}", "Color: 255 210 80",
                  f'Text: {e.lat:.7f}, {e.lon:.7f}, 1, "+", "{hover}"']
    return "\n".join(lines) + "\n"


def cc_placefile(events, now, trail, history):
    lines = [f"Title: MERLIN CC density dots / approximately 1 km / trailing {trail} min",
             "RefreshSeconds: 60", "Threshold: 999", 'Font: 2, 10, 0, "Wingdings"',
             'Font: 3, 12, 0, "Wingdings"', f"; Generated UTC: {grtime(now)}",
             "; One opaque outlined dot per occupied cell; no on-map caption.",
             "; Counts are detection records, not flashes. Minute T counts [T-trail,T).",
             "; Blue 1-4, cyan 5-19, green 20-49, yellow 50-99, orange 100-249, red 250+."]
    minutes = {}
    for e in events:
        minute = e.dt.replace(second=0, microsecond=0)
        minutes.setdefault(minute, Counter())[cell_key(e)] += 1
    frame = now - timedelta(minutes=history)
    while frame < now + timedelta(minutes=trail):
        counts = Counter()
        for minute, values in minutes.items():
            if frame-timedelta(minutes=trail) <= minute < frame:
                counts.update(values)
        if counts:
            lines.append(f"TimeRange: {grtime(frame)} {grtime(frame+timedelta(minutes=1))}")
        for (i,j), count in sorted(counts.items()):
            lat,lon = 28.5+(j+0.5)/KM_LAT, -80.6+(i+0.5)/KM_LON
            hover = escape(f"{count} CC detection records / approximately 1 km cell / trailing {trail} min / {grtime(frame)}Z")
            lines += [f"Object: {lat:.7f}, {lon:.7f}", "Color: 15 20 25", 'Text: 0, 0, 3, "l"',
                      f"Color: {density_color(count)}", f'Text: 0, 0, 2, "l", "{hover}"', "End:"]
        frame += timedelta(minutes=1)
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--outdir", default="docs")
    parser.add_argument("--now", help="UTC timestamp for historical testing")
    args = parser.parse_args()
    if not 1 <= TRAIL <= 60 or not 0 <= HISTORY <= 60:
        raise ValueError("MERLIN_TRAIL_MINUTES must be 1-60 and MERLIN_HISTORY_MINUTES 0-60")
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(UTC)
    now = now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
    now = now.replace(second=0,microsecond=0)
    start = now - timedelta(minutes=HISTORY+TRAIL)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {kind: pool.submit(fetch_window,kind,start,now) for kind in ["c2c","c2g"]}
        data = {kind: f.result() for kind,f in futures.items()}
    # Build both completely before replacing either published output.
    cc = cc_placefile(data["c2c"][0],now,TRAIL,HISTORY)
    cg = cg_placefile(data["c2g"][0],now,TRAIL,HISTORY)
    diag = {"generated_utc":now.isoformat(), "window_start_utc":start.isoformat(),
            "trail_minutes":TRAIL, "history_minutes":HISTORY,
            "source":"MERLIN C2C/C2G APIs", "feeds":{}}
    for kind,(events,rejected) in data.items():
        diag["feeds"][kind] = {"records":len(events),"rejected":rejected,
            "newest_event_utc":max((e.dt for e in events),default=None).isoformat() if events else None,
            "current_window_records":sum(now-timedelta(minutes=TRAIL) <= e.dt < now for e in events)}
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    for name,text in [("merlin_cc_density.txt",cc),("merlin_cg.txt",cg),("merlin_status.json",json.dumps(diag,indent=2))]:
        (out/name).write_text(text,encoding="utf-8")
    print(json.dumps(diag))

if __name__ == "__main__": main()
