# The database

One PostgreSQL instance holds spatial data, vector search, and application
state. This page covers how to get one running, how schema changes reach it,
and what the tables are for.

The methodology paper is the authority on what the numbers mean. Where a column
exists to satisfy a rule, this page and the migration comments name the section
rather than restating the argument.

---

## 1. What has to be installed

Three extensions, and the project does not work without any of them:

| Extension | Used for |
|---|---|
| PostGIS | Facility points, hex boundaries, census polygons, every distance and overlay |
| h3-pg | Ad-hoc H3 queries in psql |
| pgvector | Retrieval over the statute corpus |

**h3-pg is why this is a self-hosted image.** Managed Postgres providers do not
offer it, so `infra/postgres/Dockerfile` builds it from source on top of
`postgres:17-bookworm` and Railway runs that image as the `db` service. The
first build compiles the H3 C library and takes several minutes.

**Nothing in the pipeline depends on h3-pg.** Cell indexes are computed in
Python during the nightly job and stored as text, so the schema uses a domain,
`h3_cell`, rather than the extension's `h3index` type. That is deliberate: it
keeps the data loadable into a stock Postgres, and a test enforces it. The
extension is there for the queries a human writes at a prompt.

---

## 2. Local development

The default path is the container. `docker-compose.yml` builds the same image
Railway does, so a local database and a deployed one differ only in the data
they hold.

```bash
cp .env.example .env
make up          # build the image and wait for initdb to finish
make extensions  # print the extension versions
make migrate     # create the schema
```

`make up` is slow the first time and fast afterwards. If port 5432 is taken,
set `POSTGRES_PORT` in `.env` to something free and change the port in
`DATABASE_URL` to match.

Useful afterwards:

```bash
make psql            # a shell on the local database
make migrate-status  # what is applied, what is pending
make down            # stop the container, keep the data
docker compose down -v   # stop it and destroy the volume
```

### Against a remote database instead

Every migration command reads `DATABASE_URL`, so pointing at a shared
development database on Railway is a matter of setting it. Take the connection
string from the Railway dashboard, under the `db` service's Variables tab, and
use the public proxy hostname rather than the internal one, which only resolves
inside Railway's network.

```bash
DATABASE_URL='postgresql://user:password@host.proxy.rlwy.net:PORT/railway' \
  make migrate-status
```

Two cautions. A shared development database has no per-branch isolation, so a
migration you apply is applied for everyone on it, and `migrate-down` unwinds
their schema too. And Railway's egress is billed, so a full pilot-state load
over the public proxy costs real money where the same load into a local
container costs nothing. Use the container for anything involving bulk data.

---

## 3. How schema changes land

**Only through a migration.** No `CREATE TABLE` typed into psql, no column
added by hand on Railway, no exceptions. A schema that exists because somebody
ran a statement once cannot be rebuilt, and this project's whole claim is that
its output is reproducible from public inputs.

The runner is `api/app/migrate.py` and the files are in `api/migrations`.

### Writing one

```bash
make migrate-new name=add_facility_naics   # writes 00NN_add_facility_naics.{up,down}.sql
$EDITOR api/migrations/00NN_add_facility_naics.up.sql
make migrate
make migrate-status
```

Rules the runner enforces, and why each exists:

- **Files are `NNNN_slug.up.sql` with a matching `.down.sql`.** Anything else
  in the directory is an error rather than a file to skip, because an
  unrecognised file is far more likely to be a migration somebody expected to
  run than a stray note.
- **An applied migration is never edited.** The runner stores a checksum and
  refuses to continue when a file changes underneath it. Your database already
  has the old statement; theirs would get the new one. Write the next migration
  instead.
- **A pending migration may not be numbered below an applied one.** Two
  branches numbering past each other produce this, and applying the lower one
  after the higher gives a database that no fresh run of the set reproduces.
  Renumber the branch.
- **Each file runs in one transaction.** A file whose first line is
  `-- migrate:no-transaction` runs outside one, for `CREATE INDEX
  CONCURRENTLY` and its few relatives, and must hold exactly one statement:
  with no transaction there is nothing to roll back, so a multi-statement
  failure would leave a database the ledger does not describe.
- **Concurrent runners queue.** The runner takes a Postgres advisory lock, so
  two deploys racing to migrate wait for each other rather than interleaving.

### Down migrations

They exist so a review branch can be unwound locally, and CI exercises the
whole set in both directions on every push. Production rolls forward: to undo
a shipped migration, write the next one.

### Applying them to a deployment

The migrations ship inside the `api` service, which is why they live under
`api/` rather than `infra/` — Railway builds that service with Root Directory
`/api`, and nothing outside it reaches the image.

```bash
railway run --service api python -m app.migrate up
```

`make migrate-verify` exits non-zero unless every migration is applied and
unedited, which is the check to run after a deploy.

### The ledger

`schema_migration` holds one row per applied migration with its checksum,
when it was applied, and how long it took. It is created by the runner on
first use, so an empty database needs no bootstrap step.

---

## 4. The schema

Twenty-three tables in five groups, plus the runner's own ledger. Every fact
table carries a `snapshot_id`, and every derived hex table carries a `run_id`,
except `hex_exposure`, which is keyed by the source's own vintage instead
because it holds one interpolation of one release rather than one run's view of
it.

### Provenance (`0002`)

| Table | Grain |
|---|---|
| `source_snapshot` | One download: URL, retrieval time, sha256, vintage |
| `pipeline_run` | One execution of the pipeline, with the methodology version it implemented |
| `pipeline_run_source` | Which snapshot of each source a run read |

Section 6 requires every adapter to record what it fetched and checksum it, and
section 9 requires a run's inputs to survive so a score can be audited later.
Both land here. `pipeline_run.is_current` marks the run the API and the tiles
serve, and a partial unique index allows only one.

### Geography (`0003`)

| Table | Grain |
|---|---|
| `census_tract` | TIGER tract polygon |
| `census_block` | 2020 block polygon with its PL 94-171 population count |
| `hex` | One H3 resolution-8 cell: centroid, boundary, parish, whether it is in the pilot state |
| `tract_hex_weight` | One tract-hex overlap, with the population and area weights |

`tract_hex_weight` is section 7 computed and stored. Extensive quantities
(counts) multiply through `pop_weight`; intensive ones (rates, modeled risks)
are averaged over `population`. Both formulas in that section become one join.
Confusing the two is, per the paper, the most common way this step goes wrong.

### Sources (`0004` to `0008`, and `0011`)

| Table | Grain | Feeds |
|---|---|---|
| `facility` | One regulated facility | E3, F1, F4 |
| `facility_compliance_quarter` | Facility, quarter, program | F2 |
| `enforcement_action` | One formal action | F3 |
| `chemical_toxicity_weight` | One CAS number | E3 |
| `tri_release` | Facility, year, chemical | E3 |
| `tract_exposure` | Tract, AirToxScreen vintage | E1, E2 |
| `hex_exposure` | Hex, AirToxScreen vintage | E1, E2 |
| `monitor` | One OpenAQ location | E4, and the c_monitor confidence term |
| `monitor_measurement` | Monitor, parameter, day | E4 |
| `hex_air_quality` | Hex, parameter | E4, and the c_monitor confidence term |
| `tract_demographics` | Tract, ACS vintage, variable | S1, S2, P1 to P5 |
| `tract_race_ethnicity` | Tract, ACS vintage, variable | nothing; see `0011` |
| `hex_demographics` | Run, hex | The displayed profile |

Four things in here are load-bearing rather than incidental:

`hex_exposure` is `tract_exposure` with section 7 applied, and the pair is the
worked example of the rule that section states. Modeled risks are intensive, so
a hex takes the population-weighted mean of the tract values overlapping it,
never their area-weighted mean and never a rate rebuilt from separately
interpolated parts. The tract table stays the source of record, so a hex value
walks back to the tracts it came from and a change to the interpolation is a
recompute rather than a re-download. Every hex in the pilot state gets a row,
including the ones that got no number: `cancer_risk_absence` says whether the
crosswalk knew of no overlapping tract, the overlapping tracts were absent from
the release, or the overlaps held no population at all, and a check constraint
forbids a row that carries both a value and a reason or neither.

`facility.coordinate_status` implements section 6's positional accuracy rule.
ECHO and TRI coordinates are self-reported and some land in the wrong parish or
in open water. Flagged facilities stay in the table, because the exclusion
count is published; proximity indicators filter on `coordinate_status = 'ok'`.
Deleting them would hide the problem and make the count unrecoverable.

`hex_air_quality` exists so that "nobody has measured here" is a stored fact
rather than a missing row. Section 8.1 gives a hex beyond 25 km of a monitor no
E4 value, never zero and never the state median, and the row carries the
distance to the nearest monitor either way, because that distance is the
`c_monitor` term of section 12 and the detail panel displays it. It is the only
hex-grained table that is not keyed by run: the monitor network is a fact about
a snapshot of OpenAQ, not about a scoring pass. Its `h3` is deliberately not a
foreign key; coverage is computed over an envelope wider than the state
boundary, and every read joins `hex` to it rather than the reverse, so the few
cells outside the grid are inert.

`tract_demographics` is long rather than wide because section 7 forbids
recomputing a rate from independently interpolated parts. Storing each
published numerator and denominator as its own row, with its own margin of
error, and deriving the rate once at the end is the rule; a wide table would
quietly invite the opposite.

`hex_demographics` holds race and ethnicity. They are displayed on every hex
and used in the disparity analysis of section 13.6, and they are never inputs
to the score. Section 14 argues that at length: keeping race out of the
arithmetic is what makes the disparity finding an independent result rather
than a built-in one.

### Race and ethnicity before interpolation (`0011`)

| Table | Grain | Feeds |
|---|---|---|
| `tract_race_ethnicity` | Tract, ACS vintage, variable | nothing |

The tract-level counterpart of those three `hex_demographics` columns, and the
reason it is not simply more rows in `tract_demographics`: that table is the one
every indicator reads. A variable filter is a weak boundary, and a `WHERE
variable LIKE` widened by one character would pull racial composition into an
indicator without anything failing. A separate table takes a join to cross, and
a reviewer sees a join.

The two tables have the same grain and the same columns on purpose, so CS-106
interpolates both through one code path.

### Scores (`0009`)

| Table | Grain |
|---|---|
| `hex_indicator` | Run, hex, indicator: value, percentile, and whether it was observed |
| `indicator_distribution` | Run, indicator: n, the zero block, percentile breakpoints |
| `hex_score` | Run, hex: score, components, confidence terms, or the reason there is no score |

`hex_indicator` keeps a row for absent indicators too, with `observed = false`
and a NULL value. That is what the detail panel renders as a dropped indicator,
so a user always sees which of the fifteen produced the score. Zero and missing
are different facts and the schema keeps them different: a check constraint
forbids only the incoherent direction, an unobserved indicator carrying a value.

`hex_score` is scored or it carries a reason it is not, never both and never
neither, because a map needs to be able to explain every colour it draws.

The contributing facilities on the detail panel are derived at read time from
`facility` and `hex` through the PostGIS index. Materialising them per hex per
run would be the largest table in the database by a wide margin, to save a
distance query over a few thousand rows.

### Statute corpus (`0010`)

| Table | Grain |
|---|---|
| `statute_document` | One authority, with its edition, source URL and retrieval date |
| `statute_chunk` | One section of one document, with its embedding |

Phase 3 work, created now because it is the only reason pgvector is installed
and an extension nothing uses is an extension nobody notices has stopped
working. Appendix B is the manifest and its rules are structural: the corpus
cannot grow at runtime, chunking never crosses a section boundary so a
retrieved passage always carries a complete citable unit, and
`may_reason_from` is false for the two cases that may be cited for context but
not reasoned from.

The embedding dimension is fixed by the model. Changing models means a
migration and a re-embed, which is the intended friction: a corpus holding
vectors from two models returns quietly worse retrievals rather than failing.

---

## 5. Troubleshooting

**`make up` hangs.** The healthcheck waits for the init scripts, not just for
the socket. During `initdb` the entrypoint runs a temporary server on the local
socket only, so a socket check reports ready while extensions are still being
created. Give the first build several minutes and watch
`docker compose logs -f db`.

**`extension "h3" is not available`.** The container is stock Postgres, not the
project image. Rebuild with `docker compose up -d --build db`, and check
`make extensions` prints four rows.

**`migrate` reports drift.** A file changed after it was applied. Restore the
file, or on a local database rebuild from empty with `docker compose down -v`
followed by `make up && make migrate`.

**`type "h3_cell" does not exist`.** Migration `0001` has not run. It creates
the domain as well as the extensions.
