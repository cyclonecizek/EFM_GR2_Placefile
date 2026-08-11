#!/usr/bin/env python3
"""
KSC Spaceport Weather Archive 1-minute Field Mill -> GRLevelX placefile.

Known KSC export schema:
    OneMinuteMean,Date,Time,MillNo

The generator:
- fetches or reads a KSC FieldMill/Export CSV
- parses timestamps explicitly
- finds the newest observation per mill (CSV order is not trusted)
- joins MillNo to the coordinate table
- writes a GRLevelX placefile and diagnostic JSON
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests

USER_AGENT = "KSC-FieldMill-GRLevelX/2.0"

@dataclass
class Observation:
    site: str
    time: datetime
    value_vpm: float

def parse_number(value: str) -> float | None:
    try:
        x = float(str(value).strip())
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None

def parse_ksc_datetime(date_s: str, time_s: str) -> datetime | None:
    s = f"{date_s.strip()} {time_s.strip()}"
    for fmt in (
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%m/%d/%y %H:%M:%S",
        "%m/%d/%y %H:%M",
    ):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None

def normalize_site(mill_no: str) -> str | None:
    s = str(mill_no).strip()
    if not s:
        return None
    try:
        n = int(float(s))
    except ValueError:
        m = re.search(r"(\d{1,2})", s)
        if not m:
            return None
        n = int(m.group(1))
    return f"FM{n:02d}"

def parse_ksc_export_csv(text: str) -> list[Observation]:
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    if not reader.fieldnames:
        raise ValueError("CSV has no header")

    normalized = {name.strip().lower(): name for name in reader.fieldnames}
    required = {
        "oneminutemean": None,
        "date": None,
        "time": None,
        "millno": None,
    }
    for key in required:
        if key not in normalized:
            raise ValueError(
                f"Expected KSC export column '{key}' not found. "
                f"Columns were: {reader.fieldnames}"
            )
        required[key] = normalized[key]

    out = []
    for row in reader:
        value = parse_number(row.get(required["oneminutemean"], ""))
        dt = parse_ksc_datetime(
            row.get(required["date"], ""),
            row.get(required["time"], ""),
        )
        site = normalize_site(row.get(required["millno"], ""))
        if value is None or dt is None or site is None:
            continue
        out.append(Observation(site=site, time=dt, value_vpm=value))

    if not out:
        raise ValueError("No valid KSC field-mill observations were parsed")
    return out


BASE60 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz01234567"

# Verified 2026 token structure for the current all-mills + OneMinuteMean selection:
#
#   Ba M D H m ABa M D H m AAAABaAABACAEAFAGAHAIAJAKALAMANAOAPAQARASATAUAVAWAXAYAZAaAbAcAdAeAfAgAhAiAj
#
# Example:
#   Aug 11 14:00 -> Aug 11 14:10
#   BaILOAABaILOKAAAABaAABACAEAFAGAHAIAJAKALAMANAOAPAQARASATAUAVAWAXAYAZAaAbAcAdAeAfAgAhAiAj
TOKEN_PREFIX = "Ba"
TOKEN_BETWEEN = "ABa"
TOKEN_AFTER_END = "AAAABaAABACAEAFAGAHAIAJAKALAMANAOAPAQARASATAUAVAWAXAYAZAaAbAcAdAeAfAgAhAiAj"

def enc60(n: int) -> str:
    if not 0 <= n < len(BASE60):
        raise ValueError(f"value {n} is outside KSC single-character range")
    return BASE60[n]

def encode_ksc_dt(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    return enc60(dt.month) + enc60(dt.day) + enc60(dt.hour) + enc60(dt.minute)

def build_ksc_token(start: datetime, end: datetime) -> str:
    if end <= start:
        raise ValueError("end time must be later than start time")
    if start.year != 2026 or end.year != 2026:
        raise ValueError(
            "Automatic token generation is currently verified only for 2026."
        )
    return (
        TOKEN_PREFIX
        + encode_ksc_dt(start)
        + TOKEN_BETWEEN
        + encode_ksc_dt(end)
        + TOKEN_AFTER_END
    )

def build_export_url(start: datetime, end: datetime) -> str:
    return (
        "https://kscweather.ksc.nasa.gov/wxarchive/FieldMill/Export/"
        + build_ksc_token(start, end)
    )

def fetch_export() -> str:
    export_url = os.getenv("KSC_ARCHIVE_RESULT_URL", "").strip()

    if not export_url:
        lookback = int(os.getenv("LOOKBACK_MINUTES", "60"))
        end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        start = end - timedelta(minutes=lookback)
        export_url = build_export_url(start, end)

    print(f"KSC export URL: {export_url}")

    r = requests.get(
        export_url,
        timeout=60,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/csv,text/plain,application/octet-stream,*/*",
        },
    )
    r.raise_for_status()
    return r.text

def load_sites(path: Path) -> dict[str, tuple[float, float]]:
    sites = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            site = (row.get("site") or "").strip().upper()
            lat = parse_number(row.get("latitude", ""))
            lon = parse_number(row.get("longitude", ""))
            if site and lat is not None and lon is not None:
                sites[site] = (lat, lon)
    return sites

def latest_by_site(obs: list[Observation]) -> dict[str, Observation]:
    latest = {}
    for o in obs:
        old = latest.get(o.site)
        if old is None or o.time > old.time:
            latest[o.site] = o
    return latest

def color_for(vpm: float) -> tuple[int, int, int]:
    # Visualization categories only, not NASA/Space Force safety criteria.
    a = abs(vpm)
    if a < 500:
        return (160, 160, 160)
    if a < 1000:
        return (80, 200, 120)
    if a < 2000:
        return (235, 210, 60)
    if a < 5000:
        return (245, 145, 45)
    return (240, 70, 70)

def build_placefile(
    latest: dict[str, Observation],
    sites: dict[str, tuple[float, float]],
    now: datetime,
) -> str:
    lines = [
        "Title: KSC 1-Min Field Mills",
        "RefreshSeconds: 60",
        "Threshold: 200",
        "; Source: NASA KSC Spaceport Weather Archive FieldMill Export",
        "; OneMinuteMean units: V/m",
        "; Colors are visualization categories only, NOT official launch/lightning criteria.",
    ]

    for site in sorted(latest):
        if site not in sites:
            continue
        o = latest[site]
        lat, lon = sites[site]
        age_min = max(0, int((now - o.time).total_seconds() / 60))
        r, g, b = color_for(o.value_vpm)
        lines.append(f"Color: {r} {g} {b}")
        lines.append(
            f"Place: {lat:.8f}, {lon:.8f}, "
            f"{site} {o.value_vpm:+.0f} V/m "
            f"({o.value_vpm/1000:+.3f} kV/m) "
            f"{o.time:%H%MZ} age {age_min}m"
        )

    lines.append("")
    return "\n".join(lines)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="Local KSC export CSV for testing")
    ap.add_argument("--sites", default="docs/field_mill_sites.csv")
    ap.add_argument("--output", default="docs/ksc_fieldmills.txt")
    ap.add_argument("--json-output", default="docs/ksc_fieldmills.json")
    ap.add_argument("--print-url", action="store_true")
    ap.add_argument("--start", help="UTC start YYYY-MM-DDTHH:MM")
    ap.add_argument("--end", help="UTC end YYYY-MM-DDTHH:MM")
    args = ap.parse_args()

    if args.print_url:
        if args.start and args.end:
            start = datetime.strptime(args.start, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
            end = datetime.strptime(args.end, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
        else:
            end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
            start = end - timedelta(minutes=int(os.getenv("LOOKBACK_MINUTES", "60")))
        print(build_export_url(start, end))
        return

    text = (
        Path(args.input).read_text(encoding="utf-8", errors="replace")
        if args.input else fetch_export()
    )

    obs = parse_ksc_export_csv(text)
    latest = latest_by_site(obs)
    sites = load_sites(Path(args.sites))
    now = datetime.now(timezone.utc)

    placefile = build_placefile(latest, sites, now)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(placefile, encoding="utf-8")

    payload = {
        "generated_utc": now.isoformat(),
        "source": "NASA KSC Spaceport Weather Archive",
        "schema": ["OneMinuteMean", "Date", "Time", "MillNo"],
        "records_parsed": len(obs),
        "latest_station_count": len(latest),
        "station_count_plotted": sum(1 for s in latest if s in sites),
        "observations": [
            {
                "site": o.site,
                "time_utc": o.time.isoformat(),
                "value_vpm": o.value_vpm,
                "latitude": sites.get(o.site, (None, None))[0],
                "longitude": sites.get(o.site, (None, None))[1],
            }
            for o in sorted(latest.values(), key=lambda x: x.site)
        ],
    }
    Path(args.json_output).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(
        f"Parsed {len(obs)} rows; latest stations={len(latest)}; "
        f"plotted={payload['station_count_plotted']}"
    )

if __name__ == "__main__":
    main()
