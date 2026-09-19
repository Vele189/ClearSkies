"""Methodology section 10: the Population Characteristics component.

The demographic half of the score, built from the Sensitive Populations and
Socioeconomic Factors groups:

    PC_raw(h) = ( 1.0 · mean(Sensitive) + 1.0 · mean(Socioeconomic) ) / 2.0
    PC(h)     = 10 · PC_raw(h) / max_h PC_raw(h)

The assembly is in `component.py`, shared with Pollution Burden. What is decided
here is which groups belong to this component and what a hex with too little
demographic data is called.

The component is named for `Component.POPULATION_CHARACTERISTICS` in the
registry of record rather than the looser "vulnerability" the work was first
described as. Vulnerability is a word about people; what is being measured is
the age structure and economic circumstances of a place, and CalEnviroScreen's
own term says so without the extra claim.

**Both groups weigh 1.0, and the means are averaged rather than pooled.** This
is where averaging matters most. Socioeconomic Factors has five indicators to
Sensitive Populations' two, so pooling all seven percentiles would hand the
economic indicators five sevenths of this component for no reason beyond how
many of them there happen to be. Section 10 averages the two group means so the
two say equally much, and stays stable if an indicator is later added to either.

**Falling back to one group.** Section 11 rule 4. Sensitive Populations needs at
least 1 of its 2 and Socioeconomic Factors at least 4 of its 5; if one group
misses its minimum the component is the other group's mean outright, with the
weights re-normalizing, and the hex takes a confidence penalty. Both groups
weigh the same here, so either loss costs half the component's weight, which is
the symmetry the methodology implies and Pollution Burden's asymmetry does not
have. If neither group clears its minimum the hex is `no_score` with reason
`insufficient_population_data`.

**Hexes under 25 people never reach this module.** Section 5 excludes them from
the scored universe before anything is ranked, and they carry `low_population`
rather than a demographic reason. `eligibility.py` is where that happens, and
the distinction is worth keeping sharp: `low_population` says the methodology
declines to score a place with almost nobody in it, while
`insufficient_population_data` says a populated place had too little data to
describe. Collapsing the two would tell a reader in a rural hex that the census
failed them when in fact the cell holds eleven people.

**Race and ethnicity are not inputs, and this is the file that would be edited
to make them one.** Section 14 is the argument and it is evidentiary rather than
political. The project's central claim is that environmental burden in Louisiana
falls disproportionately on Black communities. If racial composition were an
input, the score would be high where the population is Black partly because the
formula put it there, the §13.6 correlation would be true by construction, and a
Title VI disparate-impact argument resting on it would be far weaker than one
resting on a metric that never reached for race. So the seven indicators here are
age structure and economic circumstance, and nothing else.

Race is not hidden. `Demographics` on the API response carries the composition
for every hex, the detail panel shows it beside the score, and CS-213 makes the
disparity analysis a headline output. The decision is about what enters the
arithmetic, not about what the tool talks about, and
`tests/test_population.py` keeps the arithmetic honest with a guard that fails
if a race or ethnicity indicator ever appears in the registry.
"""

from collections.abc import Collection, Mapping

from burden.component import ComponentResult, ComponentSpec, compute
from burden.indicators import group_spec
from burden.percentile import Ranking

SENSITIVE_POPULATIONS = "sensitive_populations"
SOCIOECONOMIC_FACTORS = "socioeconomic_factors"

# `Component.POPULATION_CHARACTERISTICS` in the registry of record, and the
# `population_characteristics` column on `hex_score`.
POPULATION_CHARACTERISTICS = ComponentSpec(
    name="population_characteristics",
    groups=(group_spec(SENSITIVE_POPULATIONS), group_spec(SOCIOECONOMIC_FACTORS)),
    no_score_reason="insufficient_population_data",
)


def population_characteristics(
    rankings: Mapping[str, Ranking], *, scored: Collection[str]
) -> ComponentResult:
    """Score the demographic half over the scored hexes.

    `scored` is `Eligibility.scored` from section 5: hexes under 25 people are
    already gone and carry `low_population`, not a reason from this component.
    Indicators outside S1, S2 and P1 through P5 are ignored, so the whole run's
    rankings can be handed to both components.
    """
    return compute(POPULATION_CHARACTERISTICS, rankings, scored=scored)
