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
