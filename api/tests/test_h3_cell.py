"""One definition of an acceptable cell index, and both edges using it.

The failure this replaces was a 500: `h3.is_valid_cell` accepts spellings the
`h3_cell` domain in migration 0001 does not, so a value that passed the router
failed in Postgres, and a request that was merely not in the accepted form was
reported as a fault in the server.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import h3_cell

CELL = "88444600ddfffff"


def test_a_canonical_resolution_8_cell_is_accepted() -> None:
    assert h3_cell.validate(CELL) == CELL


@pytest.mark.parametrize(
    "value",
    [
        "88444600DDFFFFF",  # upper case: valid to h3-py, rejected by the domain
        "0x88444600ddfffff",
        " 88444600ddfffff",
        "88444600ddfffff\n",
        "88444600ddfffg",
        "",
        "not-a-cell",
    ],
)
def test_a_non_canonical_index_is_rejected_rather_than_repaired(value: str) -> None:
    """Lower-casing an upper-case index would be a small kindness with a long
    tail: the cell id is the join key between the map, the API, the cache and
    the database, and an API accepting two spellings of one key stores two."""
    with pytest.raises(h3_cell.InvalidCell):
        h3_cell.validate(value)


def test_the_wrong_resolution_is_rejected_and_says_which() -> None:
    with pytest.raises(h3_cell.InvalidCell, match="resolution 7"):
        h3_cell.validate("87444600dffffff")


def test_fifteen_hex_digits_that_are_not_a_cell_are_rejected() -> None:
    """The shape is necessary and not sufficient."""
    with pytest.raises(h3_cell.InvalidCell, match="not a valid H3 cell"):
        h3_cell.validate("ffffffffffffffe")


# ---- Both edges ----------------------------------------------------------


@pytest.mark.parametrize("value", ["88444600DDFFFFF", "0x88444600ddfffff", "87444600dffffff"])
def test_the_hex_endpoint_answers_422_rather_than_500(client: TestClient, value: str) -> None:
    assert client.get(f"/hex/{value}").status_code == 422


@pytest.mark.parametrize("value", ["88444600DDFFFFF", "0x88444600ddfffff", "87444600dffffff"])
def test_the_draft_endpoint_validates_the_same_way(client: TestClient, value: str) -> None:
    """`/draft` did not validate at all, so a non-canonical index reached the
    query and came back as a 500."""
    response = client.post("/draft", json={"h3": value, "document_type": "public_comment_letter"})

    assert response.status_code == 422
