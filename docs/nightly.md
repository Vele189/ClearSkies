# The nightly run

Scheduled orchestration of every adapter, with no server to manage.

`.github/workflows/etl.yml` runs at 07:00 UTC, roughly 01:00 in the pilot state,
and can be triggered by hand. It installs the ingestion package and calls
`python -m pipeline nightly`. Everything interesting happens in Python rather
than in YAML, for one reason: the orchestration has rules worth testing, and a
rule expressed in workflow steps is a rule no test can reach.

## What one night does

1. **Plan.** Read the ledger for when each source last loaded cleanly, and decide
   which sources are due. Print the plan before pulling anything.
2. **Pull** the sources that are due, in dependency order, into one shared sink.
   In the workflow that sink is in memory, not Postgres. See *What the night does
   not do* below.
3. **Gate.** Apply CS-108's per-source thresholds and cross-source checks.
4. **Record** the night in the ledger and every pull in the provenance history,
   whatever happened to them.
5. **Promote** the run, but only if the gate passed.
6. **Regenerate** `docs/provenance.md` from the manifests and commit it, if it
   changed.

Steps 1 and 5 are what this ticket adds to what CS-108 already did.

## What the night does not do

It does not write to the database. `python -m pipeline nightly` runs every due
adapter into the in-memory sink and applies the gate to the result, so a green
night means the sources are still reachable, still shaped the way the adapters
believe, and still inside the CS-108 thresholds. It does not mean the map has
tonight's numbers in it.

Loading is `python -m pipeline run <source> --load`, against `DATABASE_URL`, run
by hand. The workflow is given no such secret, deliberately: the ledger that
decides what is due is a file in an Actions cache, so a night that loaded would
write to the database on the strength of state GitHub is free to evict. The two
move together, into `pipeline_run` and the Postgres sink, and until then this
page says which of the two a night actually did.

What the night *does* keep is the snapshots: every download is written to
`etl/pipeline-snapshots`, which has its own Actions cache, because a source that
has gone away is served from its last good copy and a copy held in memory does
not outlive the process that fetched it.

## Refresh cadence

Only one of these sources changes every day. Pulling all eight nightly would
spend six times the Actions budget and six times EPA's bandwidth to arrive at the
same numbers, so each source declares how often it is worth pulling, in
`etl/pipeline/schedule.py`, with the reason attached to the interval.

| Source | Upstream | Pulled | Why |
|---|---|---|---|
| `openaq` | daily | every night | Measurements arrive continuously and E4's trailing window moves every night. |
| `fake` | fixture | every night | The reference adapter proves the four stages still fit together. A contract test that runs monthly reports a break three weeks late. |
| `epa_echo` | weekly | every 7 days | ECHO refreshes weekly, so six nights in seven would re-download an unchanged file. |
| `epa_tri` | annual, ~18-month lag | every 30 days | Republished at most once a year. |
| `airtoxscreen` | every 1-2 years, ~3-year lag | every 30 days | Republished at most once a year. |
| `epa_rsei` | annual, by model version | every 30 days | Republished on its own model-version schedule, at most once a year. |
| `census_acs` | annual release | every 30 days | Republished at most once a year. |
| `census_block` | decennial | every 365 days | The 2020 blocks and their PL 94-171 counts are fixed until the 2030 census. It is also the longest pull in the job, about 30 minutes, so a monthly pull would buy nothing with the largest bill in the schedule. |

A monthly interval on an annual source bounds how long a new release can sit
unnoticed. The day one is announced, a `workflow_dispatch` with `force` closes
that gap to minutes. That is the right way round: paying for a nightly download
to shorten a bounded, manually closable lag buys nothing.

The interval counts from the last **success**, not the last attempt. A source
that has been failing for a week stays due every night rather than resting out
its cadence on the strength of a load that never landed.

### Carried is not skipped, and not failed

A source that is not due is *carried*: it did not run, and last night's rows are
still the right rows. The ledger records that as a distinct outcome from a pull
that failed, because they cost the same number of manifests and mean opposite
things. A job that renders them the same way either panics every night or stops
reporting on the night it should.

`--require` follows the same rule. It means "this source produced what it was
asked for", so a carried source is not required of that run. A source that is
required and is not in the plan at all is a different matter and does fail the
run: it was never considered, rather than deliberately left alone.

## Dependency order

Sources run in topological order over their declared dependencies, and cheapest
first within a level.

Today no adapter depends on another, and that is designed rather than accidental:
`pipeline.adapters.base` gives a source no way to read what another source
loaded, which is what keeps adding a sixth a contained change. TRI joins ECHO's
registry ids by fetching them from ECHO's own endpoint, not by reading the ECHO
adapter's output. `test_schedule.py` asserts the edge set is empty, so a future
change that introduces a real dependency has to be argued with rather than
quietly slipped in.

The mechanism exists anyway, because the stages after the adapters are not so
lucky. The dasymetric interpolation of CS-106, the facility assignment of CS-107
and the scoring of CS-204 all consume what the adapters write, and each should
land as one `depends_on` entry rather than as a rewrite of the job.

Cheapest-first ordering within a level is not cosmetic. The job carries a
timeout, so when a night overruns, the order decides what got cut.

## What a failed night does

Nothing. That is the point.

Nothing was written to the database in the first place, and even once the night
loads, each source's transaction will have committed hours before the gate ran,
so a failure cannot mean a rollback: unwinding four good sources to punish a
fifth would be worse than saying so. Instead the run is **not promoted**: it is
recorded in the ledger, marked failed, and the map keeps serving the run that
last passed its gate.

The schema already models this. `pipeline_run` in migration 0002 carries a
status and an `is_current` flag, with a constraint that only a succeeded run may
hold it and a partial unique index permitting exactly one holder.
`etl/pipeline/ledger.py` is that model, file-backed, and `row_for_sql` emits the
shape the table takes so the two cannot drift. The ledger moves into Postgres
with the sink.

A night on which every source was carried is also not promoted. It loaded
nothing, so its gate had nothing to check and passed by having no opinion.
Promoting on the strength of a report made entirely of skips is the exact shape
CS-108 exists to refuse.

## How a failure reaches a person

- The **exit status** is 1, so the workflow run is red.
- The **step summary** on the run page carries the plan and every check, so the
  reason is visible without opening a log.
- **Annotations** attach the failures to the run itself.
- An **issue** is opened, labelled `nightly-etl`, which notifies whoever watches
  the repository. One issue, commented on, rather than one a night: a source
  down for a week is one problem lasting a week, not seven. It is closed by hand
  once the night is green, because an auto-closing notice is one nobody reads.
- The **quality report and ledger** are uploaded as an artifact for 30 days.

## Actions budget

Unmetered for public repositories, 2,000 minutes a month on the free tier for
private ones. The budget is written against the tighter of the two.

| | Minutes |
|---|---|
| 30 nights of a typical pull (OpenAQ plus the reference adapter) | ~183 |
| 4 nights of ECHO's weekly refresh | ~12 |
| 1 night when the four monthly sources come due together | ~18 |
| A twelfth of a night for the decennial block layer | ~3 |
| 30 nights of checkout, install and gate | ~60 |
| **Total** | **~276** |

Under 300 against a 2,000 floor, and the cadence policy is why. Pulling all
eight every night would be roughly 1,760 minutes for the same numbers.

`timeout-minutes` is 75, above the ~57 minutes an all-eight night is expected to
cost, so a genuinely slow night finishes rather than being cut in half. An
all-eight night happens twice: on the first one, and after the cache is lost.
The per-source budgets are envelopes rather than measurements, except the block
layer's, which was measured. Being wrong about one costs ordering, not
correctness: cheapest-first means a night that does hit the timeout loses the
census blocks, the one source that cannot have changed.

A `concurrency` group stops a scheduled run and a hand-triggered one loading at
the same time. They share a ledger, and two nights promoting themselves in
parallel is how a run that failed its gate ends up current.

## The ledger between runs

A cadence counts from a date, and a GitHub runner keeps nothing by default, so
the workflow caches `etl/pipeline-state`, and `etl/pipeline-snapshots` beside it.
Each cache key is unique per run and each restore key is a prefix, so every night
writes a fresh entry and picks up the most recent one.

This is interim, and safe to rely on because losing it is harmless: a cache miss
means every source comes out due and the night does one redundant full pull.
That is the right failure direction. Assuming a pull was recent when it was not
would cost a month of stale data instead.

## Running it

```
python -m pipeline plan                 # what tonight would pull, and why
python -m pipeline nightly              # the scheduled run
python -m pipeline nightly --force epa_tri   # ignore one source's cadence
python -m pipeline nightly --all        # ignore every cadence
python -m pipeline nightly --snapshots DIR   # where last-good downloads are kept
python -m pipeline runs                 # past nights, and the one being served
```

`plan` pulls nothing and writes nothing, so it is safe to run against a real
state directory to see what the next scheduled run intends to do.
