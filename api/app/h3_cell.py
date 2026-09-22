"""One definition of "an H3 cell this API accepts", used everywhere.

There were two, and the gap between them was a 500. `/hex/{h3}` asked
`h3.is_valid_cell`, which happily accepts `88444600DDFFFFF` and
`0x88444600ddfffff`, and passed the string on to a query whose parameter is the
`h3_cell` domain from migration 0001: fifteen lower-case hex digits, nothing
else. Postgres then raised a domain violation, which reaches the client as a
500 -- the server reporting a bug in itself over a request that was simply not
in the form it accepts. `/draft` did not validate at all.

So the rule lives here and both edges use it. A cell is acceptable when it is
fifteen lower-case hex digits, a valid H3 index, and resolution 8.

**Non-canonical input is rejected rather than normalised.** Lower-casing an
upper-case index would be a small kindness with a long tail: the cell id is the
join key between the map, the API, the cache and the database, and an API that
quietly accepts two spellings of one key is an API where two spellings end up
stored. 422 with a sentence saying what the form is costs the caller one fix.
"""

from __future__ import annotations

import re
from typing import Annotated

import h3
from pydantic import AfterValidator

# Methodology section 5. The grid is resolution 8 and nothing else is scored.
TARGET_RESOLUTION = 8

# The `h3_cell` domain from migration 0001, as a Python pattern. `\Z` and not
# `$`, which also matches before a trailing newline and would let
# "88444600ddfffff\n" through to the query the domain then rejects.
CANONICAL = re.compile(r"\A[0-9a-f]{15}\Z")


class InvalidCell(ValueError):
    """The value is not an H3 cell this API can answer about."""


def validate(value: str) -> str:
    """The value unchanged, or `InvalidCell` saying which rule it broke."""
    if not CANONICAL.match(value):
        raise InvalidCell(
            f"{value!r} is not an H3 cell index: expected fifteen lower-case hex "
            "digits, e.g. 88444600ddfffff"
        )
    if not h3.is_valid_cell(value):
        raise InvalidCell(f"{value!r} is not a valid H3 cell index")
    resolution = h3.get_resolution(value)
    if resolution != TARGET_RESOLUTION:
        raise InvalidCell(
            f"Cell is resolution {resolution}; ClearSkies scores resolution "
            f"{TARGET_RESOLUTION}. See docs/methodology.md section 5."
        )
    return value


# For a request body: a `ValueError` from a validator is what FastAPI turns
# into a 422, so the body and the path report the same failures the same way.
H3Cell = Annotated[str, AfterValidator(validate)]
