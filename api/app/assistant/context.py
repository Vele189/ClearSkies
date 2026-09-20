"""What the model is given about one hexagon, and nothing else.

CS-304 requires the model to work from retrieved context and supplied hexagon
data only. The retrieval half is `retrieval.as_context`. This is the other half:
the hexagon, rendered as text with every record carrying the identifier a
citation has to quote.

Two decisions worth stating.

**Every record is printed with its ID.** A facility described as "a chemical
plant 2 km north" cannot be cited, so the model either omits the claim or
invents an identifier for it. Printing the registry ID next to the name means
the citable form is the easy form.

**Absent values are printed as absent.** An indicator that was never observed
says so rather than being left out of the list. Section 11 spends a page on why
missing is not zero, and a model shown a list with a gap in it fills the gap
from what it knows about Louisiana, which is exactly the outside knowledge the
prompt forbids.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# How many contributing facilities to list. All of them, up to a limit that
# keeps one hexagon from filling the whole context window; the count is printed
# either way so the model never believes it has seen them all when it has not.
MAX_FACILITIES = 25


@dataclass
class HexContext:
    """One hexagon's data, as the model receives it."""

    h3: str
    parish: str | None
    score: float | None
    percentile: float | None
    confidence: float | None
    confidence_band: str
    methodology_version: str
    indicators: list[dict[str, Any]] = field(default_factory=list)
    demographics: dict[str, Any] = field(default_factory=dict)
    facilities: list[dict[str, Any]] = field(default_factory=list)
    data_vintage: dict[str, str] = field(default_factory=dict)

    def render(self) -> str:
        lines: list[str] = [
            "# Hexagon data",
            "",
            f"H3 cell: {self.h3} (resolution 8)",
            f"Parish: {self.parish or 'not recorded'}",
            f"Methodology version: {self.methodology_version}",
            "",
            "## Score",
            f"Burden score: {_number(self.score)} of 100",
            f"Statewide percentile: {_number(self.percentile)}",
            f"Confidence: {_number(self.confidence)} ({self.confidence_band})",
            "",
            (
                "The score describes modelled exposure, nearby permitted sources and "
                "a vulnerable population. It is not a finding of wrongdoing by any "
                "operator. Percentiles are Louisiana percentiles and not national ones."
            ),
        ]

        lines += ["", "## Indicators"]
        if not self.indicators:
            lines.append("None recorded.")
        for indicator in self.indicators:
            observed = indicator.get("observed", True)
            value = _number(indicator.get("value"))
            percentile = _number(indicator.get("percentile"))
            suffix = "" if observed else "   NOT OBSERVED, dropped from its group mean"
            lines.append(
                f"- {indicator.get('id')}: {indicator.get('name')} = {value} "
                f"{indicator.get('unit', '')}".rstrip()
                + f" (percentile {percentile}, source {indicator.get('source')})"
                + suffix
            )

        lines += [
            "",
            "## Demographics",
            (
                "Recorded and displayed, never an input to the score. Methodology "
                "section 14. You may report these as facts about the population. You "
                "may not infer from them why anything was built where it was."
            ),
        ]
        if not self.demographics:
            lines.append("None recorded.")
        for key, value in self.demographics.items():
            lines.append(f"- {key}: {_number(value) if isinstance(value, float) else value}")

        lines += ["", f"## Contributing facilities ({len(self.facilities)})"]
        if not self.facilities:
            lines.append(
                "None within the 10 km interaction radius. Do not refer to any "
                "facility by name; there are none in this data."
            )
        for facility in self.facilities[:MAX_FACILITIES]:
            lines.append(
                f"- {facility.get('name')} "
                f"[record_id {facility.get('registry_id')}, dataset echo] "
                f"{_number(facility.get('distance_km'))} km, "
                f"program {facility.get('program')}"
            )
        if len(self.facilities) > MAX_FACILITIES:
            lines.append(
                f"...and {len(self.facilities) - MAX_FACILITIES} more not listed here. "
                "Do not state a total you have not been given."
            )

        if self.data_vintage:
            lines += ["", "## Data vintage"]
            for source, vintage in sorted(self.data_vintage.items()):
                lines.append(f"- {source}: {vintage}")

        return "\n".join(lines)


def _number(value: Any) -> str:
    """A value, or the fact that there isn't one.

    "not recorded" rather than a blank or a zero. Section 11's whole argument is
    that missing is not zero, and a model shown a blank fills it in.
    """
    if value is None:
        return "not recorded"
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def build_prompt(hex_context: HexContext, passages: str, request: str) -> str:
    """The user message: the data, the passages, and what is being asked for.

    The passages and the hexagon data are labelled as the only sources, again,
    at the point they are handed over. The system prompt says it too. Saying it
    twice is cheap and the failure it prevents is a model treating the retrieved
    text as a starting point for what it already knows.
    """
    return "\n\n".join(
        [
            hex_context.render(),
            "# Retrieved statutory passages",
            "",
            (
                "These are the only legal authorities available to you. Cite a "
                "section by copying its label exactly as it appears in brackets."
                if passages
                else (
                    "No passage in the corpus was close enough to this request to "
                    "retrieve. You have no legal authority available. Refuse rather "
                    "than citing a statute from memory."
                )
            ),
            "",
            passages,
            "# What to draft",
            "",
            request,
        ]
    )
