# Live LPLWS Field Mill Placefile

One-minute LPLWS electric potential gradient observations for GRLevelX.

## Source

The updater fetches the complete latest minute from
`https://codiapi-lplws1.rad.spaceforce.mil/lplws_1min/latest`.
The endpoint was reachable outside RAD during testing on October 16, 2026,
although the supplied guide describes RAD-only access.
No archive export tokens or archive secrets are required.
`KSC_ARCHIVE_RESULT_URL` is no longer used. TLS validation remains enabled,
and transient HTTP/network failures are retried up to three attempts.

`reading_date` and `reading_time` identify the observation in UTC;
`loaded_at` is ingestion time and is not used for observation age.
Values are displayed in V/m, retaining their sign. Null/nonfinite values
are skipped; zero is preserved. Status flags are retained in hover text and
JSON. Their meaning is unconfirmed in the API guide, so X is not automatically
treated as missing or as a quality-control decision.

## Mill locations and coverage

`docs/field_mill_sites.csv` defines the configured mill list. Only mills in
that list are plotted. Valid API coordinates update locations for those mills;
the CSV provides fallback coordinates. The API also returns other IDs at a
repeated location far outside the Cape; these are not automatically added.
Diagnostic JSON retains all parsed latest readings and marks which are plotted.

## Display and URL

https://cyclonecizek.github.io/EFM_GR2_Placefile/ksc_fieldmills.txt

The existing circle icons, signed numeric values, and absolute-magnitude
thresholds are retained:

- Green: below 500 V/m.
- Yellow: 500 to below 1,000 V/m.
- Red: 1,000 V/m or greater.

These are visualization categories, not official launch/lightning criteria.
Hover text includes observation time, age, signed value, and API status flag.

## Updates

GitHub Actions requests updates every five minutes. Scheduling may be delayed.
GR refreshes the published file every 60 seconds. Code changes on main also
trigger the updater; the Pages deployment runs after a successful update.

## Local use

```sh
pip install -r requirements.txt
python -m unittest discover -s tests
python src/ksc_fieldmill_placefile.py
```

Outputs are `docs/ksc_fieldmills.txt` and `docs/ksc_fieldmills.json`.
Use `--input response.json` for a saved API array or
`--input sample_fieldmill_result.csv` for legacy CSV testing.
`LPLWS_API_BASE_URL` optionally overrides the API host.
`EFM_ICON_URL` optionally overrides the published icon URL.
Failures fetching or parsing data stop the workflow before output publication.

## Live MERLIN lightning placefiles

Two additional placefiles share this repository and Pages hosting:

- https://cyclonecizek.github.io/EFM_GR2_Placefile/merlin_cg.txt
- https://cyclonecizek.github.io/EFM_GR2_Placefile/merlin_cc_density.txt

Formatting follows `LaunchWeatherReplay/lib/merlin.ts` and `lib/symbols.ts`:
gold Arial plus signs for CG, and opaque Wingdings dots with a dark outline
at approximately 1 km cell centers for CC. There is no on-map CC caption.
CC detection counts use the same bins: blue 1–4, cyan 5–19, green 20–49,
yellow 50–99, orange 100–249, red 250+. Counts represent detection records,
not clustered flashes. CG signal strength is labeled in source units because
the API guide does not specify physical units.

The live C2C and C2G APIs are queried by observation time in five-minute
chunks, with smaller requests if a chunk exceeds the API event-count limit.
Exact event IDs remove boundary duplicates without merging distinct detections.
`event_datetime` controls placement; original `event_time` is retained in hover
text. Ingestion `epoch_ms` is not used as the event time.

Default trail: 15 minutes. Default radar history: 60 minutes. For minute T,
CC density counts detections in [T−trail,T), using the Replay minute-bin rule.
GR TimeRange is included so both layers also work with recent radar loops.
After generation, future TimeRange entries only expire already-observed
detections and decrease CC density as those events age out; they add no future
detections. A quiet current window produces no current symbols, even if older
lightning exists in the API. HTTP errors fail the updater rather than being
reported as a quiet window. No-event results alone cannot prove feed health.

The separate Update MERLIN Lightning Placefiles workflow requests updates
every five minutes. GR refreshes every minute. A failed job preserves published
outputs; their TimeRange entries still expire. Diagnostic data is published in
`merlin_status.json`, including generation time, window counts, and newest
returned event time. Both updater jobs rebase before pushing to avoid conflicts.

Local generation:

```sh
python src/merlin_placefiles.py
```

`MERLIN_TRAIL_MINUTES` accepts 1–60, and `MERLIN_HISTORY_MINUTES` accepts 0–60.
`MERLIN_C2C_API_BASE_URL` and `MERLIN_C2G_API_BASE_URL` optionally override hosts.
`--now` accepts a UTC timestamp for historical testing; production uses current UTC.
API behavior and matching were checked on October 16, 2026. Actual display
still needs visual confirmation in GR2Analyst on the user's machine.
