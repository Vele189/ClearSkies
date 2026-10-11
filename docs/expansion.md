# Expansion

Adding states to a score that was specified for one.

This document covers what has to be true before a second state's rows land, in
what order states should arrive, and what each one buys. `docs/methodology.md`
section 9 is the authority on percentiles and section 4 on why Louisiana was
the pilot; nothing here may move a cut point or re-rank a published score
without a methodology revision.

**Status: proposal.** The schema work in section 2 is written (migrations 0030
and 0031) and unapplied. No second state's data has been loaded.

---

## 1. The constraint, and the one that is not the constraint

The Neon branch limit is 1 GiB of logical size, per branch. `dev-seed` is at
**483 MB**, so there is **541 MB** of headroom, and the plan upgrade on
2026-10-15 removes the ceiling entirely.

Step 0 itself costs **28 MB**, measured on the check branch: 483 MB to 511 MB,
almost all of it the restored `statute_chunk_embedding_idx` at 21 MB. That
leaves **513 MB**, which still holds phases 1 to 3 with room to spare.

The headroom is not only for data. `docs/database.md` section 2 says to branch
the database rather than share one, and a `migrate-check` branch inherits its
parent's logical size and then diverges as the run rewrites rows. A re-score
rewrites `hex_score` and `hex_indicator`, which is roughly 90 MB at Louisiana's
size. A parent sitting at 90% of the limit is a parent no migration can be
tested against, which is the real reason not to spend the last of it.

### What a state costs

Measured from the Louisiana load rather than estimated:

| Unit | Bytes | Driven by |
|---|---|---|
| One hex | 2,171 | land area: `hexes = land_km² / 0.737` |
| One census tract | 21,908 | tract count |
| One facility | 4,070 | regulated facilities in ECHO and TRI |
| One state's statutes | ~8 MB | state-specific material only; the federal core is shared |

Hexes are about 82% of the cost, and hex count follows land area, which is
known exactly. So these estimates are firm where it matters and loose only on
facility counts, where being wrong by a factor of two moves a state by tens of
megabytes rather than hundreds.

| State | Hexes | Estimate |
|---|---|---|
| District of Columbia | 214 | 14 MB |
| Rhode Island | 3,634 | 24 MB |
| Delaware | 6,848 | 32 MB |
| Connecticut | 17,018 | 71 MB |
| Maryland | 34,114 | 125 MB |
| New Jersey | 25,844 | 127 MB |
| West Virginia | 84,486 | 213 MB |
| Pennsylvania | 157,236 | 452 MB |

**A state is all or nothing.** Section 9 ranks an indicator against the rest of
the state, so half a state produces percentiles computed against half a
denominator. There is no partial load that is merely less complete; it is
wrong rather than small.

---

## 2. What must land before any second state

### 2.1 The silent failure this prevents

`indicator_distribution` was keyed `(run_id, indicator_id)` and
`hex_score.percentile` is one column. With one state, "the scored universe" and
"Louisiana" are the same set by accident. Load a second state without changing
that and **every stored Louisiana percentile shifts, and nothing errors.** The
pre-registered criterion in section 13.2 is about the *statewide* top decile;
it would still print a pass or a fail, computed against a denominator it was
never registered against.

This is the whole reason the schema work comes first and is not a follow-up.

### 2.2 The lost migrations

`schema_migration` on `dev-seed` records 0028 `tract_health` and 0029
`drop_low_value_indexes` as applied on 2026-10-01, with checksums. **Their
files exist in no commit on any ref in this repository, nor in any dangling
object.** They were applied through the runner from a working tree that was
never committed.

`make migrate-verify` against `dev-seed` fails today and says so exactly:

```
0028 is recorded as applied but its file is gone
0029 is recorded as applied but its file is gone
```

`production` is unaffected: it is at 0027 and matches this directory. So the two
long-lived branches have diverged by two migrations, and only one of them can
be rebuilt from the repository — against the claim in `docs/database.md`
section 3 that the output is reproducible from public inputs.

The checksum is `sha256(up file)`, so no reconstruction can be proved identical
unless it is byte-exact. **Migration 0030 therefore does not pretend to be
those files.** It restates their effects from the live schema, guarded so it is
a no-op where already applied and effective where not.

### The loop, and `forget`

The repair cannot itself be a migration. `up()` raises on any `drift` before
applying anything, and "recorded as applied but its file is gone" is drift, so
the two orphan rows block *every* migration — including one written to clean up
after them. Confirmed on a check branch: `up` refused with both drift lines and
applied nothing.

So the ledger repair is an operation on the ledger, added to the runner as
`app.migrate forget`:

```bash
python -m app.migrate forget 0028 0029   # before 0030 can be applied
```

It is narrow on purpose. It refuses a version that still has a file, because
forgetting one of those would make the next `up` re-apply a migration already in
the database. It refuses a version that is not in the ledger, rather than
passing silently. So the only thing it can do is the thing it is for.

The two checksums, for the record, since nothing else holds them now:

| Version | Slug | sha256 of the lost up file |
|---|---|---|
| 0028 | `tract_health` | `ca9d19f0dbb5c5572e8aee5fb7d1357b36d8e55767f038ccc9d42efc35ac1051` |
| 0029 | `drop_low_value_indexes` | `adc21f318083ee34e1cc199e6704db768ab173c5f27a5efea376979efeb9bcad` |

0028 and 0029 are left as spent numbers, and the gap in `api/migrations` is the
record. `tests/test_migrations.py` names both so a third gap still fails.

### Reverting 0030 refuses rather than destroying data

0030 re-declares `tract_health`; it did not create the 1,367 rows already in it,
and the pull that produced them is the lost migration's. A `DROP TABLE` on the
way down would delete data the migration never put there and cannot restore. The
first round-trip test on the check branch did exactly that and emptied the
table, which is how this was found. The down migration now refuses while the
table has rows, the same way 0031's refuses while more than one state is scored.

What 0030 restates:

- **`tract_health`**, reconstructed column for column: three CDC PLACES measures
  with confidence intervals, keyed by tract and release year. See section 6.
- **`hex_pilot_idx` stays dropped.** It was a partial index on the single-state
  flag that 0031 renames, so restoring it would restore an index on a column
  that is about to change.
- **`statute_chunk_embedding_idx` is restored.** 0010 chose it deliberately —
  *"HNSW rather than IVFFlat because the corpus is small and static, so build
  time is irrelevant and recall is not"* — and without it every retrieval is a
  sequential scan over 2,841 chunks of 1536-dimensional vectors. A documented
  decision is not reversed by an undocumented migration.

### 2.3 Per-state percentiles

Migration 0031:

| Change | Why |
|---|---|
| `scored_state` table, seeded with Louisiana | A single-valued `PILOT_STATE` cannot express two states, and coverage is a property of the data, not of the process reading it |
| `indicator_distribution` gains `state_fips`; PK → `(run_id, state_fips, indicator_id)` | The distribution a percentile was ranked against belongs to one state |
| `hex.in_pilot_state` → `hex.centroid_in_state` | Not a duplicate of `state_fips`: one is which ranking the cell joins, the other is whether its centroid is inside that state's line (section 6). "Pilot" is the wrong word for either once there are two |
| `hex.state_fips` FK → `scored_state` | A grid may not exist for a state nobody has declared scored |
| `hex_scored_by_state_idx` | The multi-state successor to `hex_pilot_idx`; the run walks one state at a time, so the state leads |
| `no_score_reason`: `outside_pilot_state` → `outside_scored_states` | The old wording stops being true the moment a second state is scored |

`scoring/burden/percentile.py` needs no new concept. It already says *"`rank`
takes the scored universe as a required argument rather than trusting its
callers to have filtered already"*. The caller passes one state at a time.

### 2.4 The regression test that matters

Per-state percentiles over exactly one state must reproduce today's numbers to
the last digit. Louisiana is the fixture: run 0031, re-score, and every
`hex_score.percentile` must be unchanged. If any moves, the partition is wrong,
and it is far better to learn that while there is one state than after a second
has been published.

---

## 3. The order states arrive, and why it is not by size

| Phase | States | Adds | Running | When |
|---|---|---|---|---|
| 0 | — (schema only) | 0 | 483 MB | before anything |
| 1 | District of Columbia | 14 MB | 497 MB | now |
| 2 | Rhode Island | 24 MB | 521 MB | now |
| 3 | Delaware | 32 MB | 553 MB | now |
| 4 | West Virginia | 213 MB | 766 MB | after 2026-10-15 |
| 5 | Connecticut, Maryland, New Jersey | 323 MB | — | after 2026-10-15 |

**Phases 1 to 3 buy no validation evidence, and that is the point.** None of
DC, Rhode Island or Delaware carries a pre-registered site, so they prove the
multi-state machinery without spending anything that Appendix A is keeping
score of. They are cheap enough to load, inspect, drop and reload.

**West Virginia is the first state that tests the score**, because it activates
`N-INSTITUTE` through `activate_when: "scoring coverage includes WV"`. Section
17.5 is explicit that flipping `active` is not a change to the set: the target
was fixed before a national score existed, precisely so it could not be chosen
afterwards. That is a commitment, not a feature flag. Spend it on a settled
pipeline, which means after the machinery has survived three states and after
the plan upgrade has removed the pressure to get it right first time.

**District of Columbia first is deliberate beyond being smallest.** Its 206
tracts over 158 km² invert Louisiana's geometry. Section 6 chose hexagons
because Louisiana tracts vary in area by three orders of magnitude, and the
case it worried about was the rural tract larger than any sensible cell. DC is
the opposite: most of its tracts are smaller than one resolution-8 cell, so
`tract_hex_weight` has many tracts per hex rather than many hexes per tract.
That path has never been exercised, and at 214 hexes a run takes minutes.

---

## 4. What a within-state percentile means in a state with no heavy industry

The smaller and less industrial the state, the more a within-state percentile
map misleads. DC's top decile is about 21 cells, and they will be painted at the
dark end of the ramp whatever their absolute burden, because the ramp colours
rank and the rank is computed over DC. A reader who has seen Cancer Alley in the
same colour has been told something false.

Section 15 already carries this caveat and `docs/frontend.md` section 1 already
repeats it. Neither is enough once there are five states on one map, because the
caveat is currently a sentence about Louisiana rather than a per-state statement
the interface makes unavoidable.

Two consequences, and they are decisions rather than tasks:

1. **Per-state percentiles stay**, over a national ranking. They preserve every
   published Louisiana score and the pre-registered criteria. The cost is that
   one map cannot be coloured on one scale, and that cost is accepted.
2. **The interface must name whose percentile it is showing**, everywhere it
   shows one. That is not a caption; it is the difference between a map that is
   honest and one that is not.

---

## 5. Naming whose percentile it is

**Done.** `/health` reports `scored_states` read from the `scored_state` table
rather than from configuration, `pilot_state` is gone from `Settings` and from
the `Health` schema, and `/hex` returns `state_name` beside the FIPS code.

The copy splits along what each surface actually knows:

| Surface | Says | Because |
|---|---|---|
| Masthead (`App.tsx`) | "…in Louisiana", "…in Louisiana and West Virginia", "…across 3 states", or no state at all when `/health` has not answered | It is the one line on every page, so a stale state here is the most-read wrong sentence on the site |
| Legend | "Percentile within its own state" | It sits over the whole map and does not know which hexagon is being read. With two states drawn there is no single state whose percentile it shows |
| Detail panel | "Percentiles are *Louisiana* percentiles." | It has a hexagon, so it can name the state. Where the API did not say, it narrows the claim instead of guessing |
| Map's `h1` | "Map of cumulative environmental burden" | Coverage is the masthead's job; a heading naming one state would go stale where nothing checks it |

`place.ts` now prefers the API's `state_name` over its own FIPS table, which
existed because `state` is a code and a reader was once shown **"22"** as the
name of where they live. The table stays as a fallback.

**Deliberately not changed.** `AboutPage` and `MethodologyPage` describe the
scope as Louisiana only, air and industrial burden only. That is *true today*,
and rewriting it to be state-agnostic before a second state exists would make
it vaguer without making it more accurate. It changes when DC loads, in the
same commit.

Still outstanding: the initial viewport is Louisiana (`MapView.tsx` carries the
bounds as a constant). With several states it needs either a state selector or
a bounding box computed over the scored extent.

---

## 6. The `tract_health` decision

0030 recovers the table because the rows are real and the work was done. It is
read by nothing: no module under `api/`, `etl/`, `scoring/`, `assistant/` or
`web/` mentions it.

Using it is a methodology revision, not a code change. Section 3 names
CalEnviroScreen's health-outcome indicators as what ClearSkies lacks, and
section 16 records their absence as *"the single largest gap in the
specification"* on the grounds that no free national tract-level source exists.
CDC PLACES is one, for asthma, COPD and coronary heart disease. If that
assessment has changed, it changes in `docs/methodology.md` with its reasoning,
a weight, and a place in the Sensitive Populations subgroup — not by a scoring
module quietly reading a table.

Until that decision is made the table stays recovered, unused and commented as
such. The alternative, dropping it, is defensible and loses 1,367 rows of a
pull nobody has the script for.

---

## 7. Revision history

- **2026-10-11.** First version. Section 2.3's schema work applied to
  `dev-seed`; the per-state loop in `burden/states.py` and the coverage
  reporting in section 5 both landed. No second state loaded, and no scoring
  run executed against the new path. Sizing model measured from the Louisiana load.
  Migrations 0030 and 0031 written and applied on branch
  `migrate-check-0030-0031` off `dev-seed`, forward and back and forward again,
  then applied to `dev-seed`; `verify` reports 29 applied and every checksum
  matching. `production` is still at 0027. `app.migrate forget` added, with
  tests.
