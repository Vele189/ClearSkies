# Data quality and the pipeline gate

A bad load should fail loudly, not quietly poison the score.

That is harder than it sounds, because the dangerous failures in this pipeline
do not raise. A source returns every row it was asked for and covers a third of
the state. A join key changes shape and two thirds of an indicator's signal
disappears into unmatched rows. A unit changes upstream and a modeled risk
arrives three orders of magnitude too large, still inside every type. In each
case the adapter is fine, the manifest is green, and the map is wrong.

## What was already covered

The adapter interface carries the generic half, and CS-108 does not rebuild it:

- every rejected record is counted, sampled into the manifest, and keyed by a
  reason short enough to be a histogram,
- one tolerance rule (`PartialFailurePolicy`) refuses to load a pull that lost
  too much, leaving last night's data in place,
- a repeated natural key inside one pull fails the run, because which row
  survived would otherwise depend on iteration order,
- every run produces a `PullMetadata`, including the runs that failed.

All of that judges a source against itself, one source at a time. Two things it
structurally cannot do are what this ticket adds.

## Per-source thresholds

`etl/pipeline/quality/expectations.py` declares, for each of the five Phase 1
sources: the row count range each table should land in, how often a field may be
null, which coded values are known, what numbers are physically plausible, and
which fields have to be well-formed geography.

Declared as data rather than written as code, for the same reason `SourcePolicy`
is. Five hand-rolled check suites drift within a month: one adapter validates its
coordinates and another forgets, one treats a null as fatal and another shrugs.

**Every threshold carries the reason it holds that value**, and they come in two
kinds, labelled in the file:

*Grounded* numbers come from something checkable. Louisiana had 1,388 census
tracts in the 2020 TIGER release, so the tract tables expect between 1,200 and
1,600 rows. The ECHO adapter recorded 13,842 Louisiana air facilities against the
live service, of which roughly one row in twenty-three repeats a registry id.

*Envelope* numbers are deliberately loose. Four of the five adapters have never
run against live upstream, so a tight range would be a guess that fails on the
first honest night. They catch catastrophe — a source returning nothing, a join
fanning out, a unit changing — and not drift.

The envelopes are not meant to stay loose. Every run records the value each check
measured, so after a fortnight of nightly runs a range can be taken from history
instead of from judgement:

```bash
python -m pipeline history --store quality-runs
```

That is why "check results persisted per run" is an acceptance criterion and not
a nicety.

### Where a declaration lives

An adapter owns its own domain knowledge, so the intended home is an
`expectations` class variable on the adapter, exactly as `policy` already works.
CS-102 through CS-105 are on unmerged branches, so their five declarations
currently sit in `expectations.py` keyed by registry name, and `for_source`
prefers whatever the adapter class declares. As each adapter merges, its entry
moves onto its class.

A source that declares nothing is reported as a gap, not passed over.

## Cross-source checks

`etl/pipeline/quality/cross.py` holds the checks no adapter can make, because no
adapter sees more than itself:

| Check | The failure it catches |
|---|---|
| `tri_matches_echo` | TRI loading cleanly against FRS ids ECHO no longer uses. Every unmatched facility silently leaves indicator E3. |
| `tract_coverage` | A tract in the list with no values, which becomes a hex with a missing indicator. Also the reverse: a value for a tract that does not exist, which is a join that will drop. |
| `hex_grid_agreement` | Two sources writing different hex grids, so the score is built from an inner join and the map loses cells without an error. |
| `group_minimum.<group>` | Section 11 rule 2 measured across the grid: the share of cells holding enough indicators for a group to be computable. |
| `scored_hex_minimums` | A hex carrying a score it was not entitled to, which looks exactly like a hex that earned one. |

## Four statuses, not two

`pass`, `warn`, `fail` and **`skip`**. The fourth is the one that earns its
place. A check that could not run is not a check that passed, and a gate
reporting all-green because half its checks found no data is precisely the silent
poisoning this ticket exists to prevent.

So a check whose inputs are absent returns `skip` naming exactly what it wanted,
and the run's verdict is `skip` rather than `pass`. The nightly job says which
sources it was supposed to produce:

```bash
python -m pipeline check --require epa_echo --require epa_tri
```

A skip on a required source becomes a failure, and a required source that
produced no manifest at all fails outright. That keeps two different answers
apart: "this has not been built yet" and "this was supposed to be here and is
not".

Several checks skip today by design. The hex-level tables for E3, F1 through F4
and S1 through P5 are built by CS-106, CS-107 and CS-202, and their group
minimums cannot be evaluated until they exist. Evaluating a group on the
indicators that happen to exist would invent failures: a cell holding E1 and E2
fails a minimum of 2 of 4 only because E3 and E4 could not be looked for. Adding
one line to `HEX_INDICATORS` as each lands is all that is needed.

## What a failure does

The gate does not roll anything back. Each adapter's transaction closed long
before it ran, and unwinding four committed sources to punish the fifth would be
worse than saying so.

A failure means the run does not become the current one. The job exits non-zero,
`pipeline_run.is_current` stays where it was, and the map keeps serving last
night's data until somebody looks.

## Where a failure surfaces

Not only in a log:

- **The Actions run page.** The report renders to `$GITHUB_STEP_SUMMARY`, so the
  verdict, every failure and the full check table are on the run itself.
- **Annotations.** Each failure raises a `::error` and each warning a
  `::warning`, which attach to the run rather than sitting in scrollback.
- **The exit status.** Non-zero fails the job, which is what GitHub notifies on.
- **The database.** `quality_run` and `quality_check_result` (migration `0015`)
  hold every check of every run, so the history is queryable rather than
  scrolled.
- **The artifact.** The nightly job keeps `etl/quality-runs/` for thirty days.

## Running it

```bash
python -m pipeline check                       # every registered source, then the gate
python -m pipeline check fake --no-store       # one source, nothing persisted
python -m pipeline check --require epa_echo    # a skip on ECHO is a failure
python -m pipeline check --json                # the whole report
python -m pipeline history                     # what each check has measured
```

Exit status is 0 unless a check failed.

## Adding a check

1. **A threshold on one source.** Add a rule to that source's
   `SourceExpectations`, and say in the `note` why the number is what it is. A
   threshold without a reason gets tightened at 2am and stops meaning anything.
2. **A check spanning sources.** Add a function to `cross.py` returning a
   `CheckResult`, and register it in `run_cross_checks`. Return `skip` naming
   what was missing rather than passing when its inputs are absent.
3. **Test both directions.** A check only tested on bad data can be one that
   fires on everything; a check only tested on good data can be one that never
   fires at all.

`tests/test_quality_checks.py` also holds a drift guard: every rule is checked
against the record class that writes its table, for every adapter importable in
the tree. It covers ECHO today and covers each of the others on the day its
branch lands, with no edit needed.
