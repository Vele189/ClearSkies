#!/usr/bin/env python3
"""Rebuild `scoring/tests/fixtures/synthetic_values.json`, the 13.5 harness input.

Beside `make_validation_fixture.py` and for the same reason: the numbers it
writes are invented, and their only job is to drive every branch of
`burden.robustness` through `scripts/run_robustness.py` so CI can prove that
command still runs the section 13.5 checks without a database.

    python3 scripts/make_robustness_fixture.py

It is built to **fail** on purpose, exactly as the validation fixture is. A
fixture that produced a green robustness result would sooner or later be quoted
as one, and section 13.5's whole subject is results that are artifacts of their
own construction.

**How it is built to fail, and why that shape.** Environmental Effects ranks the
grid backwards from Exposures, with adjacent pairs transposed. Under section 10
the Exposures group is worth twice Environmental Effects, so Pollution Burden
still follows Exposures; weight the two equally and they very nearly cancel, and
the state comes out in a different order. That drives the equal-weighting variant
well below the 0.85 bar while leaving the Exposures-only variant almost
untouched, which is the failure mode section 13.5 exists to catch rather than an
arbitrary miss.

The leave-one-out check fails too, on E1 and E2, because twelve hexes are given
exactly those two Exposures indicators and no Environmental Effects at all.
Removing either takes the pollution half below its section 11 rule 2 minimum with
nothing to fall back to, and those hexes lose their score rather than moving a
decile. Both branches are worth exercising, and the report distinguishes them.

Three other shapes are written in so the rest of the branches run: a block of
hexes below the section 5 population threshold, a block section 12 bans from
validation statistics, and eight hexes holding four of the five Socioeconomic
Factors, so that removing one of the four trips the count rule. The `areal` block
is the same grid re-estimated so that a different set of cells clears the
25-person line, which is most of what the interpolation check is about.
"""

import json
import pathlib
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "scoring" / "tests" / "fixtures" / "synthetic_values.json"

METHODOLOGY_VERSION = "0.1.3"
COUNT = 140

EXPOSURES = ("E1", "E2", "E3", "E4")
ENVIRONMENTAL_EFFECTS = ("F1", "F2", "F3", "F4")
SENSITIVE = ("S1", "S2")
SOCIOECONOMIC = ("P1", "P2", "P3", "P4", "P5")


def cells(count: int) -> list[str]:
    """Invented cell names, zero-padded so they sort in generation order.

    Deliberately not H3 indexes. `synthetic_scores.json` uses real cell names
    because the gate joins them against the frozen validation fixture; nothing
    here joins against anything, and a name that cannot be mistaken for a
    Louisiana cell is the safer choice for a file full of invented numbers.
    """
    return [f"synthetic-{index:04d}" for index in range(count)]


def transposed_reverse(count: int) -> list[int]:
    """Reverse, with every adjacent pair swapped.

    Plain reverse cancels to a constant under equal weighting, and a constant has
    no ordering to correlate against, so the check would come back undefined
    rather than low. The transposition leaves something behind for the
    cancellation to be measured against.
    """
    order = list(range(count - 1, -1, -1))
    for index in range(0, count - 1, 2):
        order[index], order[index + 1] = order[index + 1], order[index]
    return order


def build_indicators(
    names: list[str], *, jitter: int = 0
) -> dict[str, dict[str, float | None]]:
    """The grid's raw indicator values.

    `jitter` rotates the ordering by that many places for the areal block, so the
    two interpolations disagree about where hexes stand without disagreeing about
    everything. A second block that held identical values would report a rank
    correlation of exactly 1.0 and exercise none of the arithmetic the third
    check is made of.
    """
    count = len(names)
    backwards = transposed_reverse(count)
    values: dict[str, dict[str, float | None]] = {}

    def ladder(position: int) -> float:
        return float((position + jitter) % count)

    for indicator in EXPOSURES:
        values[indicator] = {h3: ladder(index) for index, h3 in enumerate(names)}
    for indicator in ENVIRONMENTAL_EFFECTS:
        values[indicator] = {h3: ladder(backwards[index]) for index, h3 in enumerate(names)}
    # The demographic half says the same thing about every hex, so the ordering
    # is the pollution half's and the equal-weighting variant has nowhere else to
    # get one. That is what makes the failure below attributable to the weight.
    # It also puts every hex in one tie block, which is the shape section 9 warns
    # about for E3 and F1 through F4 and the case the rank correlation's
    # mid-rank handling exists for.
    for indicator in SENSITIVE + SOCIOECONOMIC:
        values[indicator] = {h3: 1.0 for h3 in names}

    # Absences, never zeros. These twelve hexes hold exactly two Exposures
    # indicators and no Environmental Effects at all, so the pollution half is
    # computable only while both survive. Removing E1 takes them out of the score
    # entirely, which the leave-one-out check reports as a lost score rather than
    # as a decile move.
    for indicator in EXPOSURES[2:] + ENVIRONMENTAL_EFFECTS:
        for h3 in names[100:112]:
            values[indicator][h3] = None
    # And these eight hold four of the five Socioeconomic Factors, so removing
    # any of the four trips the 4-of-5 minimum. Reported apart from the movement
    # itself, because it is a property of the count rule rather than of the
    # indicator.
    for h3 in names[112:120]:
        values[SOCIOECONOMIC[4]][h3] = None

    return values


def build_hexes(names: list[str], *, populations: list[float]) -> dict[str, dict[str, Any]]:
    hexes: dict[str, dict[str, Any]] = {}
    for index, h3 in enumerate(names):
        row: dict[str, Any] = {
            "population": populations[index],
            # Section 12 bars the insufficient band from validation statistics,
            # and section 13.5 is a validation statistic. Ten hexes carry it so
            # the exclusion is exercised rather than assumed.
            "confidence_band": "insufficient" if 60 <= index < 70 else "moderate",
        }
        if index >= COUNT - 5:
            # Section 5's other exclusion. These never reach a percentile
            # denominator under either interpolation.
            row["outside_pilot_state"] = True
        hexes[h3] = row
    return hexes


def main() -> None:
    names = cells(COUNT)

    # Dasymetric: twenty cells below the 25-person threshold of section 5.
    dasymetric_population = [8.0 if index < 20 else 400.0 + index for index in range(COUNT)]
    # Areal: the same grid with the people spread by area instead, which moves
    # six cells across the threshold in each direction. Which cells get a score
    # at all is the largest single consequence of the choice, and a fixture whose
    # two universes matched would never exercise the part of the check that says
    # so.
    areal_population = [
        (400.0 if 14 <= index < 20 else 8.0)
        if index < 26
        else 400.0 + index
        for index in range(COUNT)
    ]

    payload = {
        "source": "SYNTHETIC HARNESS FIXTURE - invented indicator values, not a scored run",
        "note": (
            "Built by make_robustness_fixture.py to exercise every branch of the "
            "section 13.5 checks without a database. Deliberately fails the "
            "equal-weighting variant and two leave-one-out indicators, so it "
            "cannot be mistaken for a robustness result."
        ),
        "methodology_version": METHODOLOGY_VERSION,
        "hexes": build_hexes(names, populations=dasymetric_population),
        "indicators": build_indicators(names),
        "areal": {
            "hexes": build_hexes(names, populations=areal_population),
            "indicators": build_indicators(names, jitter=9),
        },
    }

    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
