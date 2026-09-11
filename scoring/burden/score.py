"""Methodology section 10 step 4: the burden score.

    Score(h) = PB(h) · PC(h)          range (0, 100]

Two numbers, each already rescaled to 0 through 10 by their own component,
multiplied. Nothing is rescaled again: the product of two values in (0, 10] is
already in (0, 100], which is what `CHECK (score > 0 AND score <= 100)` on
`hex_score` expects. It is strictly above zero because every percentile is
(section 9), so every group mean is, so every component is.

**The multiplication is the substantive claim.** Section 3 adopts it from
CalEnviroScreen deliberately: pollution in a place with low vulnerability and
vulnerability in a place with low pollution are both treated as less severe than
the two occurring together. An additive model would let a high score in one
component fully compensate for a low score in the other, which is not what
"cumulative burden" is meant to describe. The consequence a reader is most
likely to find surprising is section 10's own worked example, and it follows from
the arithmetic here: a hex at the 95th percentile for pollution and the 20th for
vulnerability scores about 19, while a hex at the 60th for both scores about 36.
The second is higher.

**The score's own distribution is recorded.** The map colours by percentile
rather than by raw score, because the raw distribution is heavily right-skewed
and a linear ramp on it would render most of the state indistinguishable. That
percentile is produced by the same section 9 machinery every indicator goes
through, ranked over the hexes that actually got a score, so a hex the run could
not score is in no denominator here either.

**Four reasons a hex has no score, and one column to hold them.** Section 5
supplies two before anything is computed: `outside_pilot_state` for a cell whose
centroid is over the line, `low_population` for one with fewer than 25
residents. The components supply the other two when a hex is in scope and
populated but too thinly described: `insufficient_pollution_data` and
`insufficient_population_data`. A hex that fails both components could honestly
carry either, and the column takes one string, so the tie breaks toward the
pollution reason. That is a convention rather than a finding, and it is safe to
make one because nothing is hidden by it: both components' group means are
persisted beside the reason, so the panel shows a reader that both halves failed
whichever name the column holds.

**Reproducibility is a property this module has to keep, not one it inherits.**
Section 13 requires the same inputs under the same methodology version to
produce identical output, and section 17 requires every published score to carry
the version that produced it. So the rows come out ordered by hex rather than by
whatever order a dict was built in, the arithmetic is stdlib floats throughout,
and `digest` hashes the canonical form of the whole run including the version.
Two runs that agree on that hash agree on every score; a run under a different
version does not collide with one under this version even if every number
matches, because a score means "this, under these rules".
"""

import hashlib
from dataclasses import dataclass
from typing import Any

from burden.component import ComponentResult, HexComponent
from burden.eligibility import Eligibility, NoScoreReason
from burden.methodology import METHODOLOGY_VERSION
from burden.percentile import Distribution, rank
from burden.pollution import ENVIRONMENTAL_EFFECTS, EXPOSURES
from burden.population import SENSITIVE_POPULATIONS, SOCIOECONOMIC_FACTORS


@dataclass(frozen=True, slots=True)
class HexScore:
    """One row of `hex_score`: the score, why there isn't one, and the parts.

    Exactly one of `score` and `no_score_reason` is set, which is the
    `hex_score_scored_xor_reason` constraint in migration 0009. Both would leave
    the map with a colour it cannot explain, and neither would leave a hole a
    reader has to guess at.

    The four `*_mean` fields are the subgroup means in percentile space, kept
    because the explain panel renders the waterfall from them and they cannot be
    recovered from the total once the weights have been applied.
    """

    h3: str
    score: float | None
    percentile: float | None
    pollution_burden: float | None
    population_characteristics: float | None
    exposures_mean: float | None
    env_effects_mean: float | None
    sensitive_mean: float | None
    socioeconomic_mean: float | None
    no_score_reason: NoScoreReason | None
    methodology_version: str


@dataclass(frozen=True, slots=True)
class ScoreRun:
    """Every hex the run knew about, scored or explained, plus the distribution."""

    hexes: tuple[HexScore, ...]
    distribution: Distribution
    methodology_version: str

    def by_h3(self) -> dict[str, HexScore]:
        return {row.h3: row for row in self.hexes}

    def scored(self) -> tuple[HexScore, ...]:
        return tuple(row for row in self.hexes if row.score is not None)

    def scored_hexes(self) -> int:
        """The count `pipeline_run.scored_hexes` records for the run."""
        return len(self.scored())

    def reasons(self) -> dict[NoScoreReason, int]:
        """How many hexes each no-score reason accounts for.

        A run where `low_population` suddenly halves has had something happen to
        the dasymetric step, and the shape of this map is the cheapest place to
        notice.
        """
        counts: dict[NoScoreReason, int] = {}
        for row in self.hexes:
            if row.no_score_reason is not None:
                counts[row.no_score_reason] = counts.get(row.no_score_reason, 0) + 1
        return counts

    def digest(self) -> str:
        """A stable hash of the whole run, for section 13's reproducibility claim.

        Covers the methodology version as well as the numbers, because a score
        is a statement about a place under a particular set of rules. Two runs
        of the same inputs under different versions are different results even
        when every figure agrees, and a digest that collided on them would be
        asserting something the paper denies.
        """
        hasher = hashlib.sha256()
        hasher.update(f"methodology={self.methodology_version}\n".encode())
        for row in self.hexes:
            hasher.update(_canonical(row).encode())
        return hasher.hexdigest()

    def rows_for_sql(self, *, run_id: int) -> list[dict[str, Any]]:
        """The payload the Postgres sink inserts into `hex_score`.

        Emitted as plain dicts because this package has no database dependency,
        on the same terms as `rows_for_sql` in the ingestion package's
        provenance module.

        The confidence columns are present and empty. CS-205 fills them, and
        naming them here means the insert shape does not change when it does.
        `methodology_version` is deliberately not among them: it lives on
        `pipeline_run`, and every row reaches it through `run_id`. Repeating one
        string across 150,000 rows is what the foreign key is for, and one
        version per run is what section 17 actually asks for.
        """
        return [
            {
                "run_id": run_id,
                "h3": row.h3,
                "score": row.score,
                "percentile": row.percentile,
                "pollution_burden": row.pollution_burden,
                "population_characteristics": row.population_characteristics,
                "exposures_mean": row.exposures_mean,
                "env_effects_mean": row.env_effects_mean,
                "sensitive_mean": row.sensitive_mean,
                "socioeconomic_mean": row.socioeconomic_mean,
                "confidence": None,
                "confidence_band": None,
                "c_coverage": None,
                "c_recency": None,
                "c_spatial": None,
                "c_monitor": None,
                "nearest_monitor_km": None,
                "no_score_reason": row.no_score_reason,
            }
            for row in self.hexes
        ]


def burden_score(
    *,
    eligibility: Eligibility,
    pollution: ComponentResult,
    population: ComponentResult,
    methodology_version: str = METHODOLOGY_VERSION,
) -> ScoreRun:
    """Compose the two components into one score per hex, per section 10 step 4.

    `eligibility` is the whole grid: the hexes section 5 scores and the ones it
    excludes, with the reason for each. Both components must have been computed
    over exactly the scored set, which is checked rather than assumed.
    """
    scored_set = set(eligibility.scored)
    _require_same_universe("pollution burden", pollution, scored_set)
    _require_same_universe("population characteristics", population, scored_set)

    pollution_rows = pollution.by_h3()
    population_rows = population.by_h3()

    composed: dict[str, float] = {}
    for h3 in eligibility.scored:
        pb = pollution_rows[h3].score
        pc = population_rows[h3].score
        if pb is not None and pc is not None:
            composed[h3] = pb * pc

    # The score's own statewide distribution, through the same section 9
    # machinery as every indicator. Only hexes that got a score are ranked, so
    # an unscorable hex is absent from this denominator exactly as it is from
    # every other one.
    ranked = rank(
        {h3: value for h3, value in composed.items()},
        scored=tuple(sorted(composed)),
    )
    percentiles = {row.h3: row.percentile for row in ranked.hexes}

    rows: list[HexScore] = []

    for excluded in eligibility.excluded:
        rows.append(
            HexScore(
                h3=excluded.h3,
                score=None,
                percentile=None,
                pollution_burden=None,
                population_characteristics=None,
                exposures_mean=None,
                env_effects_mean=None,
                sensitive_mean=None,
                socioeconomic_mean=None,
                no_score_reason=excluded.reason,
                methodology_version=methodology_version,
            )
        )

    for h3 in eligibility.scored:
        pollution_row = pollution_rows[h3]
        population_row = population_rows[h3]
        score = composed.get(h3)

        rows.append(
            HexScore(
                h3=h3,
                score=score,
                percentile=percentiles.get(h3),
                pollution_burden=pollution_row.score,
                population_characteristics=population_row.score,
                exposures_mean=pollution_row.group_mean(EXPOSURES),
                env_effects_mean=pollution_row.group_mean(ENVIRONMENTAL_EFFECTS),
                sensitive_mean=population_row.group_mean(SENSITIVE_POPULATIONS),
                socioeconomic_mean=population_row.group_mean(SOCIOECONOMIC_FACTORS),
                no_score_reason=(
                    None if score is not None else _failure(pollution_row, population_row)
                ),
                methodology_version=methodology_version,
            )
        )

    rows.sort(key=lambda row: row.h3)

    return ScoreRun(
        hexes=tuple(rows),
        distribution=ranked.distribution,
        methodology_version=methodology_version,
    )


def _failure(pollution: HexComponent, population: HexComponent) -> NoScoreReason:
    """Which reason a scored-universe hex carries when it could not be scored.

    Pollution first when both failed. The tie-break is a convention, and it
    costs a reader nothing because both components' group means sit beside it.
    """
    reason = pollution.no_score_reason or population.no_score_reason
    assert reason is not None, "a hex with no score must have a reason from one component"
    # Both components' reasons are drawn from the four `hex_score` accepts.
    return reason  # type: ignore[return-value]


def _require_same_universe(name: str, result: ComponentResult, scored: set[str]) -> None:
    covered = {row.h3 for row in result.hexes}
    if covered != scored:
        raise ValueError(
            f"the {name} component covers a different set of hexes than section 5 "
            f"made eligible; the two cannot be composed"
        )


def _canonical(row: HexScore) -> str:
    """One line per hex, in a form that does not vary between equal runs."""
    fields = (
        row.h3,
        _number(row.score),
        _number(row.percentile),
        _number(row.pollution_burden),
        _number(row.population_characteristics),
        _number(row.exposures_mean),
        _number(row.env_effects_mean),
        _number(row.sensitive_mean),
        _number(row.socioeconomic_mean),
        row.no_score_reason or "",
    )
    return "|".join(fields) + "\n"


def _number(value: float | None) -> str:
    # repr round-trips a float exactly and is the shortest string that does, so
    # two runs that computed the same bits write the same characters.
    return "" if value is None else repr(value)
