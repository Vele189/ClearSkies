# ClearSkies

**Cumulative environmental burden, mapped and explained — plus a drafting assistant that turns the data into cited advocacy documents.**

ClearSkies joins EPA compliance records, toxic release inventories, modeled air toxics exposure, measured air quality, and census demographics into a single burden score for every hexagon on a map. Click a hex and you see exactly why it scored the way it did, which facilities contributed, and how confident the score is. From there you can generate a draft public comment letter, agency complaint, community briefing, or journalist fact sheet — grounded in public records, with every citation verified before the draft is shown.

> **Status: Phase 0 (foundations).** The methodology paper and the pre-registered validation set are written; no pipeline or scoring code exists yet. **Pilot state: Louisiana**, locked. See [Roadmap](#roadmap) for what exists and what doesn't.

---

## Why this exists

Low-income and minority communities in the US are disproportionately located near polluting industrial facilities. The data proving this is public, but it is scattered across several government databases, each with its own format and quirks, and none of it is easy for a non-specialist to read.

Three gaps, three answers:

| Gap | What ClearSkies does |
|---|---|
| The data isn't joined up. Compliance records, release inventories, air quality, and demographics live in separate systems. | Pluggable adapters normalize all five sources into one PostGIS database on a shared H3 hexagon grid. |
| Existing tools are read-only. They show you a number and stop. | Every score decomposes into its inputs, its contributing facilities, and a confidence value. |
| Advocacy is expensive. A well-cited public comment takes hours of skilled work. | A drafting assistant produces a first draft in seconds, with citations checked against real records before you ever see them. |

---

## How it works

### Data ingestion

Five public sources, one adapter each:

- **EPA ECHO / ICIS** — facilities, permits, violations, enforcement actions
- **EPA TRI** — annual toxic release volumes by facility
- **EPA NEI / AirToxScreen** — modeled air toxics exposure, the primary pollution input because it covers every area evenly
- **OpenAQ** — measured daily air quality, carrying a coverage flag where sensors are sparse
- **US Census ACS** — income, poverty, race and ethnicity, linguistic isolation, age, housing burden

A nightly GitHub Actions job validates and loads everything into PostGIS. Census values move from tracts to hexagons by dasymetric areal interpolation, so population is not misassigned when a tract straddles a hex boundary.

### Scoring

Every area is bucketed into an H3 resolution-8 hexagon, roughly 0.7 km², which puts about 150,000 populated hexagons in Louisiana. Cell indexes and boundaries are computed in Python during the nightly job and stored, so the pipeline does not depend on `h3-pg` being present; the extension is there for ad-hoc queries. The burden score follows the structure used by CalEnviroScreen and EJScreen: a pollution burden component multiplied by a population vulnerability component, with each indicator expressed as a statewide percentile rank. Every hex also carries a confidence value reflecting data coverage and age.

The methodology is written before the code. The output is validated against ten well-documented Louisiana environmental justice sites, from Reserve and Mossville to Gordon Plaza, and the score is expected to flag them on its own, without being tuned to them. The validation set is committed before any scoring code and is append-only. Weights change only through a documented revision of the methodology paper, never to make a case pass.

### The map

A React and MapLibre GL frontend serves scored hexes as static vector tiles. Clicking a hex opens a panel with a waterfall breakdown of the sub-scores, the contributing facilities each linking to its EPA record, the confidence value, and a short explainer covering what the score means and what it does not.

Nothing on the screen is a black box. Every number traces back to a source record.

### The drafting assistant

Four document types: public comment letter, agency complaint draft, community briefing sheet, journalist fact sheet.

Four guardrails that keep it honest:

1. **Structured output.** Pydantic schemas with a required citations field. No free-form prose escapes the schema.
2. **Curated retrieval.** Statutes come only from a versioned corpus — Clean Air Act, Title VI, the Louisiana Environmental Quality Act and the state's public trust provision — retrieved via pgvector. The model cannot cite a statute that isn't in the corpus.
3. **Citation verification.** Every record ID and statute section is checked against the database before the draft is rendered. A draft with an unverifiable citation is rejected, not shown with a warning.
4. **Facts-only language rules.** Documented facts and statistical patterns only. Never claims about corporate intent.

Every output is labeled a draft requiring human review. There is no send button and no publish path anywhere in the system, by design.

---

## Tech stack

Every component is open source. Two line items cost money: a Railway Hobby plan and LLM API usage.

| Layer | Choice |
|---|---|
| Languages | Python 3.12, TypeScript |
| Geospatial | GeoPandas, Shapely, h3-py |
| Database | PostgreSQL + PostGIS + h3-pg + pgvector, custom image on Railway |
| ETL orchestration | GitHub Actions scheduled workflow |
| Backend API | FastAPI |
| Vector tiles | Static PMTiles on Cloudflare R2 |
| Object storage | Cloudflare R2 (tiles, raw source snapshots as Parquet) |
| LLM integration | Pydantic AI |
| LLM provider | Anthropic or OpenAI |
| Frontend | React, TypeScript, Tailwind, MapLibre GL |
| Basemap | OpenFreeMap or Protomaps |
| Hosting | Railway (frontend, API, database) |
| Monitoring | Railway logs plus an external uptime check |

One database handles spatial queries, vector search, and application data.

**Why the split.** Railway runs everything that is a running process: the frontend, the API, and the database. One platform, one bill, one deploy config. Railway's CDN is enabled on the frontend service, so static assets are served from the edge and cache hits cost no egress and never wake the container.

**Why tiles are the exception.** PMTiles are read with HTTP Range requests against one large archive, which is a poor fit for an edge cache keyed on whole URLs, and Railway bills egress at $0.05/GB. R2 charges nothing for egress and is built for exactly this access pattern. Tiles are also the only asset in the project large enough for that difference to matter.

**Enable the CDN on the frontend service only.** The draft endpoint is a POST that returns per-hex generated documents, and an edge cache in front of it buys nothing and risks serving one request's output to another.

**Cost:** Railway Hobby at $5/month plus LLM API usage. Everything else is free.

**Three Railway services, one repo.** Each service points at the same GitHub repository with a different Root Directory, and Watch Paths scoped so a frontend commit does not redeploy the API.

| Service | Root directory | Built from |
|---|---|---|
| `web` | `/web` | Vite build, CDN enabled |
| `api` | `/api` | FastAPI, CDN disabled |
| `db` | `/infra/postgres` | Dockerfile, volume at `/var/lib/postgresql/data` |

Service configuration lives in `.railway/railway.ts` rather than `railway.json`, which Railway deprecated with a hard cutoff of 2026-12-01. Generate it with `railway config pull` after the services exist rather than hand-writing it, and note that a service cannot be managed by the dashboard and by infrastructure as code at the same time.

---

## Repository layout

What exists today:

```
clearskies/
├── docs/
│   ├── methodology.md            Indicators, weights, normalization, validation
│   └── validation/sites.yml      Pre-registered validation set (append-only)
├── api/                          FastAPI service
│   ├── app/indicators.py         The fifteen indicators, one declaration
│   ├── app/schemas.py            Response models mirroring the methodology
│   └── tests/
├── web/                          React, MapLibre GL, PMTiles
├── infra/postgres/               Custom image: PostGIS + h3-pg + pgvector
├── scripts/                      Pre-registration and fixture guards
├── .railway/railway.ts           Railway service definitions
├── .github/workflows/            CI and the nightly ETL job
├── .github/ISSUE_TEMPLATE/       Bug, scoring, methodology, data source
├── CONTRIBUTING.md
├── LICENSE                       MIT
├── Makefile
└── docker-compose.yml            Local database only
```

`scoring/` is deliberately absent. The methodology requires the validation set to be committed before any scoring code exists, and CI enforces that ordering by comparing commit history. Creating the directory early would defeat the check it is meant to pass.

Still to come: `etl/` with the five adapters and the interpolation step (Phase 1), `scoring/` (Phase 2), `assistant/` with the statute corpus and citation verifier (Phase 3).

---

## Running it locally

**Prerequisites:** Python 3.12, Node 20+, Docker.

```bash
cp .env.example .env
make up            # build and start Postgres with all three extensions
make extensions    # print the extension versions, proving the image is right
make install       # Python venv and npm dependencies
make api           # FastAPI on :8000, docs at /docs
make web           # Vite dev server on :5173
make check         # lint, typecheck, tests, pre-registration guard
```

`make up` builds `infra/postgres` from source, which compiles h3-pg and takes several minutes the first time.

The map renders the basemap and the API answers `/health` and `/indicators`, but no hexagon is scored yet. `/hex/{h3}` validates the cell and reports that the pipeline has not run rather than inventing a score. The frontend shows a banner saying the same. That is Phase 0 behaving correctly.

---

## API

Published OpenAPI docs at `/docs`. The endpoint that matters most:

```
GET /hex/{h3}
```

Returns the burden score, every sub-score with its percentile rank, the confidence value, the contributing facilities with their EPA record links, and the demographic profile. This is the same payload the map panel renders, so anything visible in the UI is available programmatically.

---

## Adding a data source

Adapters implement a single interface: fetch, validate, normalize to the hex grid, and declare freshness. Adding a source means writing one module in `etl/adapters/`, registering it, and documenting it in `docs/provenance.md`. The README in that directory carries the full contract.

---

## Roadmap

Five phases, each ending in something demoable. No fixed dates; a phase is done when its exit condition is met.

| Phase | Focus | Exit condition |
|---|---|---|
| 0. Foundations | Methodology v0, pilot state, validation cases, repo and CI, adapter interface | Methodology written, repo builds |
| 1. Data pipeline | All five adapters, areal interpolation, quality checks, nightly job | Full pilot state dataset in PostGIS |
| 2. Score and map | Scoring engine, confidence, validation run, tiles, API, map, explain panel | Live map, 8 of 10 validation sites in the top decile |
| 3. Drafting assistant | Statute corpus, retrieval, schemas, prompts, citation verifier, draft viewer | Zero unverifiable citations in a 50-draft audit |
| 4. Polish and launch | Accessibility, rate limiting, monitoring, docs, model card, write-up | Public URL and repo live |

Phases 0 through 2 stand on their own as a complete piece. Phase 3 is the most distinctive part and is worth finishing, but the project does not depend on it.

---

## Limitations and honest caveats

- **Louisiana only.** Percentiles are Louisiana percentiles, so a Louisiana 90th percentile is not a national one. National coverage is out of scope for the first release.
- **Modeled exposure is modeled.** AirToxScreen estimates, they are not measurements. Measured OpenAQ data is sparser and unevenly distributed, which is exactly why it is a secondary input with a coverage flag.
- **Correlation is not causation.** A high burden score describes a pattern in public data. It is not a finding of wrongdoing by any facility or operator.
- **Drafts are drafts.** Every generated document requires human review before use. Nothing here is legal advice, and nothing is sent or published automatically.
- **A low score is not a clean bill of health.** It can mean low burden, or it can mean the indicators that would have caught the burden are missing. Read the confidence value alongside the score.
- **No health outcome data.** Asthma, low birth weight, and cardiovascular indicators have no free tract-level national source, so the vulnerability side rests on age structure and economic hardship alone. This is the largest gap in the specification.
- **Race is recorded but not scored.** Keeping it out of the arithmetic is what makes the disparity finding an independent result rather than a built-in one. The methodology paper argues this at length.

Out of scope for this release: national coverage, non-US data, user accounts, mobile apps, automatic sending or publishing, legal briefs, and formal legal or community review. The methodology paper notes where the last of those would belong in a production build.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Two rules there are not about code and are easy to trip over.

Scoring weights and indicator choices are argued in `docs/methodology.md`, not in code comments, so a disagreement about the score is a disagreement about that document. And the validation set is closed: `docs/validation/sites.yml` is read-only, and a criterion that fails is never answered by adjusting a weight until it passes.

`make check` runs everything CI does apart from the database image build.

---

## License and data

MIT, see [LICENSE](LICENSE). Every upstream dataset is US public-domain government data; `docs/provenance.md` records each source, its last pull, and its known gaps.
