"""What the nightly job runs tonight, in what order, and what it leaves alone.

`run_adapter` knows how to run one source. `run_gate` knows how to judge a
night's load. Neither knows what a night should consist of, and left to itself
the job would do the crudest possible thing: pull all six sources in whatever
order the registry happens to iterate, every night, forever.

That is wrong in three separate ways, and this module is the three answers.

**Most of these sources do not change nightly.** ECHO refreshes weekly upstream.
TRI, AirToxScreen and ACS publish once a year or less, with lags measured in
years. Re-downloading a 2019 AirToxScreen release every night for a year costs
the Actions budget, costs EPA the bandwidth, and cannot produce a different
number. Only OpenAQ genuinely moves every day. So each source declares how often
it is worth pulling, and a source that is not due is *carried*, not skipped: last
night's rows stand, and the plan says so in as many words. A carried source and a
source that failed to load are different states and must never render the same.

**Order has to be declared rather than inherited.** The five Phase 1 adapters
have no data dependencies on each other, and that is a designed property rather
than an accident: `pipeline.adapters.base` gives a source no way to read another
source, which is what keeps adding a sixth a contained change. TRI joins ECHO's
registry ids by fetching them from ECHO's own endpoint, not by reading what the
ECHO adapter loaded. So the graph below is genuinely empty of edges today, and
`depends_on` exists anyway, because the stages that come after the adapters are
not so lucky: the dasymetric interpolation of CS-106, the facility assignment of
CS-107 and the scoring of CS-204 all consume what the adapters write. Declaring
the mechanism now, with the honest answer that today's edge set is empty, is what
lets each of those land as one entry rather than as a rewrite of the job.

**A finite job needs a declared order even without edges.** The workflow carries
a timeout, so when a night overruns, the order decides what got cut. Sources
within the same dependency level therefore run cheapest first: a night that dies
at the timeout has spent its minutes on the sources most likely to have finished
rather than on the one big annual download that was never going to.

Every number here carries the reason it holds that value, on the same terms as
`pipeline.quality.expectations`: a threshold whose reason is unwritten gets
changed at 2am by whoever is on call and stops meaning anything. The minute
budgets are envelopes, labelled as such, because four of these six adapters have
never run against live upstream from a GitHub runner.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

# What upstream does, which is the reason each interval below holds its value.
# This is documentation attached to the number rather than a switch: nothing
# branches on it, and `every_days` is what the planner reads.
Cadence = Literal["daily", "weekly", "annual", "fixture"]

# pull     run the adapter tonight
# carry    not due; the previous load stands and stays current
# blocked  a declared dependency did not succeed tonight, so running this now
#          would build on data that is missing or stale without saying so
Action = Literal["pull", "carry", "blocked"]

_ACTION_WORD: dict[Action, str] = {
    "pull": "pull",
    "carry": "carry",
    "blocked": "BLOCKED",
}


@dataclass(frozen=True, slots=True)
class Refresh:
    """How often a source is worth pulling, and why that interval.

    `every_days` is a floor on the gap between full pulls, not a promise about
    when a new release is noticed. An annual source on a 30-day interval picks up
    a republished vintage within a month of it appearing; the day a release is
    announced, `workflow_dispatch` closes that gap to minutes. That trade is
    deliberate: a release lands once a year and is announced, so paying for a
    nightly re-download to shorten a bounded, manually closable lag is the wrong
    way round.
    """

    cadence: Cadence
    every_days: int
    why: str

    def due(self, *, last_success: datetime | None, now: datetime) -> tuple[bool, str]:
        """Whether to pull tonight, and the sentence explaining the answer.

        A source that has never succeeded is always due. That is the case on the
        first night, and it is also the case after a run of failures, which is
        the behaviour wanted: an interval counts from the last *success*, so a
        source that has been failing for a week is retried every night rather
        than waiting out its cadence on the strength of a load that never landed.
        """
        if last_success is None:
            return True, "never pulled successfully, so it is due"

        age = now - last_success
        if age < timedelta(0):
            # A clock that went backwards, or a store carried between machines.
            # Pulling is the safe answer; refusing on a negative age would strand
            # the source until the clock caught up.
            return True, f"last success is dated {_stamp(last_success)}, in the future; pulling"

        interval = timedelta(days=self.every_days)
        days = age.total_seconds() / 86_400
        if age >= interval:
            return True, (
                f"last success {_stamp(last_success)}, {days:.1f} days ago, "
                f"at or past the {self.every_days}-day {self.cadence} interval"
            )
        remaining = (interval - age).total_seconds() / 86_400
        return False, (
            f"pulled {days:.1f} days ago and the {self.cadence} interval is "
            f"{self.every_days} days; due again in {remaining:.1f}. {self.why}"
        )


@dataclass(frozen=True, slots=True)
class SourceSchedule:
    """Everything the nightly job needs to decide about one source."""

    source: str
    refresh: Refresh
    # Sources that must have loaded successfully tonight before this one runs.
    # Empty for all five Phase 1 adapters, for the reason in the module
    # docstring. The derived stages that land later are what fills it.
    depends_on: tuple[str, ...] = ()
    # An envelope, not a measurement. Used only to order sources within a
    # dependency level and to add up the budget in docs, so being wrong costs
    # ordering rather than correctness.
    budget_minutes: float = 5.0
    note: str = ""


# ---- the declarations --------------------------------------------------
#
# Keyed by registry name, the same convention `pipeline.quality.expectations`
# uses and for the same reason: four of these adapters are on unmerged branches,
# so a declaration cannot live on a class this tree cannot import. Unlike the
# expectations, these do not move onto the adapter when it merges. How often to
# pull a source is a property of the nightly job's budget, not of the adapter,
# and keeping the six intervals on one page is what makes the budget reviewable.

DAILY = Refresh(
    cadence="daily",
    every_days=1,
    why="OpenAQ publishes measurements continuously and E4's trailing window moves every night.",
)

WEEKLY = Refresh(
    cadence="weekly",
    every_days=7,
    why=(
        "ECHO refreshes weekly upstream, so six nights in seven would re-download "
        "a file that cannot have changed."
    ),
)

# One pull a month against a source that republishes at most once a year. The
# interval is what the acceptance criterion asks for in as many words: an
# annually-published source is not re-pulled in full every night.
MONTHLY = Refresh(
    cadence="annual",
    every_days=30,
    why=(
        "Upstream republishes at most once a year, with a lag of years. A monthly "
        "pull bounds how long a new release can sit unnoticed; workflow_dispatch "
        "closes the gap the day one is announced."
    ),
)

FIXTURE = Refresh(
    cadence="fixture",
    every_days=1,
    why=(
        "The reference adapter reads a fixture, not a network. It runs every night "
        "because its job is to prove the four stages still fit together, and a "
        "contract test that runs monthly is a contract test that reports a break "
        "three weeks late."
    ),
)


SCHEDULES: dict[str, SourceSchedule] = {
    # Cheapest thing in the job and the one with no upstream, so it sorts first
    # within its level and a broken interface is the first thing the night says.
    "fake": SourceSchedule(
        source="fake",
        refresh=FIXTURE,
        budget_minutes=0.1,
        note="Reference adapter. Fixture-backed, so it costs a runner second and no bandwidth.",
    ),
    "epa_echo": SourceSchedule(
        source="epa_echo",
        refresh=WEEKLY,
        budget_minutes=3.0,
        note=(
            "Envelope. One bulk query for Louisiana air facilities plus a paged "
            "detail walk, at two requests a second."
        ),
    ),
    "epa_tri": SourceSchedule(
        source="epa_tri",
        refresh=MONTHLY,
        budget_minutes=4.0,
        note=(
            "Envelope. The Basic Data File for one reporting year, the TRI facility "
            "directory, the ECHO registry ids it joins against, and the ZIP gazetteer."
        ),
    ),
    "airtoxscreen": SourceSchedule(
        source="airtoxscreen",
        refresh=MONTHLY,
        budget_minutes=5.0,
        note=(
            "Envelope. Two requests, but one is a national workbook that is "
            "unzipped and parsed for every tract in the country."
        ),
    ),
    "openaq": SourceSchedule(
        source="openaq",
        refresh=DAILY,
        budget_minutes=6.0,
        note=(
            "Envelope, and the largest. Paged daily measurements for every "
            "Louisiana sensor across a trailing year, held to OpenAQ's published "
            "60 requests a minute."
        ),
    ),
    "census_acs": SourceSchedule(
        source="census_acs",
        refresh=MONTHLY,
        budget_minutes=8.0,
        note=(
            "Envelope, and the slowest single pull. TIGER tract geometry for the "
            "state is large and TIGERweb has already refused one query."
        ),
    ),
}


# The interval a source gets when nothing is declared for it. Daily, because a
# source nobody has thought about should cost attention rather than quietly
# pulling once a month; the plan names it so the omission is visible.
UNDECLARED = Refresh(
    cadence="daily",
    every_days=1,
    why="No schedule is declared for this source, so it is pulled nightly until one is.",
)


def schedule_for(source: str) -> SourceSchedule:
    """The declaration for one source, or a daily default that says it is missing."""
    declared = SCHEDULES.get(source)
    if declared is not None:
        return declared
    return SourceSchedule(
        source=source,
        refresh=UNDECLARED,
        note="Undeclared: add an entry to pipeline.schedule.SCHEDULES.",
    )


# ---- ordering ----------------------------------------------------------


class DependencyError(ValueError):
    """The declared graph cannot be run: a cycle, or an edge to nothing."""


def resolve_order(sources: Iterable[str]) -> tuple[str, ...]:
    """The sources, topologically sorted, cheapest first within a level.

    Kahn's algorithm with an explicit tie-break rather than a set, because an
    order that depends on hash iteration makes two nights incomparable and makes
    a flaky ordering bug unreproducible.

    An edge pointing at a source that is not in this run is an error rather than
    a silently dropped edge. Running a derived stage while quietly ignoring that
    its input was never scheduled is precisely the failure the graph exists to
    prevent.
    """
    wanted = list(dict.fromkeys(sources))
    known = set(wanted)

    remaining: dict[str, set[str]] = {}
    for name in wanted:
        edges = set(schedule_for(name).depends_on)
        missing = sorted(edges - known)
        if missing:
            raise DependencyError(
                f"{name} depends on {', '.join(missing)}, which this run does not include"
            )
        remaining[name] = edges

    ordered: list[str] = []
    while remaining:
        ready = [name for name, edges in remaining.items() if not edges]
        if not ready:
            stuck = ", ".join(sorted(remaining))
            raise DependencyError(f"dependency cycle among {stuck}")
        ready.sort(key=lambda name: (schedule_for(name).budget_minutes, name))
        for name in ready:
            ordered.append(name)
            del remaining[name]
        for edges in remaining.values():
            edges.difference_update(ready)
    return tuple(ordered)


# ---- the plan ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlannedSource:
    """One source's place in tonight's run, and the reason it is there."""

    source: str
    action: Action
    reason: str
    schedule: SourceSchedule

    @property
    def pulling(self) -> bool:
        return self.action == "pull"

    def line(self) -> str:
        return f"[{_ACTION_WORD[self.action]}] {self.source}: {self.reason}"


@dataclass(frozen=True, slots=True)
class RunPlan:
    """What tonight does, decided before anything is pulled.

    Deciding first and running second is what makes the plan printable. A night
    that is about to skip four of six sources should be able to say so before it
    spends twenty minutes proving it, and `python -m pipeline plan` is that.
    """

    planned: tuple[PlannedSource, ...] = ()
    now: datetime | None = None
    notes: tuple[str, ...] = field(default=())

    @property
    def to_pull(self) -> tuple[str, ...]:
        return tuple(p.source for p in self.planned if p.action == "pull")

    @property
    def carried(self) -> tuple[str, ...]:
        return tuple(p.source for p in self.planned if p.action == "carry")

    @property
    def blocked(self) -> tuple[str, ...]:
        return tuple(p.source for p in self.planned if p.action == "blocked")

    @property
    def budget_minutes(self) -> float:
        """Minutes tonight's pulls are expected to cost, by the declared envelopes."""
        return sum(p.schedule.budget_minutes for p in self.planned if p.action == "pull")

    def for_source(self, source: str) -> PlannedSource | None:
        return next((p for p in self.planned if p.source == source), None)

    def summary(self) -> str:
        return (
            f"{len(self.to_pull)} to pull, {len(self.carried)} carried, "
            f"{len(self.blocked)} blocked; "
            f"about {self.budget_minutes:.1f} runner minutes"
        )

    def markdown(self) -> str:
        """The plan as a page, for the Actions run summary."""
        lines = [
            "# Nightly ETL plan",
            "",
            f"{self.summary()}.",
            "",
            "| | Source | Cadence | Budget | Reason |",
            "|---|---|---|---|---|",
        ]
        for p in self.planned:
            lines.append(
                f"| {_ACTION_WORD[p.action]} | {p.source} | "
                f"{p.schedule.refresh.cadence} every {p.schedule.refresh.every_days}d | "
                f"{p.schedule.budget_minutes:g}m | {p.reason} |"
            )
        for note in self.notes:
            lines += ["", f"> {note}"]
        return "\n".join(lines) + "\n"


def plan_run(
    sources: Iterable[str],
    *,
    now: datetime,
    last_success: Mapping[str, datetime] | None = None,
    force: Iterable[str] = (),
    force_all: bool = False,
) -> RunPlan:
    """Decide what tonight runs, before it runs.

    `last_success` is when each source last loaded cleanly, which is what the
    cadence counts from. An empty mapping means a first night, or a job that lost
    its state, and every source comes out due. That is the right failure
    direction: forgetting when a source was last pulled costs a redundant pull,
    where assuming it was recent costs a month of stale data.

    `force` names sources to pull regardless of cadence, which is what a
    `workflow_dispatch` the morning a new release lands is for.
    """
    history = dict(last_success or {})
    forced = set(force)
    ordered = resolve_order(sources)

    planned: list[PlannedSource] = []
    for name in ordered:
        schedule = schedule_for(name)
        if force_all or name in forced:
            planned.append(PlannedSource(name, "pull", "pull was forced for this run", schedule))
            continue
        due, why = schedule.refresh.due(last_success=history.get(name), now=now)
        planned.append(PlannedSource(name, "pull" if due else "carry", why, schedule))

    notes: list[str] = []
    undeclared = sorted(p.source for p in planned if p.source not in SCHEDULES)
    if undeclared:
        notes.append(
            f"No schedule is declared for {', '.join(undeclared)}; they are being pulled "
            "nightly by default. Add them to pipeline.schedule.SCHEDULES."
        )
    if not history:
        notes.append(
            "No previous successful run was found, so every source is due. On a run "
            "that expected carried state, this means the state was lost rather than "
            "that everything genuinely needs pulling."
        )
    return RunPlan(planned=tuple(planned), now=now, notes=tuple(notes))


def apply_outcomes(plan: RunPlan, *, succeeded: Iterable[str]) -> RunPlan:
    """Re-mark sources whose dependencies failed tonight.

    Called after the pulls, because whether a dependency succeeded is not knowable
    until it has run. With today's empty edge set this changes nothing and returns
    the plan it was given; it is here so that the first derived stage to declare
    an input gets the behaviour rather than having to add it.
    """
    ok = set(succeeded)
    updated: list[PlannedSource] = []
    changed = False
    for p in plan.planned:
        failed = sorted(d for d in p.schedule.depends_on if d not in ok)
        if p.action == "pull" and failed:
            changed = True
            updated.append(
                PlannedSource(
                    p.source,
                    "blocked",
                    f"depends on {', '.join(failed)}, which did not succeed tonight",
                    p.schedule,
                )
            )
        else:
            updated.append(p)
    if not changed:
        return plan
    return RunPlan(planned=tuple(updated), now=plan.now, notes=plan.notes)


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M UTC")


__all__ = [
    "DAILY",
    "FIXTURE",
    "MONTHLY",
    "SCHEDULES",
    "UNDECLARED",
    "WEEKLY",
    "Action",
    "Cadence",
    "DependencyError",
    "PlannedSource",
    "Refresh",
    "RunPlan",
    "SourceSchedule",
    "apply_outcomes",
    "plan_run",
    "resolve_order",
    "schedule_for",
]
