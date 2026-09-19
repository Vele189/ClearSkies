"""Methodology section 10: the Pollution Burden component.

The pollution half of the score, built from the Exposures and Environmental
Effects groups:

    PB_raw(h) = ( 1.0 · mean(Exposures) + 0.5 · mean(EnvEffects) ) / 1.5
    PB(h)     = 10 · PB_raw(h) / max_h PB_raw(h)

The assembly is in `component.py`, which both components share. What is decided
here is which groups belong to this component, and what a hex with too little
pollution data is called.

**The 1.0 / 0.5 ratio is a claim, not a default.** Section 10 weights measured and
modeled exposure at twice what the proximity-derived environmental effects
indicators get, because E1 through E4 estimate what reaches a person and F1
through F4 count what is nearby. Changing it is a methodology change with an
entry in that document's changelog, not an edit here.

**Falling back to Environmental Effects alone.** Section 11 rule 3. If fewer
than 2 of the 4 Exposures indicators are present the group is not computable and
the component is built from Environmental Effects alone, with the weights
re-normalizing so it is that group's mean rather than a third of it. The hex
keeps a score and takes a heavy confidence penalty, which `component.py`
computes as the surviving share of the component's weight — one third here,
because Exposures is two thirds of it. If neither group clears its minimum the
hex is `no_score` with reason `insufficient_pollution_data` and carries no
pollution number at all.

**AirToxScreen is the primary input, and stays primary by being two of four.**
E1 and E2 both come from AirToxScreen and both are modeled statewide, so in
practice they are the two Exposures indicators a hex almost always has. Nothing
here promotes them beyond that. Section 11 rule 2 sets the Exposures minimum at
2 of 4 and this module does not quietly raise it to "2 of 4, and one must be
AirToxScreen": that would be a stricter rule than the methodology states, and
the methodology is where it would have to be argued first.

**OpenAQ contributes without letting sensor absence read as cleanliness.** E4 is
measured PM2.5 and it is missing, never zero, beyond 25 km from a monitor. The
direction of that failure is the reason it matters: zero is the bottom of the
scale, so an absent monitor imputed to zero would give the hex the lowest
percentile in the state for E4, drag its Exposures mean down, and report a place
nobody has ever measured as cleaner than one that was measured and found clean.
An unmonitored area is uncertain, not clean. The guarantee runs through CS-201,
which never turns an absent value into a percentile, and section 11 rule 1,
which drops the indicator from the mean instead of filling it in. The cost lands
on `c_monitor` in section 12, where a reader can see it.
"""

from collections.abc import Collection, Mapping

from burden.component import ComponentResult, ComponentSpec, compute
from burden.indicators import group_spec
from burden.percentile import Ranking

EXPOSURES = "exposures"
ENVIRONMENTAL_EFFECTS = "environmental_effects"

# `Component.POLLUTION_BURDEN` in the registry of record, and the
# `pollution_burden` column on `hex_score`.
POLLUTION_BURDEN = ComponentSpec(
    name="pollution_burden",
    groups=(group_spec(EXPOSURES), group_spec(ENVIRONMENTAL_EFFECTS)),
    no_score_reason="insufficient_pollution_data",
)


def pollution_burden(
    rankings: Mapping[str, Ranking], *, scored: Collection[str]
) -> ComponentResult:
    """Score the pollution half over the scored hexes.

    `rankings` are the CS-201 percentile rankings keyed by indicator id, all
    ranked against this same set of scored hexes. Indicators outside E1 through
    E4 and F1 through F4 are ignored, so the whole run's rankings can be handed
    to both components.
    """
    return compute(POLLUTION_BURDEN, rankings, scored=scored)
