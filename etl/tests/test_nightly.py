"""The scheduled run, end to end, through the command the workflow calls.

`test_schedule.py` proves the planner and `test_ledger.py` proves the promotion
rule. This proves they are wired together: that a night which pulls nothing does
not promote itself, that a night which fails does not either, and that the
cadence actually stops the second run of the same day from re-pulling.

Everything runs against the reference adapter, which reads a fixture rather than
a network, so these are real end-to-end runs rather than mocks of one.
"""

from pathlib import Path

from pipeline.ledger import RunLedger


def nightly(state: Path, store: Path, *extra: str) -> int:
    from pipeline.__main__ import main

    return main(["nightly", "fake", "--state", str(state), "--store", str(store), *extra])


def test_a_first_night_pulls_and_promotes_itself(tmp_path: Path) -> None:
    state, store = tmp_path / "state", tmp_path / "store"
    assert nightly(state, store) == 0

    ledger = RunLedger(state)
    current = ledger.current()
    assert current is not None
    assert current.outcome_for("fake") is not None
    assert current.outcome_for("fake").action == "pull"  # type: ignore[union-attr]


def test_the_report_and_the_ledger_are_both_written(tmp_path: Path) -> None:
    """A night has to leave evidence in both places: what it checked, and what it was."""
    state, store = tmp_path / "state", tmp_path / "store"
    nightly(state, store)

    assert list(store.glob("*/report.json")), "no quality report was persisted"
    assert (state / "runs.jsonl").exists(), "the night was not recorded"
    assert (state / "current.json").exists(), "nothing was promoted"


def test_the_second_run_of_the_same_day_carries_rather_than_re_pulling(tmp_path: Path) -> None:
    """The cadence, observed through the command rather than through the planner."""
    state, store = tmp_path / "state", tmp_path / "store"
    nightly(state, store)
    assert nightly(state, store) == 0

    runs = RunLedger(state).runs()
    assert len(runs) == 2
    assert runs[0].outcome_for("fake").action == "pull"  # type: ignore[union-attr]
    assert runs[1].outcome_for("fake").action == "carry"  # type: ignore[union-attr]


def test_a_night_that_pulled_nothing_does_not_become_the_served_run(tmp_path: Path) -> None:
    """A gate with nothing to check passes by having no opinion.

    Promoting on the strength of a report made entirely of skips is the exact
    shape CS-108 exists to refuse, so an idle night leaves the previous run
    serving even though it exited zero.
    """
    state, store = tmp_path / "state", tmp_path / "store"
    nightly(state, store)
    first = RunLedger(state).current()
    assert first is not None

    assert nightly(state, store) == 0
    still = RunLedger(state).current()
    assert still is not None
    assert still.run_id == first.run_id, "an idle night replaced the served run"


def test_force_pulls_a_source_the_cadence_would_have_carried(tmp_path: Path) -> None:
    state, store = tmp_path / "state", tmp_path / "store"
    nightly(state, store)
    assert nightly(state, store, "--force", "fake") == 0

    runs = RunLedger(state).runs()
    assert runs[-1].outcome_for("fake").action == "pull"  # type: ignore[union-attr]
    current = RunLedger(state).current()
    assert current is not None
    assert current.run_id == runs[-1].run_id


def test_a_failed_gate_exits_one_and_promotes_nothing(tmp_path: Path) -> None:
    """Requiring a source that is not registered fails the night."""
    state, store = tmp_path / "state", tmp_path / "store"
    nightly(state, store)
    served = RunLedger(state).current()
    assert served is not None

    assert nightly(state, store, "--force", "fake", "--require", "epa_echo") == 1

    still = RunLedger(state).current()
    assert still is not None
    assert still.run_id == served.run_id, "a failed night replaced the served run"
    assert RunLedger(state).runs()[-1].status == "failed"


def test_requiring_a_carried_source_does_not_fail_the_night(tmp_path: Path) -> None:
    """`--require` means "produced what it was asked for", and a carried source
    was asked for nothing. Otherwise every cadence would fail its own run."""
    state, store = tmp_path / "state", tmp_path / "store"
    nightly(state, store)
    assert nightly(state, store, "--require", "fake") == 0

    last = RunLedger(state).runs()[-1]
    assert last.status == "succeeded"
    assert any("carried tonight by its cadence" in note for note in last.notes)


def test_two_runs_in_the_same_second_get_different_identities(tmp_path: Path) -> None:
    state, store = tmp_path / "state", tmp_path / "store"
    for _ in range(3):
        nightly(state, store, "--force", "fake")

    ids = [run.run_id for run in RunLedger(state).runs()]
    assert len(ids) == len(set(ids)), f"duplicate run ids: {ids}"


def test_plan_reports_without_pulling_anything(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    from pipeline.__main__ import main

    state = tmp_path / "state"
    assert main(["plan", "fake", "--state", str(state)]) == 0
    assert "fake" in capsys.readouterr().out
    assert not (state / "runs.jsonl").exists(), "plan recorded a run"


def test_runs_lists_the_ledger_and_marks_the_served_run(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    from pipeline.__main__ import main

    state, store = tmp_path / "state", tmp_path / "store"
    nightly(state, store)
    assert main(["runs", "--state", str(state)]) == 0

    out = capsys.readouterr().out
    assert "current" in out
    assert "fake" in out


def test_runs_says_so_when_nothing_has_been_promoted(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    from pipeline.__main__ import main

    assert main(["runs", "--state", str(tmp_path)]) == 0
    assert "no runs recorded" in capsys.readouterr().out


def test_the_night_records_where_its_data_came_from(tmp_path: Path) -> None:
    """CS-110: the manifest outlives the run directory that held it."""
    from pipeline.provenance import ProvenanceStore

    state, store = tmp_path / "state", tmp_path / "store"
    nightly(state, store)

    recorded = ProvenanceStore(state).history()
    assert [p.source for p in recorded] == ["fake"]
    assert ProvenanceStore(state).run_ids() == [RunLedger(state).runs()[-1].run_id]


def test_a_carried_night_adds_no_provenance_row(tmp_path: Path) -> None:
    """Nothing was pulled, so nothing new came from anywhere."""
    from pipeline.provenance import ProvenanceStore

    state, store = tmp_path / "state", tmp_path / "store"
    nightly(state, store)
    nightly(state, store)

    assert len(ProvenanceStore(state).history()) == 1


def test_the_provenance_command_regenerates_the_page(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    from pipeline.__main__ import main
    from pipeline.provenance import BEGIN, END

    state, store = tmp_path / "state", tmp_path / "store"
    nightly(state, store)

    page = tmp_path / "provenance.md"
    page.write_text(f"# Provenance\n\n{BEGIN}\n\n_Nothing yet._\n\n{END}\n", encoding="utf-8")

    assert main(["provenance", "--state", str(state), "--page", str(page)]) == 0
    assert "fake" in page.read_text()
    assert "updated" in capsys.readouterr().out


def test_regenerating_a_missing_page_fails_rather_than_creating_one(tmp_path: Path) -> None:
    from pipeline.__main__ import main

    assert main(["provenance", "--state", str(tmp_path), "--page", str(tmp_path / "gone.md")]) == 1
