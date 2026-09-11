"""Hand-written questions, and the section each one should reach.

The spot-check set. Every pair was written by reading the statute and asking
what somebody drafting a comment or a complaint would actually type, then
recording which section answers it. None was produced by running retrieval and
writing down what came back, which would measure nothing.

Expectations are section *prefixes*, not exact labels. A question about the
hazardous air pollutant list is answered by any chunk of 42 U.S.C. § 7412(b),
and demanding a particular subdivision would be measuring the chunker rather
than retrieval. A prefix that stops at the section number accepts any
subdivision of it.

The four Louisiana authorities of Appendix B.2 are deliberately absent. They
are not in the corpus (docs/corpus.md section 4), and a spot-check set that
asked for them would report a retrieval failure for what is an ingestion gap.
When they land, the questions for them belong here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Question:
    """One question, and the section that should come back for it."""

    text: str
    expect: str
    why: str = ""


QUESTIONS: tuple[Question, ...] = (
    Question(
        "Which pollutants did Congress list as hazardous air pollutants?",
        "42 U.S.C. § 7412(b)",
        "The initial list itself, the most cited provision in an air toxics comment.",
    ),
    Question(
        "What makes a facility a major source of hazardous air pollutants?",
        "42 U.S.C. § 7412(a)",
        "The ten and twenty-five ton thresholds are in the definitions subsection.",
    ),
    Question(
        "What emission standard must the EPA set for a listed source category?",
        "42 U.S.C. § 7412(d)",
        "Maximum achievable control technology.",
    ),
    Question(
        "Does the public get to comment on a Title V operating permit application?",
        "42 U.S.C. § 7661a",
        "The public participation requirement a comment letter is exercising.",
    ),
    Question(
        "How long is a Title V operating permit valid?",
        "42 U.S.C. § 7661a",
        "The five year term and the permit programme requirements sit together.",
    ),
    Question(
        "What must a state implementation plan contain to be approved?",
        "42 U.S.C. § 7410",
        "The adequacy requirements a SIP challenge turns on.",
    ),
    Question(
        "What is required before building a major emitting facility in a clean air area?",
        "42 U.S.C. § 7475",
        "Prevention of significant deterioration preconstruction requirements.",
    ),
    Question(
        "What are the purposes of the prevention of significant deterioration programme?",
        "42 U.S.C. § 7470",
        "The declaration of purpose.",
    ),
    Question(
        "Which facilities have to report their toxic chemical releases each year?",
        "42 U.S.C. § 11023",
        "The EPCRA reporting requirement that produces the TRI data this tool uses.",
    ),
    Question(
        "Who must be told about an accidental release of a hazardous substance?",
        "42 U.S.C. § 11004",
        "Emergency notification.",
    ),
    Question(
        "Is a permit needed to discharge a pollutant into navigable waters?",
        "33 U.S.C. § 1342",
        "The NPDES permit programme.",
    ),
    Question(
        "What is the national goal for eliminating discharges into navigable waters?",
        "33 U.S.C. § 1251",
        "The declaration of goals and policy.",
    ),
    Question(
        "What standards apply to owners of hazardous waste treatment and storage facilities?",
        "42 U.S.C. § 6924",
        "RCRA standards for TSD facilities.",
    ),
    Question(
        "May a programme receiving federal money discriminate on the basis of race?",
        "42 U.S.C. § 2000d",
        "Section 601 itself.",
    ),
    Question(
        "What can a federal agency do if a recipient of its funds discriminates?",
        "42 U.S.C. § 2000d-1",
        "Section 602, the rulemaking and fund-termination authority.",
    ),
    Question(
        "How do I file a discrimination complaint against a recipient of EPA funds?",
        "40 C.F.R. § 7.120",
        "The complaint procedure, and the right answer to the question a resident asks.",
    ),
    Question(
        "What practices are specifically prohibited for recipients of EPA assistance?",
        "40 C.F.R. § 7.35",
        "Specific prohibitions, including the disparate-impact provision.",
    ),
    Question(
        "How long does someone have to file a Title VI complaint with the EPA?",
        "40 C.F.R. § 7.120",
        "The 180 day deadline, which a draft that gets wrong wastes somebody's claim.",
    ),
    Question(
        "Can a private individual sue to enforce Title VI disparate-impact regulations?",
        "532 U.S. 275 (2001)",
        "Sandoval. The single most important question for getting the posture right.",
    ),
    Question(
        "What duty does a Louisiana agency have to protect the environment when it permits?",
        "452 So. 2d 1152 (La. 1984)",
        "Save Ourselves and the public trust duty.",
    ),
)
