"""What the model is shown about one hexagon.

Most of these are about absence: a value that was never observed, a facility
list that is empty, a list that was truncated. Every one of them is a place
where a model shown nothing fills in what it knows about Louisiana, which is
exactly the outside knowledge the prompt forbids.
"""

from __future__ import annotations

from app.assistant.context import MAX_FACILITIES, HexContext, build_prompt


def hexagon(**overrides: object) -> HexContext:
    fields: dict[str, object] = {
        "h3": "88444600ddfffff",
        "parish": "St. James",
        "score": 81.4,
        "percentile": 94.2,
        "confidence": 0.71,
        "confidence_band": "moderate",
        "methodology_version": "0.1.4",
    }
    fields.update(overrides)
    return HexContext(**fields)  # type: ignore[arg-type]


def test_the_score_is_framed_as_what_it_is() -> None:
    """Section 15, carried into the context rather than left to the prompt
    alone. The model reads this next to the number."""
    rendered = hexagon().render()

    assert "not a finding of wrongdoing by any operator" in rendered
    assert "Louisiana percentiles and not national ones" in rendered


def test_an_unobserved_indicator_says_so_rather_than_being_omitted() -> None:
    """Section 11: missing is not zero. A model shown a list with a gap fills
    the gap."""
    rendered = hexagon(
        indicators=[
            {
                "id": "E4",
                "name": "Monitored NO2",
                "value": None,
                "percentile": None,
                "unit": "ppb",
                "source": "OpenAQ",
                "observed": False,
            }
        ]
    ).render()

    assert "E4" in rendered
    assert "NOT OBSERVED" in rendered
    assert "not recorded" in rendered


def test_an_absent_score_is_printed_as_absent() -> None:
    rendered = hexagon(score=None, percentile=None).render()

    assert "not recorded" in rendered
    assert "0.0 of 100" not in rendered


def test_every_facility_carries_the_identifier_a_citation_needs() -> None:
    """A facility described only by name cannot be cited, so a model that wants
    the claim invents an identifier for it."""
    rendered = hexagon(
        facilities=[
            {
                "name": "NUCOR STEEL LOUISIANA",
                "registry_id": "110000350053",
                "distance_km": 3.2,
                "program": "CAA Title V",
            }
        ]
    ).render()

    assert "record_id 110000350053" in rendered
    assert "dataset echo" in rendered


def test_no_facilities_is_stated_rather_than_left_blank() -> None:
    rendered = hexagon(facilities=[]).render()

    assert "Do not refer to any facility by name" in rendered


def test_a_truncated_facility_list_says_it_was_truncated() -> None:
    """Otherwise the model states a total it was never given."""
    many = [
        {"name": f"F{i}", "registry_id": str(i), "distance_km": 1.0, "program": "TRI"}
        for i in range(MAX_FACILITIES + 5)
    ]

    rendered = hexagon(facilities=many).render()

    assert f"({len(many)})" in rendered
    assert "Do not state a total you have not been given" in rendered


def test_demographics_are_marked_as_never_scored() -> None:
    """Section 14. They may be reported as facts about the population and may
    not be the basis of an inference about why anything was built."""
    rendered = hexagon(demographics={"population": 1840, "black_pct": 78.2}).render()

    assert "never an input to the score" in rendered
    assert "may not infer from them why anything was built" in rendered


def test_the_prompt_names_the_passages_as_the_only_authorities() -> None:
    prompt = build_prompt(hexagon(), "[42 U.S.C. § 7412] text", "Draft a letter.")

    assert "only legal authorities available to you" in prompt
    assert "[42 U.S.C. § 7412]" in prompt
    assert "Draft a letter." in prompt


def test_an_empty_retrieval_tells_the_model_to_refuse() -> None:
    """The dangerous case. With no passages and no instruction, a model writes
    the letter from memory, and every citation in it is unverifiable."""
    prompt = build_prompt(hexagon(), "", "Draft a letter.")

    assert "No passage in the corpus was close enough" in prompt
    assert "Refuse rather than citing a statute from memory" in prompt


def test_the_data_vintage_is_shown_when_there_is_one() -> None:
    prompt = build_prompt(hexagon(data_vintage={"TRI": "2024"}), "x", "Draft.")

    assert "TRI: 2024" in prompt
