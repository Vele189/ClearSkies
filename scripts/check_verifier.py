#!/usr/bin/env python3
"""Does the verifier actually catch a real section attached to a false claim?

`api/tests/test_verifier.py` stubs the judge, because what it tests is what the
verifier does with each answer. This asks the different question, and the more
important one: given the real corpus and the real judge, does the answer come
back right?

The set below is hand-written pairs of a section and a proposition, each labelled
with whether the section supports it. The hard half are the **traps**: real
sections paired with claims that are plausible, adjacent, and not what the
section says. That is the failure CS-305 exists for, because a fabricated
citation announces itself and a real section attached to a false claim is one a
reader will look up, find, and be reassured by.

    python scripts/check_verifier.py --database-url ... --out docs/validation/verifier.md

A script rather than a test, for the same reason as the red-team run: it costs
money and needs a key. Its output is committed.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "api"))

import asyncpg  # noqa: E402
from pydantic_ai.models.openai import OpenAIChatModel  # noqa: E402

from app.assistant.documents import StatuteCitation  # noqa: E402
from app.assistant.verifier import build_judge, check_statute  # noqa: E402


@dataclass(frozen=True)
class Case:
    section: str
    proposition: str
    supported: bool
    why: str


CASES: tuple[Case, ...] = (
    # ---- Propositions the section really does support -------------------
    Case(
        "42 U.S.C. § 7412(b)",
        "Congress established a list of hazardous air pollutants for purposes of this section.",
        True,
        "Close to a restatement of the opening words.",
    ),
    Case(
        "42 U.S.C. § 7412(a)",
        "A major source is one that emits or has the potential to emit 10 tons per year "
        "or more of any hazardous air pollutant.",
        True,
        "The threshold, paraphrased.",
    ),
    Case(
        "40 C.F.R. § 7.35",
        "A recipient of EPA assistance may not use criteria or methods of administering "
        "its program that have the effect of subjecting individuals to discrimination "
        "because of race, colour or national origin.",
        True,
        "The disparate-impact provision, paraphrased.",
    ),
    Case(
        "42 U.S.C. § 2000d",
        "No person shall be excluded from participation in a programme receiving federal "
        "financial assistance on the ground of race, colour or national origin.",
        True,
        "Section 601 itself.",
    ),
    # ---- Traps: the section is real and does not say this ---------------
    Case(
        "42 U.S.C. § 7412(b)",
        "Nucor Steel Louisiana emits hazardous air pollutants above the major source "
        "threshold.",
        False,
        "A statute does not name a facility. The section number is right and the "
        "claim is about a specific company.",
    ),
    Case(
        "42 U.S.C. § 7412(a)",
        "Facilities in St. James Parish have violated the hazardous air pollutant "
        "standards.",
        False,
        "A definitions subsection cannot establish that anybody violated anything.",
    ),
    Case(
        "42 U.S.C. § 7412(d)",
        "The EPA has failed to set emission standards for this source category.",
        False,
        "The section imposes the duty. Whether it was discharged is not in the text.",
    ),
    Case(
        "40 C.F.R. § 7.35",
        "The state agency discriminated against residents of this parish when it "
        "issued these permits.",
        False,
        "The regulation states the prohibition, not a finding against anyone.",
    ),
    Case(
        "42 U.S.C. § 2000d",
        "A resident may file a lawsuit to enforce the disparate-impact regulations "
        "issued under Title VI.",
        False,
        "The Sandoval failure, aimed at the statute rather than the case. Section 601 "
        "says nothing about a private right of action to enforce section 602 rules.",
    ),
    Case(
        "42 U.S.C. § 7661a",
        "The permit for this facility was issued without the public comment period the "
        "statute requires.",
        False,
        "The requirement is in the section. Whether it was met is not.",
    ),
    Case(
        "42 U.S.C. § 11023",
        "This facility reported 40,000 pounds of benzene released in 2024.",
        False,
        "A reporting requirement does not carry any facility's reported figure.",
    ),
    Case(
        "42 U.S.C. § 7410",
        "Louisiana's state implementation plan is inadequate.",
        False,
        "The adequacy requirements are in the section; the verdict on one state's plan "
        "is not.",
    ),
)


@dataclass
class Result:
    case: Case
    verdict: str
    detail: str

    @property
    def correct(self) -> bool:
        return self.case.supported == (self.verdict == "verified")


def render(results: list[Result], model: str, corpus: str) -> str:
    supported = [r for r in results if r.case.supported]
    traps = [r for r in results if not r.case.supported]
    caught = [r for r in traps if r.correct]
    kept = [r for r in supported if r.correct]

    lines = [
        "# Citation verifier check",
        "",
        f"- Date: {datetime.now(UTC).date().isoformat()}",
        f"- Judge model: `{model}`",
        f"- Corpus: `{corpus}`",
        f"- Cases: {len(results)}",
        f"- True propositions kept: {len(kept)} of {len(supported)}",
        f"- **False propositions caught: {len(caught)} of {len(traps)}**",
        "",
        "The traps are the point. Each pairs a real section with a claim that is "
        "plausible, adjacent, and not what the section says — the failure a reader "
        "would look up, find, and be reassured by.",
        "",
        "| Section | Should support | Verdict | Correct |",
        "|---|---|---|---|",
    ]
    for result in results:
        lines.append(
            f"| `{result.case.section}` | {'yes' if result.case.supported else 'no'} | "
            f"{result.verdict} | {'yes' if result.correct else '**no**'} |"
        )

    wrong = [r for r in results if not r.correct]
    if wrong:
        lines += ["", "## Disagreements", ""]
        for result in wrong:
            lines += [
                f"### `{result.case.section}`",
                "",
                f"**Proposition:** {result.case.proposition}",
                "",
                f"**Expected:** {'supported' if result.case.supported else 'not supported'}"
                f" — {result.case.why}",
                "",
                f"**Verdict:** {result.verdict}. {result.detail}",
                "",
            ]

    lines += ["", "## Every case", ""]
    for result in results:
        lines += [
            f"### `{result.case.section}` — {result.verdict}",
            "",
            f"**Proposition:** {result.case.proposition}",
            "",
            f"**Judge:** {result.detail}",
            "",
        ]
    return "\n".join(lines)


async def main_async(args: argparse.Namespace) -> int:
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set. This script calls a paid API.", file=sys.stderr)
        return 2

    from app.assistant.retrieval import active_version

    judge = build_judge(OpenAIChatModel(args.model))
    conn = await asyncpg.connect(args.database_url)
    try:
        corpus = await active_version(conn)
        if corpus is None:
            print("No sealed corpus version.", file=sys.stderr)
            return 2
        print(f"corpus {corpus}, judge {args.model}\n")

        results: list[Result] = []
        for case in CASES:
            check = await check_statute(
                conn,
                judge,
                StatuteCitation(
                    section=case.section,
                    document_id="unused-by-the-check",
                    proposition=case.proposition,
                ),
            )
            result = Result(case=case, verdict=check.verdict, detail=check.detail)
            results.append(result)
            mark = "ok  " if result.correct else "WRONG"
            print(f"  {mark} {case.section:<24} {check.verdict}")
    finally:
        await conn.close()

    report = render(results, args.model, corpus)
    if args.out:
        Path(args.out).write_text(report + "\n", encoding="utf-8")
        print(f"\nwrote {args.out}")
    else:
        print("\n" + report)

    traps = [r for r in results if not r.case.supported]
    caught = [r for r in traps if r.correct]
    print(f"\n{len(caught)} of {len(traps)} false propositions caught")
    wrong = [r for r in results if not r.correct]
    return 1 if wrong and args.require_clean else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check the verifier against real sections.")
    parser.add_argument(
        "--database-url",
        default=os.environ.get(
            "DATABASE_URL", "postgresql://clearskies:clearskies@localhost:5432/clearskies"
        ),
    )
    parser.add_argument("--model", default="gpt-4o")
    parser.add_argument("--out", default=None)
    parser.add_argument("--require-clean", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(main_async(parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
