# Contributing to ClearSkies

Issues and pull requests are welcome. This file covers the parts of the process
that are specific to this project. If you have contributed to a Python and
TypeScript monorepo before, most of it will be unsurprising; the sections on the
methodology and the validation set will not be.

## Getting set up

```bash
cp .env.example .env
make up        # Postgres with PostGIS, h3 and pgvector; builds from source
make install   # Python venv and npm dependencies
make check     # everything CI runs
```

`make up` compiles h3-pg and takes several minutes the first time. If port 5432
is already in use, set `POSTGRES_PORT` in `.env`.

## What CI enforces

| Check | Command |
|---|---|
| Python lint and format | `ruff check`, `ruff format --check`, in `api` and `etl` |
| Python types | `mypy` in strict mode, in `api` and `etl` |
| Python tests | `pytest`, in `api` and `etl` |
| Adapter contract | `python -m pipeline run fake`, the reference source end to end |
| Frontend lint | `eslint` |
| Frontend types | `tsc --noEmit` |
| Frontend tests | `vitest run` |
| Database image | builds, and all four extensions load |
| Validation set | pre-registration ordering, and internal consistency |

`make check` runs everything above except the database image build. Run it
before opening a pull request.

## The two rules that are not about code

### Scoring disagreements go to the methodology paper first

Indicator choices, weights, normalization, and aggregation are argued in
`docs/methodology.md`, not in code comments. A pull request that changes a
weight without a corresponding revision to that document, including an entry in
its changelog, will be asked to add one.

The reason is that a cumulative burden score has enormous latitude in these
choices, and a score adjusted until it agrees with the author's expectations
proves nothing. Making every change argue for itself in one reviewable document
is what keeps that latitude visible.

### The validation set is closed

`docs/validation/sites.yml` is read-only. Sites are never added, removed, or
re-anchored, and criteria are never loosened. `scripts/check_validation_set.py`
re-derives every cell list from its anchor and fails CI if they disagree.

If a validation criterion fails, the permitted responses are: fix a defect in
the code, fix a defect in the data handling, or revise the methodology with a
rationale that stands independently of the validation outcome and re-run every
check from the beginning. Adjusting a weight because it makes a site pass is
not one of them.

Flipping `active` on an out-of-state site when scoring coverage extends to its
state is a pre-declared transition, not a change to the set.

Related: no file may be added under `scoring/` in a commit that precedes the
one adding the validation set. CI checks commit ancestry for this.

## Adding a data source

Adapters implement one interface with four stages: fetch, validate, normalize
onto the hex grid, and load. Adding a source means a module in
`etl/pipeline/adapters/`, one import line, and an entry in `docs/provenance.md`
recording the source URL, retrieval date, and known gaps. The full contract and
a worked example are in [`etl/README.md`](etl/README.md); the reference
implementation runs against a fixture with `make ingest-fake`.

Do not write a retry loop, a rate limiter, or a partial-failure rule inside an
adapter. All three are declared once in `etl/pipeline/policy.py` and applied by
the runner. If a source genuinely needs different numbers, override the policy on
the adapter class and say why in the commit message; the field expected to vary
is the rate limit, because each upstream publishes its own.

Two rules that have bitten this project already. An adapter records the exact
URL and date it used and checksums what it downloaded, because several EPA
datasets have moved or been withdrawn. And a missing value is stored as missing,
never as zero. An unmonitored area is uncertain, not clean, and imputing it to
zero or to the median would systematically pull unmonitored high-burden areas
toward the middle. That is the failure this project exists to avoid. The
`Measurement` type makes the second rule hard to break by accident: an absent
measurement cannot carry a value, and an observed one cannot be empty.

## Style

Python is formatted by ruff at 100 columns and type-checked by mypy in strict
mode. TypeScript is checked by eslint with type-aware rules; `any` is an error
outside the API client, which is the one place untyped response bodies are
narrowed.

Comments should explain why, not what. Several in this codebase record a
constraint that is not obvious from the code, such as why the container
healthcheck uses TCP rather than the local socket. Those are worth keeping.

## Reporting a scoring problem

If a hexagon looks wrong, the most useful report includes its H3 index, what
you expected, and what the drill-down panel shows. `GET /hex/{h3}` returns the
same payload the panel renders, including which indicators were dropped and
why, which is usually enough to tell a data problem from a scoring problem.
