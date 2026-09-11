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

## What a good load looks like

`SourcePolicy` decides whether a pull lost too many records. It cannot decide
whether the records it kept are believable, because that needs domain knowledge:
how many air facilities Louisiana has, how high a modeled cancer risk can
credibly go, which fields may be null and how often. That is the second
declaration an adapter makes, `expectations`, and it works the same way:

```python
@register
class EpaTriAdapter(SourceAdapter[TriSite]):
    spec = SourceSpec(name="epa_tri", ...)
    expectations = SourceExpectations(
        source="epa_tri",
        tables=(
            TableExpectations(
                table="tri_release",
                rows=RowCount(800, 40_000, note="Facility x chemical x year, one year."),
                bounds=(Bounds("stack_air", low=0.0, high=50_000_000.0),),
            ),
        ),
    )
```

Declare a row count range, null rates, plausible value bounds, geometry validity
and known code sets, and give every number a `note` saying why it holds that
value. A threshold without a reason gets tightened by whoever is on call and
stops meaning anything.

The gate then runs these, plus the cross-source checks no adapter can make about
itself, and exits non-zero if the night's load should not be scored. See
`docs/quality.md`.

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

The data quality gate (CS-108), which runs the adapters and then judges the
night as a whole:

```bash
python -m pipeline check                 # every registered source, then the gate
python -m pipeline check fake --no-store # one source, nothing persisted
python -m pipeline check --require epa_echo
python -m pipeline history               # what each check has measured over time
```

The nightly run (CS-109), which wraps the gate in a cadence, a ledger and a
promotion. See `docs/nightly.md`:

```bash
python -m pipeline plan                  # what tonight would pull, and why
python -m pipeline nightly               # plan, pull what is due, gate, promote
python -m pipeline nightly --force epa_tri   # ignore one source's cadence
python -m pipeline nightly --all         # ignore every cadence
python -m pipeline runs                  # past nights, and the one being served
```

Checks, the same ones CI runs:

```bash
make etl-check      # from the repository root
```

## Layout

```
etl/
├── pipeline/
│   ├── adapters/
│   │   ├── base.py        the interface: four stages, one class
│   │   ├── registry.py    name to adapter
│   │   └── fake.py        reference implementation
│   ├── policy.py          retry, rate limit, partial failure
│   ├── quality/           the CS-108 gate: thresholds, cross-source checks
│   │   ├── checks.py      the rules, and what applying one means
│   │   ├── expectations.py what each of the five sources should look like
│   │   ├── cross.py       checks no single adapter can make
│   │   ├── gate.py        runs everything, returns one verdict
│   │   └── store.py       every check's measurement, kept per run
│   ├── schedule.py        what tonight pulls, and in what order
│   ├── ledger.py          the night's record, and which run is served
│   ├── runner.py          runs the stages, applies the policy, emits the manifest
│   ├── metadata.py        SourceSpec, KnownGap, Artifact, PullMetadata
│   ├── records.py         NormalizedRecord, Measurement
│   ├── http.py            the one HTTP client
│   ├── sinks.py           where records land
│   ├── snapshots.py       last-good copies, for the stale fallback
│   └── context.py         what an adapter is handed
└── tests/
```
