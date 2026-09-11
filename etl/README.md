# Ingestion

Five public sources, one interface. This directory holds the adapter contract,
the machinery every adapter inherits, and a reference implementation you can
copy.

Phase 0 ships the interface and the reference adapter. Phase 1 adds the five
real sources; each is one module in `pipeline/adapters/` and one import line.

## The four stages

An adapter declares what it is and implements three methods. The runner calls
them in order.

| Stage | Signature | Does |
|---|---|---|
| fetch | `async fetch(ctx) -> FetchResult[Raw]` | Download through `ctx.http`, parse into raw records, declare the vintage |
| validate | `validate(record, ctx) -> None` | Accept, or raise `RecordRejected` |
| normalize | `normalize(record, ctx) -> Iterable[NormalizedRecord]` | Source geography and units become project geography and units |
| load | `async load(records, ctx) -> int` | Inherited. Batches by table and upserts on the natural key |

Everything else is not yours to write:

- **Retries.** `ctx.http` retries transient failures with exponential backoff and
  full jitter, honours `Retry-After`, and never retries a 404.
- **Rate limiting.** A token bucket shared by every request the run makes.
- **Checksums and snapshots.** Every download is hashed and stored, which is what
  makes the stale fallback possible.
- **Stale fallback.** If upstream is unreachable, the runner re-runs `fetch`
  against the last good snapshot, reports `stale`, and lets the recency term in
  the confidence score degrade. It never substitutes a different source.
- **Partial failure.** Rejections are counted against one tolerance rule. Over
  the line, nothing is loaded at all.
- **Transactions.** The runner opens the sink, loads, and commits the data and
  its manifest together, or rolls both back.
- **Provenance.** Every run produces a `PullMetadata`, including runs that fail.

All of it is configured by one `SourcePolicy` (`pipeline/policy.py`). The field
expected to vary between sources is the rate limit, because each upstream
publishes its own. Change anything else and say why in the commit message.

## Credentials

Most sources need none. Where one does, the adapter names it and reads it from
`ctx.credentials`; it never touches `os.environ`, so a test can run it without
arranging the environment and a missing key is a stated requirement rather than
a surprise at three in the morning. `pipeline/__main__.py` holds the one table
mapping a credential name to its environment variable.

| Source | Credential | Environment variable |
|---|---|---|
| `census_acs` | `census_api_key` | `CENSUS_API_KEY` |

Two rules for a credential in an adapter:

- Pass it as `ctx.http.get(url, secret_params={...})`, never in `url` or
  `params`. `Artifact.url` is published verbatim in `docs/provenance.md`, and it
  is also the snapshot key and the text of the retry log line.
- Since `url` is the snapshot key, a source paged or chunked over several
  requests has to vary `url` rather than `params`. Two calls sharing a URL share
  one snapshot, and a later stale night would replay one response for all of
  them.

A run with no key **fails**; it does not fall back to the last good snapshot. An
absent credential is a broken deployment, and `stale` would make it look
survivable.

## How to add a new data source

Worked example to copy: `pipeline/adapters/fake.py`, about 130 lines including
comments, with its tests in `tests/test_fake_adapter.py`.

**1. Declare the source.** Subclass `SourceAdapter[Raw]`, where `Raw` is whatever
your parser produces — a `dict[str, str]` for CSV, a dataclass for JSON. Give it
a `SourceSpec`: registry name, title, homepage, cadence, native geography, and
the indicator ids it feeds.

```python
@register
class EpaTriAdapter(SourceAdapter[dict[str, str]]):
    spec = SourceSpec(
        name="epa_tri",
        title="EPA Toxics Release Inventory",
        homepage="https://www.epa.gov/toxics-release-inventory-tri-program",
        cadence="annual, ~18-month lag",
        native_geography="point (facility lat/lon)",
        provides=("E3",),
    )
```

**2. Write `fetch`.** Request through `ctx.http.get(url)`; never construct your
own HTTP client. Return a `FetchResult` carrying the raw records, the artifacts
you downloaded, and the **vintage** — the upstream release identifier, not the
download time. `2023` for a TRI reporting year, `acs5_2019_2023` for a Census
release. Downloading a six-year-old file today does not make it current, and the
confidence score is computed from the vintage.

Raise `PermanentSourceError` if the dataset moved, was withdrawn, or lost a
column you need. Raise `TransientSourceError` if it looks temporarily unwell.
Do not catch either in order to return partial data quietly.

If the source needs a key, ask the context for it: `ctx.credential("openaq_api_key")`.
Never read `os.environ` from an adapter. The name maps to an environment
variable in `CREDENTIAL_ENV` in `pipeline/__main__.py`, which is the one place
in the package that reads the environment, and a missing key becomes a
`PermanentSourceError` — a failed pull with a legible reason, not a crash that
takes the other sources down with it.

**3. Write `validate`.** One record at a time. Raise `RecordRejected` with a
reason short enough to be a useful histogram key: `"latitude outside pilot
state"`, not the row itself. Validate what makes a record unusable, not what
makes it unusual — a facility reporting zero releases is valid, a facility whose
coordinates fall in open water is not.

**4. Write `normalize`.** Turn one accepted record into zero or more
`NormalizedRecord`s. Two rules the types enforce where they can:

- A missing value is `Measurement.absent()`, never `Measurement.of(0.0)`. Zero
  releases is an observation; no reported value is an absence. Imputing one to
  the other pulls unmonitored high-burden areas toward the middle, which is the
  failure this project exists to avoid.
- The natural key must be stable across runs, so tonight's pull updates last
  night's rows instead of duplicating them. A repeated key inside one pull fails
  the run.

**4a. If your source is tract-level, use `pipeline/interpolate.py`.** Methodology
section 7 has two formulas and picking the wrong one is, per the paper, the most
common error in this step. Counts sum across space and are apportioned through
`apportion`; rates, ratios and modeled risks do not sum and are combined by
`population_weighted_mean`. Neither area-weights anything, and a rate with a
published numerator and denominator has both apportioned and the division done
once at the end. Both return a value for **every** hex you ask about, plus a
`Coverage` saying how many came back absent and why — put that in the manifest
from `fetch`, because the runner asks for known gaps before the first record is
normalized and a count discovered later can never be published.

**5. Register it.** Add the import to `pipeline/adapters/__init__.py`. The
`@register` decorator does the rest, and `python -m pipeline sources` will list
it.

**6. Document it.** Add a row to `docs/provenance.md` recording the source URL,
retrieval date, and known gaps. `PullMetadata.provenance_row()` generates it, so
the nightly job can keep the page honest rather than leaving it to drift.

**7. Test it.** Serve a small fixture through `httpx.MockTransport`, as
`fixture_transport()` does, and assert on the manifest. No test in this package
touches the network. Cover at least: a clean pull, a row your validator should
reject, and a missing value that must not become a zero.

## Standard metadata

Every run emits a `PullMetadata`, whatever its outcome. The five facts the
interface requires of an adapter:

| Field | Meaning |
|---|---|
| `source` | Registry name, from the spec |
| `vintage` | Upstream release identifier, from `FetchResult` |
| `pulled_at` | When the run started, from `ctx.now`, timezone-aware |
| `counts` | Fetched, validated, rejected, normalized, loaded |
| `known_gaps` | What this pull does not cover, and which indicators that degrades |

The runner adds artifacts and checksums, a sample of rejections with a reason
histogram, the duration, and notes.

## Run statuses

| Status | Meaning | Exit code |
|---|---|---|
| `ok` | Every record survived | 0 |
| `partial` | Some records were rejected, within tolerance; the rest were loaded | 0 |
| `stale` | Upstream was unavailable; the last good snapshot was reused | 0 |
| `failed` | Nothing was loaded and the sink was rolled back | 1 |

## Running it

```bash
python -m pipeline sources              # what the registry knows about
python -m pipeline run fake             # the reference adapter, no network needed
python -m pipeline run fake --json      # the full manifest
python -m pipeline run fake --dry-run   # fetch and normalize, write nothing
```

Checks, the same ones CI runs:

```bash
make etl-check      # from the repository root
```

## Tracts to hexes

Three of the five sources are tract-level, and methodology section 7 moves them
onto the hex grid through an ancillary layer of 2020 Decennial block
populations rather than by area share. That transformation is
`pipeline.dasymetric`, and it is not an adapter: it reads tables that adapters
filled and writes `tract_hex_weight`.

```python
from pipeline.dasymetric import build

crosswalk, check = await build.build_and_verify(conn, state_fips="22", acs_vintage="2019-2023")
print(crosswalk.describe())
print(check.describe())  # the statewide total, and whether it closed
```

`build_and_verify` builds the crosswalk county by county, storing each inside
its own transaction, and then re-derives the statewide population total from
the rows it wrote. It raises `ReconciliationFailed` rather than returning a
crosswalk whose totals did not close.

Two things worth knowing before running it. The crosswalk needs `census_block`
populated, which is CS-112 and is not yet written; until then the arithmetic is
tested but has no data to run on. And the extensive/intensive distinction is
enforced, not advised: apportioning a rate or averaging a count raises
`KindMismatch`, because section 7 calls confusing the two the most common
source of error in this step.

## Layout

```
etl/
├── pipeline/
│   ├── adapters/
│   │   ├── base.py        the interface: four stages, one class
│   │   ├── registry.py    name to adapter
│   │   ├── fake.py          reference implementation
│   │   ├── echo.py          EPA ECHO/ICIS: facilities and compliance (F1-F4)
│   │   ├── tri.py           EPA TRI: reported chemical releases
│   │   ├── airtoxscreen.py  EPA AirToxScreen   (E1, E2)
│   │   ├── openaq.py        OpenAQ: measured PM2.5 and monitor coverage (E4)
│   │   └── census_acs.py    US Census ACS      (S1-S2, P1-P5)
│   ├── interpolate.py     section 7: tract values onto the hex grid
│   ├── dasymetric/        methodology section 7: tracts to hexes
│   │   ├── weights.py     the crosswalk, built from 2020 block populations
│   │   ├── quantities.py  extensive vs intensive, and margins of error
│   │   ├── interpolate.py the two section 7 formulas, and derived rates
│   │   ├── reconcile.py   statewide totals, and the tolerance they must meet
│   │   ├── postgis.py     the block-hex intersection, and storing the result
│   │   └── build.py       the order they run in, county by county, per state
│   ├── policy.py          retry, rate limit, partial failure
│   ├── runner.py          runs the stages, applies the policy, emits the manifest
│   ├── metadata.py        SourceSpec, KnownGap, Artifact, PullMetadata
│   ├── records.py         NormalizedRecord, Measurement
│   ├── http.py            the one HTTP client
│   ├── sinks.py           where records land
│   ├── snapshots.py       last-good copies, for the stale fallback
│   └── context.py         what an adapter is handed
└── tests/
```
