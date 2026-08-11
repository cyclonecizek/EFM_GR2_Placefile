# KSC 1-Minute Field Mill GRLevelX Placefile

GitHub Actions + GitHub Pages project for converting NASA Kennedy Space Center
Spaceport Weather Archive **1-minute mean electric field mill data** into a
GRLevelX placefile.

## Important source facts

NASA's current KSC Spaceport Weather Archive says:

- Electric field-mill data can be searched/downloaded by time and site.
- The field-mill search product is `OneMinuteMean` in V/m.
- The underlying LPLWS raw historical data are 50-Hz electric-potential-gradient
  observations.
- A normal minute contains 3,000 samples (50 Hz x 60 seconds).
- Since June 10, 2021, the archive computes the 1-minute mean using the actual
  observations available and only when at least 75% of the expected samples
  exist.
- Archive data are provided "as is" and are not under quality control.
- The web archive is public 24/7, but instrument publication can lag; NASA says
  archive updates range from about 15 to 60 minutes depending on instrument.

This project therefore displays the **observation timestamp and age**.

## Why there is a request adapter

The current public interactive FieldMill page exposes the search fields but does
not document a stable public REST/API URL. Rather than hard-code a guessed
private endpoint, the collector supports either:

1. `KSC_ARCHIVE_RESULT_URL` — a working URL copied from a successful archive
   search/download; or
2. `KSC_ARCHIVE_POST_JSON` — the form fields captured from the browser's network
   request, posted to `KSC_ARCHIVE_SEARCH_URL`.

If NASA changes the result layout, the parser exits with an error and refuses
to overwrite the last good placefile.

## Critical setup: field-mill coordinates

`docs/field_mill_sites.csv` is intentionally empty.

Coordinates must come from the authoritative KSC Weather Archive **Instrument
List / interactive map**. The project does not guess station locations. Add:

    site,latitude,longitude,notes
    FM01,28.xxxxxx,-80.xxxxxx,KSC archive instrument list
    ...

The current search page lists 34 field mills and identifies FM13, FM23, and FM33
as decommissioned. The generator excludes those three by default.

## Test locally

    pip install -r requirements.txt
    python src/ksc_fieldmill_placefile.py --input sample_fieldmill_result.csv

When coordinates have been entered, the result is:

    docs/ksc_fieldmills.txt

## GitHub setup

1. Create a repository, e.g. `ksc-fieldmill-placefile`.
2. Upload this package to the repository's `main` branch.
3. Populate `docs/field_mill_sites.csv` using KSC's authoritative instrument list.
4. In **Settings → Secrets and variables → Actions**, add one of:
   - `KSC_ARCHIVE_RESULT_URL`
   - or `KSC_ARCHIVE_POST_JSON`
5. If using POST, optionally set `KSC_ARCHIVE_SEARCH_URL`.
6. Run **Update KSC Field Mill Placefile** manually once.
7. In **Settings → Pages**, choose **GitHub Actions** as the source.
8. Run/deploy Pages.

Your GR URL will be approximately:

    https://YOUR-GITHUB-USERNAME.github.io/ksc-fieldmill-placefile/ksc_fieldmills.txt

Add that URL to the GR Placefile Manager.

## Update cadence

The workflow is scheduled every 5 minutes because GitHub Actions is not a
1-minute continuous scheduler. GR itself is told `RefreshSeconds: 60`, so it
checks the Pages URL each minute and sees a new file whenever Actions publishes
one.

## Display categories

The included colors are **visualization categories only**:

- |E| < 0.5 kV/m
- 0.5–1.0 kV/m
- 1–2 kV/m
- 2–5 kV/m
- ≥5 kV/m

They are **not official NASA/Space Force Lightning Launch Commit Criteria** and
must not be interpreted as launch-safety thresholds.

## Files

- `src/ksc_fieldmill_placefile.py` — archive parser + GR generator
- `.github/workflows/update-fieldmills.yml` — five-minute collector
- `.github/workflows/pages.yml` — GitHub Pages deployment
- `docs/field_mill_sites.csv` — authoritative coordinates go here
- `docs/ksc_fieldmills.txt` — generated GR placefile
- `docs/ksc_fieldmills.json` — generated diagnostic JSON
- `sample_fieldmill_result.csv` — parser test fixture


## v2 updates

This package has now been updated using the actual KSC FieldMill export format
observed in a downloaded archive file:

    OneMinuteMean,Date,Time,MillNo

The parser now treats that as the expected schema and explicitly computes the
newest observation for each mill from the timestamp. It does not trust CSV row
order.

The coordinate table in `docs/field_mill_sites.csv` is now populated from the
user-supplied KSC EFM placefile. FM13 and FM35 are intentionally assigned the
same coordinate because that is how they were represented in the supplied
source placefile.

The remaining automation item is generating/refreshing the encoded KSC
`/FieldMill/Export/<token>` URL for a moving time window. Until that token
generation is solved, set `KSC_ARCHIVE_RESULT_URL` to a current working export
URL as a GitHub Actions repository secret.


## v3 — automatic rolling KSC export token

The collector now generates a fresh KSC `FieldMill/Export/<token>` URL on each
run, using the 2026 token layout reverse-engineered from controlled searches.

Verified alphabet:

    0-25  = A-Z
    26-51 = a-z
    52-59 = 0-7

The timestamp portion is:

    month, day, hour, minute

with one character per component.

The Action uses a rolling 60-minute UTC lookback by default:

    LOOKBACK_MINUTES=60

`KSC_ARCHIVE_RESULT_URL` remains optional as a manual override.

Important: the fixed token fields have only been verified for 2026. The script
will intentionally stop for another year until the token is revalidated.
