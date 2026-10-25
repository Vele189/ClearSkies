# Performance and payload review — CP-23 / CS-408

Measured 2026-10-25 against the live deployment, serving run 85. Every figure
below was measured, not estimated, except where it says otherwise.

## 1. Clicking a hexagon

| | Median | p95 | Max |
|---|---|---|---|
| `GET /hex/{h3}`, 30 cells sampled by hash from run 85 | 474 ms | 711 ms | 764 ms |
| Response size | 11.8 KB | | 17.9 KB |

**Most of that is distance, not work.** These were timed from outside the
United States. Splitting one request apart:

| Endpoint | Database work | Median time to first byte |
|---|---|---|
| `GET /indicators` | none | 307 ms |
| `GET /health` | four light queries | 411 ms |
| `GET /hex/{h3}` | five queries, one spatial | 411 ms |

`/indicators` touches no database, so its 307 ms is almost all the round trip
between the measuring machine and Railway's US East region. The hex panel adds
**about 100 ms** of real work on top. For a reader in Louisiana, a few
milliseconds from Virginia, a click should take roughly 130 ms.

The five queries behind a click (core, indicators, nearby facilities, their
count, health) each cost at most ~30 ms of execution, measured against a
`SELECT 1` baseline. Merging the facility count into the facility list with
`count(*) OVER ()` would save one round trip and one spatial scan, about 15–20
ms. It is worth doing the next time `facilities.py` is touched, and not worth a
release of its own.

## 2. First load of the map

| Asset | Raw | Over the wire |
|---|---|---|
| JavaScript bundle (one file) | 1,364 KB | 454 KB |
| CSS | 127 KB | 25 KB |
| Tile archive, first view (from `pipeline tiles`) | — | ~40 KB |
| Largest single tile | — | 42 KB |
| Whole tile archive (never downloaded whole) | 10.5 MB | — |

The archive is read by HTTP Range requests: the header, the root directory,
then only the tiles in view. The first-view figure is the builder's own report
for the opening zoom, not a browser trace.

**The JavaScript is the one large item, and it is MapLibre.** The bundle is a
single file, so the text-only pages (How it works, Data sources, About) also
download the map library. Route-level code splitting, loading MapLibre only on
the map and hex routes, is the cheap improvement here. It does not help the
map page itself, which needs the library to draw anything.

## 3. Database against the plan

`dev-seed`: **798 MB of the 1 GiB branch limit (78%)**.

| Table | Size | Note |
|---|---|---|
| `census_block` | 197 MB | Only needed to rebuild the crosswalk, which is built. Droppable (CP-27). |
| `hex_indicator` | 144 MB | ~48 MB per scored run; three runs held (81, 84, 85). |
| `hex_score` | 96 MB | ~32 MB per run. |
| `hex` | 83 MB | The grid. |
| `hex_air_quality` | 56 MB | |
| `tract_hex_weight` | 50 MB | The §7 crosswalk, now including zero-population rows. |
| `statute_chunk` | 40 MB | The sealed corpus and its vectors. |

**Each scored run costs about 85 MB**, so the branch holds two more runs before
it hits the limit. Two deletions would recover roughly 280 MB, about a third
of the limit:

1. **`census_block`, 197 MB.** It can be reloaded from the decennial source if
   the crosswalk ever has to be rebuilt.
2. **Run 84, ~85 MB.** Superseded and never served. Its results are recorded
   in `docs/validation/runs/run-84-*.md`. Run 81 should stay, because it is the
   rollback for run 85.

Both are irreversible on this plan and are the owner's call. Neither has been
done.
