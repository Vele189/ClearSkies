"""The refusal channel, and the band that cannot be drafted from.

Two guardrails that are code rather than prose, because the prompt layer is the
one place in this system that can be argued with.

**Refusal is an output, not an absence.** A model given a document schema and
nothing else has no way to say "the passages you gave me do not support this".
Its options are to produce the document anyway or to fail validation, and the
first is what it will do, because producing the requested shape is what the
schema asks for. So the agent's output type is a union: the document, or a
`Refusal` naming what was missing. Giving the model a legitimate way to decline
is what makes declining something it will actually do.

**The insufficient band is refused before the model is called.** Section 12 says
a hexagon in that band is one the pipeline does not trust its own number for.
Producing a cited complaint from it would be the most damaging thing this tool
could do: the document would be indistinguishable from a good one, and its
foundation would be a score the system itself does not stand behind. The refusal
is in the type (CS-303), in the prompt (v1/system.md), and here, and none of the
three is redundant. The type stops a draft being assembled, the prompt stops the
model going along with it, and this stops the request reaching the model at all.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Section 12's bands.
CONFIDENCE_BANDS = ("high", "moderate", "low", "insufficient")

# The one that cannot produce a document. Named as a constant rather than
# written as a comparison in four places, so there is one thing to find.
REFUSED_BAND = "insufficient"

RefusalReason = Literal[
    "no_supporting_authority",
    "insufficient_data",
    "would_require_prohibited_claim",
    "request_seeks_legal_advice",
    "request_out_of_scope",
]


class Refusal(BaseModel):
    """The model declining to produce a document, with a reason.

    This is a success from the system's point of view. A refusal that names what
    was missing tells a user something true and lets them look for it. A
    document built on an invented fact tells them something false in a form
    designed to be persuasive, which is the failure the whole phase exists to
    prevent.
    """

    model_config = ConfigDict(extra="forbid")

    refused: Literal[True] = True
    reason: RefusalReason = Field(description="Which rule stopped the draft. Pick the closest.")
    explanation: str = Field(
        min_length=1,
        description=(
            "One or two sentences a non-lawyer can act on, naming what was "
            "missing. Not an apology, and never a partial draft."
        ),
    )
    missing: list[str] = Field(
        default_factory=list,
        description=(
            "Specific things that would have been needed, e.g. a statute that "
            "was not in the retrieved passages."
        ),
    )


class InsufficientConfidence(RuntimeError):
    """The hexagon is in the band that may not be drafted from.

    Carries the plain-language explanation the interface shows. CS-307 renders
    this rather than an error code, because the reader is being told the tool
    does not trust its own number for their neighbourhood, and that deserves a
    sentence rather than a status.
    """

    def __init__(self, h3: str, band: str) -> None:
        self.h3 = h3
        self.band = band
        super().__init__(
            f"hexagon {h3} is in the {band} confidence band and cannot be drafted from"
        )

    @property
    def explanation(self) -> str:
        return (
            "There is not enough data behind this hexagon's score for us to stand "
            "behind a document built on it. The score is shown with its confidence "
            "so you can see why, but drafting from it would give you a document "
            "that looks well supported and is not. Nearby hexagons with better "
            "coverage can be drafted from."
        )


def check_band(h3: str, band: str) -> None:
    """Raise unless this hexagon may be drafted from.

    Called before retrieval and before the model, so an insufficient hexagon
    costs nothing and, more to the point, never has a document written for it
    that some later check has to catch.
    """
    if band not in CONFIDENCE_BANDS:
        raise ValueError(f"{band!r} is not one of section 12's bands: {CONFIDENCE_BANDS}")
    if band == REFUSED_BAND:
        raise InsufficientConfidence(h3, band)
