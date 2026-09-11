# Provenance

Every number on the map traces back to a file someone can download. This page
records which file, from where, when, and what it is known not to cover.

The table is generated, not hand-written. Each adapter run produces a
`PullMetadata`, and `PullMetadata.provenance_row()` renders the row below. A
hand-maintained provenance page is a provenance page that stops matching the
data.

The nightly job regenerates it and commits the result, so the page cannot drift
from what was actually loaded. Only the block between the two generated markers
is rewritten; everything else here is prose. To regenerate it by hand:

```bash
cd etl && python -m pipeline provenance --page ../docs/provenance.md
```

**This page shows the latest pull, which is not the same as the latest
successful one.** If last night's ECHO pull failed, the row below says `failed`
rather than reverting to the last row that went well. A green row from three
nights ago would tell a reader the data is current when it is not.

**Every pull is kept, not just the one shown.** The row below answers "where
does this number come from today". A reader checking a claim made last month
needs last month's manifest, so each pull is recorded in `source_pull` and its
two child tables (migration 0016) and the history is queryable per source. The
same content is served as JSON at `GET /provenance`, which is what the map's
detail panel reads; `GET /provenance?source=epa_echo` returns that source's
history newest first.

Columns:

| Column | Meaning |
|---|---|
| Source | Registry name of the adapter, from its `SourceSpec` |
| Vintage | The upstream release identifier: a reporting year, a release version, a date. Not the download time |
| Pulled | When the run started, UTC |
| Records | Rows that reached the database |
| Status | `ok`, `partial`, `stale`, or `failed`. See etl/README.md |
| Checksum | First twelve hex characters of the SHA-256 of each downloaded artifact |
| Known gaps | What the pull does not cover |

## Latest pull per source

<!-- BEGIN GENERATED PROVENANCE -->

| Source | Vintage | Pulled | Records | Status | Checksum | Known gaps |
|---|---|---|---|---|---|---|

_No pipeline run has happened yet. Phase 1 wires the five adapters into the
nightly job and this table fills itself in._

<!-- END GENERATED PROVENANCE -->

## The five sources

Pinned vintages, cadences and native geographies are argued in
`docs/methodology.md` section 6. Summarised:

| Source | Provides | Native geography | Cadence |
|---|---|---|---|
| EPA ECHO / ICIS | Facilities, permits, inspections, violations, enforcement | Point | Weekly upstream |
| EPA TRI | Annual on-site air releases | Point | Annual, ~18-month lag |
| EPA AirToxScreen | Modeled cancer risk and respiratory hazard | Census tract | Every 1–2 years, ~3-year lag |
| OpenAQ | Measured PM2.5 | Point (monitor) | Daily |
| US Census ACS 5-year | Income, poverty, education, language, age, housing | Census tract | Annual, 5-year pooled |

## Why checksums

Several EPA environmental justice datasets were withdrawn from public EPA
hosting during 2025. Adapters therefore record the exact URL and date they used
and hash what they downloaded. The hash is what lets a later run tell "upstream
republished the data" from "upstream is serving the same file at a new address",
and it is what makes the stale fallback trustworthy: a run marked `stale` reused
bytes whose checksum is recorded here.

## Missing is not zero

A gap recorded on this page is not a defect being excused. It is the difference
between a value that is absent and a value that is zero, carried forward so the
confidence term (methodology section 12) and the hex drill-down panel can both
show it. No adapter imputes a missing value to zero or to the median.
