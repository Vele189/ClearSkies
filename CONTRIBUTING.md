# Contributing to ClearSkies

Issues and pull requests are welcome. This file covers the parts of the process
that are specific to this project. If you have contributed to a Python and
TypeScript monorepo before, most of it will be unsurprising; the sections on the
methodology and the validation set will not be.

## Getting set up

```bash
cp .env.example .env   # DATABASE_URL and DATABASE_URL_UNPOOLED from your Neon branch
make migrate           # create the schema
make install           # Python venvs and npm dependencies
make check             # the local half of CI
```

The database is a [Neon](https://neon.com) branch, which ships PostGIS, h3 and
pgvector as managed extensions, so there is nothing to build. Take a branch of
your own rather than sharing one. Neon gives two connection strings: the pooled
one is `DATABASE_URL`, which the API and the pipeline use, and the direct one is
`DATABASE_URL_UNPOOLED`, which `make migrate` prefers because the runner holds a
session-level advisory lock that PgBouncer's transaction mode does not keep.

Offline, or if you would rather not depend on a branch being up, `make up`
builds the equivalent container from `infra/postgres`; it compiles h3-pg and
takes several minutes the first time. CI uses the same image. Point
`DATABASE_URL` at it, leave `DATABASE_URL_UNPOOLED` empty, and every command
below is identical. If port 5432 is already in use, set `POSTGRES_PORT` in
`.env`.

[docs/database.md](docs/database.md) has both paths in full.

## What CI enforces

| Check | Command |
|---|---|
| Python lint and format | `ruff check`, `ruff format --check`, in `api`, `etl`, `scoring` and `assistant` |
| Python types | `mypy` in strict mode, in the same four packages |
| Python tests | `pytest`, in the same four packages |
| Adapter contract | `python -m pipeline run fake`, the reference source end to end |
| Tile build | `python -m pipeline tiles` over a fixture, no database needed |
| Nightly plan | `python -m pipeline plan`, which resolves the schedule and pulls nothing |
| Corpus manifest | `python -m corpus check`, Appendix B against the code |
| Frontend build | `npm run build` |
| Frontend lint | `eslint` |
| Frontend types | `tsc --noEmit` |
| Frontend tests | `vitest run` |
| Database image | builds, and all four extensions load |
| Migrations | build the schema from empty, unwind, and rebuild |
| Validation set | pre-registration ordering, and internal consistency |
| Validation gate | `scripts/run_validation.py` over the harness fixture |

`make check` runs most of that locally: the lint, typecheck and test suites for
all four Python packages and the frontend, the adapter contract, the corpus
manifest, the validation-set guards and both gate harnesses. What is left to CI
is the database image, the migration round-trip and the two PostGIS-backed API
test files it runs against that image, the frontend production build, the
nightly plan, and the fixture tile build. Run `make check` before opening a pull
request.

## The three rules that are not about code

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

Run the gate with `make validate SCORES=path/to/scores.json`. It exits non-zero
unless the run cleared the bar, and prints the three permitted responses at the
foot of its report. `make validate-harness` runs the same command over a
synthetic fixture built to fail, which proves the command works without a
database and can never be mistaken for a result.

Flipping `active` on an out-of-state site when scoring coverage extends to its
state is a pre-declared transition, not a change to the set.

Related: no file may be added under `scoring/` in a commit that precedes the
one adding the validation set. CI checks commit ancestry for this.

### Schema changes only ever land as a migration

No `CREATE TABLE` typed into psql, no column added by hand in the Neon console. Every
change is a numbered pair of files in `api/migrations`, written with
`make migrate-new name=...` and applied with `make migrate`.

A schema that exists because somebody ran a statement once cannot be rebuilt,
and a project whose claim is that its output is reproducible from public inputs
cannot have one. The runner checksums applied migrations and refuses to
continue when a released file has been edited: your database already has the
old statement and everyone else's would get the new one. Write the next
migration instead.

`docs/database.md` has the full workflow, the local development paths, and what
each table is for.

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

## The vendored skills

`.claude/skills/` holds Neon's published skill documents, vendored so that an
assistant working in this repository reads the same version everyone else does,
and `skills-lock.json` pins what was fetched. They are reference material and
nothing in the build reads them; update them by re-fetching rather than by
editing in place, and commit the lock file with the change.

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
