"""CS-213: `python -m pipeline disparity`, and the status it is allowed to exit with.

The analysis itself is covered by `test_disparity.py`. What is left to hold in
place here is the command around it, and one property of that command matters
more than the rest: its exit status may depend on whether the analysis ran and
never on what the analysis found. Section 13.6 makes the disparity finding a
reported result, and a command that exited 1 on a weak coefficient would quietly
turn the project's headline finding into a gate that somebody eventually tunes a
weight to satisfy.

The connection is faked rather than mocked at the driver. `run_disparity` takes a
connection precisely so this is possible, and `pipeline.db.connection` is the one
seam the command opens.
"""

import json
import random
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from pipeline import __main__ as cli
from pipeline import db
from pipeline.analysis import FRAMING, INDEPENDENCE

# Small enough to keep the suite quick. The production default is 2000, and the
# command's own default is that one.
RESAMPLES = 120

PARISHES = (
    "Ascension",
    "Calcasieu",
    "East Baton Rouge",
    "Iberville",
    "Jefferson",
    "Lafourche",
    "Orleans",
    "Plaquemines",
    "St. Bernard",
    "St. Charles",
    "St. James",
    "West Baton Rouge",
)


class FakeConnection:
    """Enough asyncpg to satisfy the protocol the analysis declares."""

    def __init__(
        self,
        rows: Sequence[Mapping[str, Any]] = (),
        current: Mapping[str, Any] | None = None,
    ) -> None:
        self.rows = list(rows)
        self.current = current
        self.queries: list[tuple[str, tuple[Any, ...]]] = []

    async def fetch(self, query: str, *args: Any) -> Sequence[Mapping[str, Any]]:
        self.queries.append((query, args))
        return self.rows

    async def fetchrow(self, query: str, *args: Any) -> Mapping[str, Any] | None:
        self.queries.append((query, args))
        return self.current


def scored_rows(*, slope: float, count: int = 240) -> list[dict[str, Any]]:
    """Rows whose Black share tracks the percentile by `slope`, plus noise.

    `slope` of zero is the case the framing tests care about: a dataset with no
    relationship in it, which must be reported as a near-zero coefficient rather
    than becoming a failing exit status.
    """
    rng = random.Random(7)
    rows: list[dict[str, Any]] = []
    for index in range(count):
        percentile = (index % 100) + 0.5
        black = max(0.0, min(100.0, 30.0 + slope * (percentile - 50.0) + rng.gauss(0, 6)))
        rows.append(
            {
                "h3": f"8844a1b2c{index:04x}fff",
                "percentile": percentile,
                "confidence_band": "high",
                "population": 400.0 + rng.random() * 3000.0,
                "black_pct": black,
                "people_of_color_pct": min(100.0, black + 9.0),
                "acs_vintage": "2020-2024",
                "cluster": PARISHES[index % len(PARISHES)],
            }
        )
    return rows


@pytest.fixture
def connect(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Hand the command a connection without a database behind it."""

    def install(conn: FakeConnection | None, *, unavailable: bool = False) -> FakeConnection | None:
        @asynccontextmanager
        async def fake_connection(url: str | None = None) -> AsyncIterator[Any]:
            if unavailable:
                raise db.DatabaseUnavailable("DATABASE_URL is not set")
            yield conn

        # Patched on the module rather than on the command's reference to it,
        # because `__main__` imports the module and not the function: there is
        # one object to replace, and it is this one.
        monkeypatch.setattr(db, "connection", fake_connection)
        return conn

    return install


# ---- what it prints ----------------------------------------------------


def test_a_scored_run_prints_the_page_and_exits_zero(
    connect: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    connect(
        FakeConnection(
            scored_rows(slope=0.6), current={"run_id": 42, "methodology_version": "0.1.4"}
        )
    )

    status = cli.main(["disparity", "--resamples", str(RESAMPLES)])

    assert status == 0
    page = capsys.readouterr().out
    assert page.startswith("# Disparity analysis")
    assert "Black population share" in page


def test_the_page_argues_before_it_reports(
    connect: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """Section 13.6: the argument travels with the number, and comes first."""
    connect(
        FakeConnection(
            scored_rows(slope=0.6), current={"run_id": 42, "methodology_version": "0.1.4"}
        )
    )

    cli.main(["disparity", "--resamples", str(RESAMPLES)])

    page = capsys.readouterr().out
    assert INDEPENDENCE in page
    assert FRAMING in page
    assert page.index(INDEPENDENCE) < page.index("## Correlations")


def test_json_output_carries_both_arguments_beside_the_coefficients(
    connect: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    connect(
        FakeConnection(
            scored_rows(slope=0.6), current={"run_id": 42, "methodology_version": "0.1.4"}
        )
    )

    status = cli.main(["disparity", "--json", "--resamples", str(RESAMPLES)])

    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["framing"] == FRAMING
    assert payload["independence"] == INDEPENDENCE
    assert payload["status"] == "computed"
    assert payload["correlations"]


def test_out_writes_the_page_where_the_write_up_can_read_it(
    connect: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """CS-409 and CS-207 render the finding; this is the file they render from."""
    connect(
        FakeConnection(
            scored_rows(slope=0.6), current={"run_id": 42, "methodology_version": "0.1.4"}
        )
    )
    target = tmp_path / "generated" / "disparity.md"

    status = cli.main(["disparity", "--out", str(target), "--resamples", str(RESAMPLES)])

    assert status == 0
    written = target.read_text(encoding="utf-8")
    assert written == capsys.readouterr().out
    assert INDEPENDENCE in written


# ---- what its exit status may depend on --------------------------------


def test_a_dataset_with_no_relationship_is_still_a_successful_run(
    connect: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """The property this command exists to protect.

    A near-zero coefficient is a finding, not a failure. If this ever exits
    non-zero, the headline finding has become a gate and section 13.6 has been
    broken by the command line rather than by the analysis.
    """
    connect(
        FakeConnection(
            scored_rows(slope=0.0), current={"run_id": 42, "methodology_version": "0.1.4"}
        )
    )

    status = cli.main(["disparity", "--json", "--resamples", str(RESAMPLES)])

    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    coefficients = [abs(c["coefficient"]) for c in payload["correlations"]]
    assert coefficients and max(coefficients) < 0.2


def test_a_strong_and_a_weak_finding_exit_the_same_way(connect: Any) -> None:
    strong = connect(
        FakeConnection(
            scored_rows(slope=0.9), current={"run_id": 42, "methodology_version": "0.1.4"}
        )
    )
    assert strong is not None
    assert cli.main(["disparity", "--resamples", str(RESAMPLES)]) == 0

    connect(
        FakeConnection(
            scored_rows(slope=0.0), current={"run_id": 42, "methodology_version": "0.1.4"}
        )
    )
    assert cli.main(["disparity", "--resamples", str(RESAMPLES)]) == 0


def test_an_unscored_run_exits_one_and_names_the_ticket_that_owns_it(
    connect: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    connect(FakeConnection([], current={"run_id": 42, "methodology_version": "0.1.4"}))

    status = cli.main(["disparity"])

    assert status == 1
    page = capsys.readouterr().out
    assert "CS-204" in page
    assert INDEPENDENCE in page


def test_no_current_run_is_reported_as_a_page_rather_than_a_traceback(
    connect: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    connect(FakeConnection([], current=None))

    status = cli.main(["disparity"])

    assert status == 1
    assert "CS-204" in capsys.readouterr().out


def test_no_database_is_a_different_status_from_no_scores(
    connect: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    connect(None, unavailable=True)

    status = cli.main(["disparity"])

    captured = capsys.readouterr()
    assert status == 2
    assert captured.out == ""
    assert "needs a database" in captured.err


# ---- what it is pointed at ---------------------------------------------


def test_run_analyses_that_run_and_never_asks_which_one_is_current(connect: Any) -> None:
    conn = connect(FakeConnection(scored_rows(slope=0.6)))
    assert conn is not None

    status = cli.main(["disparity", "--run", "91", "--resamples", str(RESAMPLES)])

    assert status == 0
    assert conn.queries[0][1] == (91,)
    assert not any("is_current" in query for query, _ in conn.queries)


def test_without_run_it_asks_for_the_run_the_site_is_serving(connect: Any) -> None:
    conn = connect(
        FakeConnection(
            scored_rows(slope=0.6), current={"run_id": 42, "methodology_version": "0.1.4"}
        )
    )
    assert conn is not None

    cli.main(["disparity", "--resamples", str(RESAMPLES)])

    assert "is_current" in conn.queries[0][0]


def test_the_seed_is_fixed_so_two_runs_over_the_same_rows_agree(
    connect: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """§13.6 asks the interval to be reproducible, as §9 asks of the scores."""
    for _ in range(2):
        connect(
            FakeConnection(
                scored_rows(slope=0.6), current={"run_id": 42, "methodology_version": "0.1.4"}
            )
        )
        cli.main(["disparity", "--json", "--resamples", str(RESAMPLES)])

    first, second = capsys.readouterr().out.split("}\n{")
    assert json.loads(first + "}")["correlations"] == json.loads("{" + second)["correlations"]


def test_a_confidence_level_outside_the_unit_interval_is_refused(connect: Any) -> None:
    connect(FakeConnection(scored_rows(slope=0.6)))

    with pytest.raises(SystemExit) as raised:
        cli.main(["disparity", "--level", "95"])

    assert raised.value.code == 2
