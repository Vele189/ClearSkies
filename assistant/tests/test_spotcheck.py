"""The spot-check set, and the arithmetic over it.

The question set itself gets a few tests because it is the thing most likely to
rot: an expectation written against a section that is no longer in the corpus
would report a retrieval failure for what is really a manifest change.
"""

from __future__ import annotations

from typing import Any

import pytest

from corpus.questions import QUESTIONS
from corpus.spotcheck import Hit, Report, render, run


class FakeEmbeddings:
    async def create(self, model: str, input: list[str], dimensions: int) -> Any:
        class Item:
            embedding = [0.0] * dimensions

        return type("Response", (), {"data": [Item()]})()


class FakeClient:
    embeddings = FakeEmbeddings()


class FakeConn:
    def __init__(self, labels: list[str]) -> None:
        self.labels = labels

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        return [
            {"section_label": label, "document_id": "d", "distance": 0.1 * i}
            for i, label in enumerate(self.labels, start=1)
        ]


# ---- The question set ---------------------------------------------------


def test_the_set_is_large_enough_to_notice_a_regression() -> None:
    assert len(QUESTIONS) >= 20


def test_every_question_expects_a_section_and_says_why() -> None:
    for question in QUESTIONS:
        assert question.text.endswith("?"), question.text
        assert question.expect
        assert question.why, question.text


def test_the_set_covers_both_cases_in_appendix_b3() -> None:
    """The Sandoval question is the single most important one in the set: it is
    the difference between a draft that tells somebody to file an administrative
    complaint and one that tells them to sue."""
    expectations = {q.expect for q in QUESTIONS}

    assert "532 U.S. 275 (2001)" in expectations
    assert "452 So. 2d 1152 (La. 1984)" in expectations


def test_the_set_does_not_ask_for_authorities_the_corpus_lacks() -> None:
    """The four Louisiana authorities are not ingested. Asking for them would
    report a retrieval failure for what is an ingestion gap, and the number
    would stop meaning anything."""
    for question in QUESTIONS:
        assert not question.expect.startswith("La. R.S."), question.text
        assert not question.expect.startswith("LAC "), question.text


def test_no_question_is_asked_twice() -> None:
    assert len({q.text for q in QUESTIONS}) == len(QUESTIONS)


# ---- The measurement ----------------------------------------------------


async def test_an_expected_section_is_found_at_its_rank() -> None:
    conn = FakeConn(["40 C.F.R. § 7.10", "42 U.S.C. § 7412(b)"])

    report = await run(conn, FakeClient(), "m", questions=QUESTIONS[:1], k=8)

    assert report.hits[0].rank == 2
    assert report.recall == 1.0


async def test_a_subdivision_satisfies_a_section_expectation() -> None:
    """A question about § 7412(b) is answered by any chunk of it. Demanding an
    exact label would measure the chunker rather than retrieval."""
    conn = FakeConn(["42 U.S.C. § 7412(b)(1)"])

    report = await run(conn, FakeClient(), "m", questions=QUESTIONS[:1], k=8)

    assert report.hits[0].rank == 1


async def test_a_miss_is_recorded_with_what_came_back_instead() -> None:
    """The nearest wrong answer is what tells you whether retrieval is broken
    or the question is badly worded."""
    conn = FakeConn(["33 U.S.C. § 1251"])

    report = await run(conn, FakeClient(), "m", questions=QUESTIONS[:1], k=8)

    assert not report.hits[0].found
    assert report.hits[0].closest == "33 U.S.C. § 1251"
    assert report.misses == report.hits


def test_mean_rank_ignores_the_misses() -> None:
    """Averaging a miss as rank k would make recall and rank move together and
    hide which of the two actually changed."""
    report = Report(
        hits=[
            Hit(QUESTIONS[0], rank=1, closest="a", distance=0.1),
            Hit(QUESTIONS[1], rank=3, closest="b", distance=0.2),
            Hit(QUESTIONS[2], rank=None, closest="c", distance=0.9),
        ],
        k=8,
    )

    assert report.mean_rank == 2.0
    assert report.recall == pytest.approx(2 / 3)


def test_the_report_names_every_miss() -> None:
    report = Report(
        hits=[Hit(QUESTIONS[0], rank=None, closest="33 U.S.C. § 1251", distance=0.5)],
        k=8,
    )

    rendered = render(report)

    assert "MISS" in rendered
    assert "33 U.S.C. § 1251" in rendered
    assert "0/1" in rendered
