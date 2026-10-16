#!/usr/bin/env python3
"""Live LPLWS one-minute field mill API to GRLevelX placefile."""

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
import time

USER_AGENT = "KSC-FieldMill-GRLevelX/2.0"

@dataclass
class Observation:
    site: str
    time: datetime
    value_vpm: float
    flag: str | None = None
    latitude: float | None = None
    longitude: float | None = None

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


API_BASE = os.getenv("LPLWS_API_BASE_URL", "https://codiapi-lplws1.rad.spaceforce.mil").rstrip("/")


def fetch_observations() -> list[Observation]:
    # Latest returns the entire network for one minute, not just one row.
    for attempt in range(3):
        try:
            r = requests.get(API_BASE + "/lplws_1min/latest", timeout=45,
                             headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            r.raise_for_status()
            return parse_api(r.json())
        except requests.exceptions.RequestException as exc:
            status = exc.response.status_code if exc.response is not None else None
            if attempt == 2 or (status is not None and status < 500 and status != 429):
                raise
            time.sleep(2 ** attempt)


def parse_api(payload) -> list[Observation]:
    if not isinstance(payload, list):
        raise ValueError("LPLWS API response must be a JSON array")
    out = []
    for row in payload:
        if not isinstance(row, dict):
            raise ValueError("LPLWS API records must be objects")
        value = parse_number(row.get("value"))
        site = normalize_site(row.get("field_mill", ""))
        if value is None or site is None:
            continue
        dt = datetime.fromisoformat(f"{row['reading_date']}T{row['reading_time']}".replace("Z", "+00:00"))
        dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        # Flag semantics are unconfirmed. Preserve flags without treating X as missing.
        out.append(Observation(site, dt, value, row.get("flag"),
                               parse_number(row.get("lat")), parse_number(row.get("lon"))))
    if not out:
        raise ValueError("No valid LPLWS API observations parsed")
    return out


def read_observations(path: str) -> list[Observation]:
    text = Path(path).read_text(encoding="utf-8-sig")
    return parse_api(json.loads(text)) if text.lstrip().startswith("[") else parse_ksc_export_csv(text)


def observation_sites(latest, configured):
    # Keep the configured Cape network; do not introduce placeholder API mill IDs.
    sites = dict(configured)
    for site, o in latest.items():
        if (site in configured and o.latitude is not None and o.longitude is not None
                and -90 <= o.latitude <= 90 and -180 <= o.longitude <= 180):
            sites[site] = (o.latitude, o.longitude)
    return sites


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

def default_icon_url() -> str:
    explicit = os.getenv("EFM_ICON_URL", "").strip()
    if explicit:
        return explicit

    repo = os.getenv("GITHUB_REPOSITORY", "").strip()
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"http://{owner}.github.io/{name}/efm_status_icons.png"

    return "http://cyclonecizek.github.io/EFM_GR2_Placefile/efm_status_icons.png"


ICON_URL = default_icon_url()


def category_for(vpm: float) -> tuple[int, tuple[int, int, int], str]:
    """
    Visualization categories based on absolute one-minute mean electric field.

      icon 1 / green  : |EF| < 500 V/m
      icon 2 / yellow : 500 <= |EF| < 1000 V/m
      icon 3 / red    : |EF| >= 1000 V/m

    These are user-selected visualization thresholds, not official
    NASA/Space Force lightning or launch criteria.
    """
    a = abs(vpm)
    if a < 500:
        return 1, (40, 220, 70), "GREEN"
    if a < 1000:
        return 2, (255, 205, 25), "YELLOW"
    return 3, (255, 55, 55), "RED"


def esc_hover(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\r", "")
            .replace("\n", "\\n")
    )


def build_placefile(
    latest: dict[str, Observation],
    sites: dict[str, tuple[float, float]],
    now: datetime,
) -> str:
    lines = [
        "; KSC 1-Min Electric Field Mills",
        "RefreshSeconds: 60",
        "Threshold: 200",
        f'IconFile: 1, 64, 64, 32, 32, "{ICON_URL}"',
        'Font: 1, 12, 1, "Arial"',
        "; Source: Live LPLWS one-minute API",
        "; One-minute electric potential gradient units: V/m",
        "; User visualization thresholds use absolute electric-field magnitude:",
        "; green <500 V/m; yellow 500-999 V/m; red >=1000 V/m.",
        "; These colors are NOT official launch/lightning criteria.",
    ]

    for site in sorted(latest):
        if site not in sites:
            continue

        o = latest[site]
        lat, lon = sites[site]
        age_min = max(0, int((now - o.time).total_seconds() / 60))
        icon_no, (r, g, b), category = category_for(o.value_vpm)

        hover = esc_hover(
            f"KSC Electric Field Mill {site}\n"
            f"1-min Mean: {o.value_vpm:+.0f} V/m ({o.value_vpm/1000:+.3f} kV/m)\n"
            f"Absolute EF: {abs(o.value_vpm):.0f} V/m\n"
            f"Category: {category}\n"
            f"Observation: {o.time:%Y-%m-%d %H:%MZ}\n"
            f"Age: {age_min} min\n"
            f"API status flag: {o.flag or 'none'} (meaning unconfirmed)\n"
            f"Source: Live LPLWS one-minute API"
        )

        lines.append(f"Object: {lat:.8f}, {lon:.8f}")
        # Baked-color concentric-circle status icon.
        lines.append(f'Icon: 0, 0, 0, 1, {icon_no}, "{hover}"')
        # Numeric 1-minute mean directly below the icon, matching category color.
        lines.append(f"Color: {r} {g} {b}")
        lines.append(
            f'Text: -18, -34, 1, "{o.value_vpm:+.0f}", "{hover}"'
        )
        lines.append("End:")

    lines.append("")
    return "\n".join(lines)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="Local LPLWS API JSON or legacy KSC export CSV")
    ap.add_argument("--sites", default="docs/field_mill_sites.csv")
    ap.add_argument("--output", default="docs/ksc_fieldmills.txt")
    ap.add_argument("--json-output", default="docs/ksc_fieldmills.json")
    args = ap.parse_args()
    obs = read_observations(args.input) if args.input else fetch_observations()
    latest = latest_by_site(obs)
    sites = observation_sites(latest, load_sites(Path(args.sites)))
    now = datetime.now(timezone.utc)

    placefile = build_placefile(latest, sites, now)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(placefile, encoding="utf-8")

    payload = {
        "generated_utc": now.isoformat(),
        "source": "Live LPLWS one-minute API",
        "schema": ["reading_date", "reading_time", "field_mill", "value", "flag", "lat", "lon"],
        "records_parsed": len(obs),
        "latest_station_count": len(latest),
        "station_count_plotted": sum(1 for s in latest if s in sites),
        "observations": [
            {
                "site": o.site,
                "time_utc": o.time.isoformat(),
                "value_vpm": o.value_vpm,
                "flag": o.flag,
                "plotted": o.site in sites,
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
