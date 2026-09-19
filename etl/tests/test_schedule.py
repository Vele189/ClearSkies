"""What tonight runs, and what it deliberately leaves alone.

Most of what is asserted here is about the difference between a source that was
not pulled and a source that failed. They cost the same number of manifests and
mean opposite things, and a nightly job that renders them the same way is one
that either panics every night or stops reporting the night it should.
"""

from datetime import UTC, datetime, timedelta

import pytest

from pipeline.schedule import (
    DAILY,
    MONTHLY,
    SCHEDULES,
    WEEKLY,
    DependencyError,
    Refresh,
    SourceSchedule,
    apply_outcomes,
    plan_run,
    resolve_order,
    schedule_for,
)

NOW = datetime(2026, 9, 11, 7, 0, tzinfo=UTC)


def ago(days: float) -> datetime:
    return NOW - timedelta(days=days)


# ---- the intervals themselves ------------------------------------------


def test_a_source_that_never_succeeded_is_due() -> None:
    due, why = DAILY.due(last_success=None, now=NOW)
    assert due
    assert "never pulled" in why


def test_a_daily_source_is_due_the_next_night() -> None:
    assert DAILY.due(last_success=ago(1.0), now=NOW)[0]


def test_a_daily_source_is_not_due_hours_later() -> None:
    due, why = DAILY.due(last_success=ago(0.25), now=NOW)
    assert not due
    assert "due again in" in why


def test_an_annual_source_is_not_re_pulled_every_night() -> None:
    """The acceptance criterion, stated as the test that would catch its loss."""
    for days in (1, 7, 14, 29):
        due, _ = MONTHLY.due(last_success=ago(days), now=NOW)
        assert not due, f"an annual source came due after {days} days"
    assert MONTHLY.due(last_success=ago(30), now=NOW)[0]


def test_a_weekly_source_tracks_its_upstream_refresh() -> None:
    assert not WEEKLY.due(last_success=ago(6), now=NOW)[0]
    assert WEEKLY.due(last_success=ago(7), now=NOW)[0]


def test_the_interval_counts_from_the_last_success_not_the_last_attempt() -> None:
    """A source failing for a week is retried nightly, not rested for a month.

    `last_success` is the only date the planner is given, so a run of failures
    leaves it where it was and the source stays due. This asserts the property
    that makes that safe rather than the mechanism.
    """
    assert MONTHLY.due(last_success=ago(40), now=NOW)[0]


def test_a_clock_that_went_backwards_pulls_rather_than_stranding_the_source() -> None:
    due, why = DAILY.due(last_success=NOW + timedelta(days=2), now=NOW)
    assert due
    assert "in the future" in why


def test_every_reason_is_written_down() -> None:
    """A threshold without a reason gets changed at 2am and stops meaning anything."""
    for schedule in SCHEDULES.values():
        assert schedule.refresh.why.strip(), f"{schedule.source} has no reason for its interval"
        assert schedule.note.strip(), f"{schedule.source} has no note"


def test_only_the_daily_source_is_pulled_every_night() -> None:
    """The budget rests on this: one source moves daily and the rest do not."""
    nightly = [s.source for s in SCHEDULES.values() if s.refresh.every_days == 1]
    assert set(nightly) == {"openaq", "fake"}


# ---- ordering -----------------------------------------------------------


def test_order_is_cheapest_first_within_a_level() -> None:
    """A night cut short by the timeout should have spent its minutes well."""
    order = resolve_order(["census_acs", "fake", "epa_echo"])
    assert order == ("fake", "epa_echo", "census_acs")


def test_order_is_stable_across_calls() -> None:
    """Two nights that ran the same sources must be comparable."""
    sources = ["openaq", "census_acs", "fake", "epa_tri", "airtoxscreen", "epa_echo"]
    assert resolve_order(sources) == resolve_order(list(reversed(sources)))


def test_the_five_phase_one_adapters_declare_no_edges_between_themselves() -> None:
    """Not an oversight. The interface gives a source no way to read another.

    TRI joins ECHO's registry ids by fetching them from ECHO's endpoint, not by
    reading what the ECHO adapter loaded. If a future change makes one adapter
    depend on another having run, this test is the one that should be argued
    with rather than quietly updated.
    """
    for schedule in SCHEDULES.values():
        assert schedule.depends_on == (), f"{schedule.source} declares a dependency"


def test_a_declared_dependency_is_ordered_before_its_dependent(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setitem(
        SCHEDULES,
        "derived",
        SourceSchedule(
            source="derived", refresh=DAILY, depends_on=("epa_echo",), budget_minutes=0.0
        ),
    )
    order = resolve_order(["derived", "epa_echo"])
    assert order.index("epa_echo") < order.index("derived")


def test_an_edge_to_a_source_this_run_excludes_is_an_error(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Running a derived stage while ignoring its missing input is the failure."""
    monkeypatch.setitem(
        SCHEDULES,
        "derived",
        SourceSchedule(source="derived", refresh=DAILY, depends_on=("epa_echo",)),
    )
    with pytest.raises(DependencyError, match="epa_echo"):
        resolve_order(["derived"])


def test_a_cycle_is_reported_rather_than_looped_on(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setitem(
        SCHEDULES, "a", SourceSchedule(source="a", refresh=DAILY, depends_on=("b",))
    )
    monkeypatch.setitem(
        SCHEDULES, "b", SourceSchedule(source="b", refresh=DAILY, depends_on=("a",))
    )
    with pytest.raises(DependencyError, match="cycle"):
        resolve_order(["a", "b"])


# ---- the plan -----------------------------------------------------------


def test_a_first_night_pulls_everything_and_says_why() -> None:
    plan = plan_run(["fake", "epa_echo"], now=NOW, last_success={})
    assert set(plan.to_pull) == {"fake", "epa_echo"}
    assert any("no previous successful run" in note.lower() for note in plan.notes)


def test_a_source_inside_its_interval_is_carried_not_skipped() -> None:
    plan = plan_run(["epa_tri"], now=NOW, last_success={"epa_tri": ago(3)})
    assert plan.carried == ("epa_tri",)
    assert plan.to_pull == ()
    planned = plan.for_source("epa_tri")
    assert planned is not None
    assert planned.action == "carry"


def test_force_overrides_the_cadence() -> None:
    """What a workflow_dispatch is for the morning a new release lands."""
    plan = plan_run(["epa_tri"], now=NOW, last_success={"epa_tri": ago(1)}, force=["epa_tri"])
    assert plan.to_pull == ("epa_tri",)
    assert "forced" in plan.for_source("epa_tri").reason  # type: ignore[union-attr]


def test_force_all_pulls_everything() -> None:
    plan = plan_run(
        ["fake", "epa_tri"],
        now=NOW,
        last_success={"fake": ago(0), "epa_tri": ago(0)},
        force_all=True,
    )
    assert set(plan.to_pull) == {"fake", "epa_tri"}


def test_the_budget_counts_only_what_is_being_pulled() -> None:
    plan = plan_run(["fake", "census_acs"], now=NOW, last_success={"census_acs": ago(1)})
    assert plan.to_pull == ("fake",)
    assert plan.budget_minutes == pytest.approx(SCHEDULES["fake"].budget_minutes)


def test_an_undeclared_source_is_pulled_nightly_and_named() -> None:
    """An omission should cost attention, not quietly settle into a monthly pull."""
    plan = plan_run(["brand_new"], now=NOW, last_success={"brand_new": ago(0.1)})
    assert plan.to_pull == ()  # daily interval, pulled 2.4 hours ago
    assert any("brand_new" in note for note in plan.notes)
    assert schedule_for("brand_new").refresh.every_days == 1


def test_a_dependent_is_blocked_when_its_input_failed(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setitem(
        SCHEDULES,
        "derived",
        SourceSchedule(source="derived", refresh=DAILY, depends_on=("epa_echo",)),
    )
    plan = plan_run(["epa_echo", "derived"], now=NOW, last_success={})
    assert set(plan.to_pull) == {"epa_echo", "derived"}

    after = apply_outcomes(plan, succeeded={"epa_echo"})
    assert after.blocked == ()

    after = apply_outcomes(plan, succeeded=set())
    assert after.blocked == ("derived",)
    assert "did not succeed" in after.for_source("derived").reason  # type: ignore[union-attr]


def test_applying_outcomes_with_no_edges_changes_nothing() -> None:
    plan = plan_run(["fake", "epa_echo"], now=NOW, last_success={})
    assert apply_outcomes(plan, succeeded=set()) is plan


def test_the_plan_renders_a_page_naming_every_source() -> None:
    plan = plan_run(["fake", "epa_tri"], now=NOW, last_success={"epa_tri": ago(1)})
    page = plan.markdown()
    assert "Nightly ETL plan" in page
    assert "fake" in page and "epa_tri" in page
    assert "carry" in page.lower()


def test_an_interval_of_zero_days_is_always_due() -> None:
    """Guards the boundary rather than the happy path."""
    always = Refresh(cadence="daily", every_days=0, why="test")
    assert always.due(last_success=NOW, now=NOW)[0]
