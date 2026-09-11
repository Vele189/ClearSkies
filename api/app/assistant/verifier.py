"""Every citation, checked against the database, before anything is rendered.

The component the whole phase is built around. A draft that survives this is one
where every statute section named exists in the corpus it was written against,
every record ID exists in the loaded dataset, and every claim is one the cited
passage actually makes.

**A draft with any unverifiable citation is rejected.** Not shown with a
warning, not shown with the bad citation removed, not shown at all. That is a
harder rule than it first looks, and it is the right one: a warning on a
document is read once and then forgotten by whoever forwards it, and a document
with a citation quietly deleted is a document whose remaining claims now rest on
nothing, with no sign that anything was taken out. The only safe failure is no
document.

## Existence is the easy half

A section label is looked up in the sealed corpus, exactly as the model wrote
it. A record id is looked up in `facility`. Both are string comparisons and both
catch the obvious failure, which is a citation to something that does not exist.

## Support is the half that matters

Appendix B.4 rule 3: the verifier checks that the quoted or paraphrased
proposition actually appears in the retrieved chunk. Existence alone is not
sufficient, and the reason is the failure mode this file exists for. A
fabricated citation announces itself — the section is not there, the check
fails, done. A *real* section attached to a claim it does not support is a
citation a reader can look up, will find, and will read as confirming something
it does not say. It is more persuasive than a true citation, because the effort
of checking it makes the reader more confident afterwards.

Checking a paraphrase is not a string operation, so this asks a model: does this
passage state or directly establish this proposition? That is a narrow question
with a narrow answer, asked of a passage the judge is told is the only evidence,
and it is a different call from the one that wrote the draft.

Three verdicts, and the third is the important one. `supported` passes.
`not_supported` fails. `unclear` **also fails**, because a verifier that resolves
its own uncertainty in favour of publishing is not a verifier. A false rejection
costs one draft that somebody can ask for again. A false acceptance ships a
citation nobody will check again, because it has already been checked.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent
from pydantic_ai.models import Model

from app.assistant.documents import (
    Citation,
    DraftDocument,
    RecordCitation,
    StatuteCitation,
)

log = logging.getLogger(__name__)

# Which datasets a record citation may name, and how to find a row in each.
#
# Deliberately short. These are the sources that have a stable public identifier
# a reader can take to EPA and look up. A modelled AirToxScreen value or an ACS
# estimate is a number for a tract or a hexagon, not a record with an ID, so a
# citation naming one is rejected rather than waved through: there would be
# nothing for the reader to check.
DATASET_LOOKUPS: dict[str, str] = {
    "echo": """
        SELECT facility_id, name FROM facility
         WHERE facility_id = $1 OR registry_id = $1
         LIMIT 1
    """,
    "frs": """
        SELECT facility_id, name FROM facility
         WHERE facility_id = $1 OR registry_id = $1
         LIMIT 1
    """,
    "tri": """
        SELECT facility_id, name FROM facility
         WHERE tri_facility_id = $1 OR facility_id = $1
         LIMIT 1
    """,
}

# A citation is satisfied by the label itself **or by any subdivision of it**.
#
# Matching the label exactly looks obviously right and is wrong, because a
# citation names a unit and the corpus stores chunks. A section whose every
# chunk carries a subdivision label has no chunk labelled with the bare section:
# the corpus holds `42 U.S.C. § 7410(a)` and friends, and nothing labelled
# `42 U.S.C. § 7410`. An exact match therefore rejects a correct citation to the
# section as "not in the corpus", which is the worst kind of false rejection —
# the user is told their statute does not exist.
#
# The boundary matters. `§ 7412(b)` must match `§ 7412(b)` and `§ 7412(b)(1)`,
# and must NOT match `§ 7412(a)`. Requiring the next character to be an opening
# parenthesis gives exactly that, and stops `§ 741` matching `§ 7412`.
SECTION_LOOKUP = """
SELECT section_label, document_id, text, may_reason_from
  FROM statute_corpus_active
 WHERE section_label = $1
    OR section_label LIKE $1 || '(%'
 ORDER BY section_label, ordinal
"""

# Used only to explain a near miss. A citation to a section that does not exist
# is already rejected; this says whether it was close to one that does, which is
# the difference between "the model invented a statute" and "the model dropped a
# subdivision", and those are different problems.
NEAR_MISS = """
SELECT DISTINCT section_label
  FROM statute_corpus_active
 WHERE section_label LIKE $1 || '%' OR $1 LIKE section_label || '%'
 LIMIT 5
"""

Verdict = Literal["verified", "not_in_corpus", "not_in_dataset", "unsupported", "unclear"]


class Judgement(BaseModel):
    """One answer to one narrow question about one passage."""

    model_config = ConfigDict(extra="forbid")

    verdict: Literal["supported", "not_supported", "unclear"] = Field(
        description=(
            "supported: the passage states or directly establishes the proposition. "
            "not_supported: it does not. "
            "unclear: you cannot tell from this passage alone."
        )
    )
    reason: str = Field(
        min_length=1,
        description="One sentence. Quote the words that decide it where you can.",
    )


JUDGE_INSTRUCTIONS = """
You check whether one passage supports one proposition. Nothing else.

You are given a passage of statute, regulation or case law, and a single
proposition that a draft document claims the passage supports. Answer whether it
does.

Rules:

- The passage is the only evidence. Your own knowledge of the law is not
  evidence, and a proposition that is true but not in this passage is
  NOT SUPPORTED.
- "Supported" means the passage states the proposition, or the proposition is a
  direct and faithful restatement of what the passage says. A paraphrase is
  fine. An inference is not: if getting from the passage to the proposition
  needs a step the passage does not take, it is not supported.
- Watch for a proposition that is *about* the right subject but claims more than
  the passage does. A passage requiring an agency to publish a standard does not
  support a claim that any particular facility has violated one. A passage
  defining a major source does not support a claim that a named facility is one.
  These are the failures that matter, because the section number is right.
- A proposition that names a specific facility, person, number or date is
  supported only if the passage carries it. Statutes do not name facilities.
- If you cannot tell from this passage alone, answer "unclear". Do not guess in
  either direction. "Unclear" is treated as a failure downstream, which is the
  intended behaviour.

Be strict. A citation you wave through will not be checked again by anybody.
""".strip()


@dataclass
class CitationCheck:
    """One citation, and what happened to it."""

    citation: Citation
    verdict: Verdict
    detail: str = ""
    near_misses: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.verdict == "verified"

    @property
    def reference(self) -> str:
        if isinstance(self.citation, StatuteCitation):
            return self.citation.section
        return self.citation.record_id

    @property
    def kind(self) -> str:
        return self.citation.kind


@dataclass
class Verification:
    """The verdict on a whole draft."""

    checks: list[CitationCheck] = field(default_factory=list)

    @property
    def failures(self) -> list[CitationCheck]:
        return [c for c in self.checks if not c.ok]

    @property
    def verified(self) -> bool:
        """True only if every citation passed, and there was at least one.

        A draft with no citations cannot reach here — the schema requires one —
        but a verifier that returned True for an empty list would be a verifier
        that passed anything the schema ever stopped requiring.
        """
        return bool(self.checks) and not self.failures


class DraftUnverifiable(RuntimeError):
    """A draft contained a citation that could not be verified.

    Carries every failure rather than the first, because the audit wants to know
    how a draft failed and "the first thing we noticed" is a worse answer than
    "these four things".
    """

    def __init__(self, verification: Verification) -> None:
        self.verification = verification
        summary = ", ".join(f"{c.reference} ({c.verdict})" for c in verification.failures[:5])
        super().__init__(f"{len(verification.failures)} unverifiable citation(s): {summary}")


def build_judge(model: Model | str) -> Agent[None, Judgement]:
    """An agent that answers one question with one of three words."""
    return Agent(model, output_type=Judgement, instructions=JUDGE_INSTRUCTIONS, retries=2)


async def check_statute(
    conn: Any,
    judge: Agent[None, Judgement],
    citation: StatuteCitation,
) -> CitationCheck:
    """Does this section exist in the corpus, and does it say what is claimed?"""
    rows = await conn.fetch(SECTION_LOOKUP, citation.section)
    if not rows:
        near = await conn.fetch(NEAR_MISS, citation.section)
        misses = [str(r["section_label"]) for r in near]
        return CitationCheck(
            citation=citation,
            verdict="not_in_corpus",
            detail=(
                f"{citation.section!r} is not a section label in the sealed corpus"
                + (f"; nearest are {', '.join(misses)}" if misses else "")
            ),
            near_misses=misses,
        )

    # Every chunk under this label, joined. A section split across two chunks
    # supports a proposition that spans them, and judging chunk by chunk would
    # reject it for being in neither half.
    passage = "\n\n".join(str(row["text"]) for row in rows)

    result = await judge.run(
        f"PASSAGE ({citation.section}):\n{passage}\n\nPROPOSITION:\n{citation.proposition}"
    )
    judgement = result.output
    if judgement.verdict == "supported":
        return CitationCheck(citation=citation, verdict="verified", detail=judgement.reason)
    return CitationCheck(
        citation=citation,
        verdict="unsupported" if judgement.verdict == "not_supported" else "unclear",
        detail=judgement.reason,
    )


async def check_record(conn: Any, citation: RecordCitation) -> CitationCheck:
    """Does this record exist in the loaded dataset?

    No support check. A record citation asserts that a row exists and says what
    the row says; there is no paraphrase to verify, because the model was given
    the row's fields and copied one. The failure available here is a made-up or
    mistyped identifier, and existence catches it.
    """
    dataset = citation.dataset.strip().lower()
    query = DATASET_LOOKUPS.get(dataset)
    if query is None:
        return CitationCheck(
            citation=citation,
            verdict="not_in_dataset",
            detail=(
                f"{citation.dataset!r} is not a dataset a record can be cited from; "
                f"the ones with public identifiers are {', '.join(sorted(DATASET_LOOKUPS))}"
            ),
        )

    row = await conn.fetchrow(query, citation.record_id)
    if row is None:
        return CitationCheck(
            citation=citation,
            verdict="not_in_dataset",
            detail=f"no record {citation.record_id!r} in {dataset}",
        )
    return CitationCheck(citation=citation, verdict="verified", detail=f"matched {row['name']}")


async def verify_document(
    conn: Any,
    model: Model | str,
    document: DraftDocument,
) -> Verification:
    """Check every citation in a draft. Returns the verdict; raises nothing."""
    judge = build_judge(model)
    verification = Verification()

    for citation in document.citations:
        if isinstance(citation, StatuteCitation):
            check = await check_statute(conn, judge, citation)
        else:
            check = await check_record(conn, citation)
        verification.checks.append(check)
        if not check.ok:
            log.warning(
                "citation failed verification: %s %s (%s) %s",
                check.kind,
                check.reference,
                check.verdict,
                check.detail,
            )

    return verification


LOG_REJECTION = """
INSERT INTO draft_rejection (
    h3, document_type, corpus_version, prompt_version, model,
    reason, citation_kind, citation_ref, proposition, detail
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
"""


async def log_rejections(
    conn: Any,
    verification: Verification,
    h3: str,
    document_type: str,
    corpus_version: str,
    prompt_version: str,
    model: str,
) -> int:
    """Record every failed citation, for the audit.

    One row per failure. A draft rejected for four bad citations is four facts
    about how the assistant fails, and collapsing them into one loses three.
    """
    rows = [
        (
            h3,
            document_type,
            corpus_version,
            prompt_version,
            model,
            check.verdict,
            check.kind,
            check.reference,
            getattr(check.citation, "proposition", None),
            check.detail,
        )
        for check in verification.failures
    ]
    if rows:
        await conn.executemany(LOG_REJECTION, rows)
    return len(rows)
