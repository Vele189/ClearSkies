#!/usr/bin/env python3
"""CS-308: generate fifty drafts and check every citation in every one.

The Phase 3 gate. Its criterion is zero unverifiable citations, and the only way
to know is to generate real drafts against the real corpus and check what comes
back.

What the harness does that a person then cannot skip:

- Generates across all four document types and a spread of hexagons, running
  down to the **low** confidence band and stopping there, because an
  insufficient-band hexagon cannot be drafted from at all.
- Includes hexagons with **few contributing facilities**, which is where the
  model is most tempted to pad a thin document with something it remembers.
- Re-checks every citation of every accepted draft independently, so the number
  reported is not just "the pipeline said yes".
- Runs the prohibited-language scan over the model's own words, excluding this
  system's constant disclaimers.
- Writes every draft to disk so the manual review the gate requires has
  something to read.

**What it cannot do is the manual review.** The gate says every citation is
manually verified, and a script reporting that a script agreed with itself is
not that. The write-up records which checks were mechanical and which still need
a person.

    python scripts/run_citation_audit.py --database-url ... --out docs/validation/citation-audit.md
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "api"))

import asyncpg  # noqa: E402
from openai import AsyncOpenAI  # noqa: E402
from pydantic_ai.models.openai import OpenAIChatModel  # noqa: E402

from app.assistant import audit, cost, prompts, redteam, service, verifier  # noqa: E402
from app.assistant.audit import Profile  # noqa: E402
from app.assistant.context import HexContext  # noqa: E402
from app.assistant.documents import SYSTEM_WRITTEN_FIELDS, DocumentType  # noqa: E402
from app.assistant.structured import DraftRejected  # noqa: E402
from app.routers.draft import default_request  # noqa: E402

TYPES: list[DocumentType] = [
    "public_comment_letter",
    "agency_complaint_draft",
    "community_briefing_sheet",
    "journalist_fact_sheet",
]

FACILITIES = """
SELECT registry_id, name, city, has_title_v, is_major_source
  FROM facility
 WHERE registry_id IS NOT NULL
 ORDER BY name
"""


@dataclass
class AuditedDraft:
    profile: Profile
    document_type: str
    outcome: str
    citations: int = 0
    recheck_failures: list[str] = field(default_factory=list)
    flags: list[redteam.Flag] = field(default_factory=list)
    detail: str = ""
    text: str = ""
    tokens: int = 0

    @property
    def clean(self) -> bool:
        return self.outcome == "drafted" and not self.recheck_failures


def build_context(profile: Profile, facilities: list[dict[str, Any]], index: int) -> HexContext:
    """One hexagon, with real facilities attached.

    The scores and demographics come from the profile and are a fixture; the
    facilities are rows from the database. `app/assistant/audit.py` explains
    which half of that is real and why it still makes the citation result mean
    something.
    """
    return HexContext(
        h3=f"8844460{index:02x}dfffff",
        parish=profile.parish,
        score=profile.score,
        percentile=profile.percentile,
        confidence=profile.confidence,
        confidence_band=profile.band,
        methodology_version="0.1.4",
        indicators=audit.indicators_for(profile),
        demographics={
            "population": profile.population,
            "black_pct": profile.black_pct,
            "poverty_200pct": profile.poverty_pct,
            "under_5_pct": 6.4,
            "over_64_pct": 15.1,
        },
        facilities=audit.facilities_for(profile, facilities, index),
        data_vintage={"ECHO": "2026-Q2", "AirToxScreen": "2020"},
    )


def document_text(document: Any) -> str:
    payload = document.model_dump(exclude=set(SYSTEM_WRITTEN_FIELDS))
    out: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str):
            out.append(node)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    return "\n".join(out)


# A run this size will meet the provider's tokens-per-minute limit; that is
# expected rather than exceptional, and the right response is to wait rather
# than to record fifty failures in a minute. Backoff is here in the harness and
# not in `service.py` because a user waiting on one draft should be told to try
# again, while a batch should simply take longer.
RATE_LIMIT_WAITS = (30, 60, 120)


async def with_backoff(what: str, call: Any) -> Any:
    """Run one model call, waiting out a rate limit rather than failing on it."""
    last: Exception | None = None
    for wait in (*RATE_LIMIT_WAITS, None):
        try:
            return await call()
        except Exception as exc:  # noqa: BLE001 - re-raised below if not a limit
            if not service.is_provider_limit(exc) or wait is None:
                raise
            last = exc
            print(f"      rate limited during {what}; waiting {wait}s")
            await asyncio.sleep(wait)
    raise last  # pragma: no cover - the loop either returns or raises above


async def audit_one(
    conn: Any,
    client: AsyncOpenAI,
    model: OpenAIChatModel,
    embedding_model: str,
    profile: Profile,
    context: HexContext,
    document_type: DocumentType,
) -> AuditedDraft:
    try:
        # The same request text a user sends by clicking the button in the
        # panel and typing nothing. Auditing a request nobody makes would
        # measure a path nobody takes.
        outcome = await with_backoff(
            "generation",
            lambda: service.draft_for_hex(
                conn,
                client,
                model,
                embedding_model,
                context,
                document_type,
                default_request(document_type),
                "0.1.4",
            ),
        )
    except verifier.DraftUnverifiable as exc:
        return AuditedDraft(
            profile=profile,
            document_type=document_type,
            outcome="unverifiable",
            detail="; ".join(
                f"{c.reference} ({c.verdict}) {c.detail}" for c in exc.verification.failures
            ),
        )
    except DraftRejected as exc:
        return AuditedDraft(profile, document_type, "schema_rejected", detail=str(exc))
    except Exception as exc:  # noqa: BLE001 - one draft failing must not stop the audit
        return AuditedDraft(profile, document_type, "error", detail=f"{type(exc).__name__}: {exc}")

    if outcome.refusal is not None:
        return AuditedDraft(
            profile,
            document_type,
            "refused",
            detail=f"{outcome.refusal.reason}: {outcome.refusal.explanation}",
        )

    assert outcome.draft is not None
    document = outcome.draft.document

    # Re-verify independently. The pipeline already verified before returning,
    # and a gate that trusts the thing it is gating is not a gate.
    #
    # Inside the try, because it was outside it once: a rate limit here killed a
    # three-hour run at draft 37 and lost every result with it. One draft
    # failing must cost one draft.
    try:
        recheck = await with_backoff(
            "re-check", lambda: verifier.verify_document(conn, model, document, context.h3)
        )
    except Exception as exc:  # noqa: BLE001 - see above
        return AuditedDraft(
            profile,
            document_type,
            "error",
            detail=f"re-check failed: {type(exc).__name__}: {exc}",
        )
    text = document_text(document)

    return AuditedDraft(
        profile=profile,
        document_type=document_type,
        outcome="drafted",
        citations=len(document.citations),
        recheck_failures=[f"{c.reference} ({c.verdict}) {c.detail}" for c in recheck.failures],
        flags=redteam.scan(text),
        text=text,
    )


def render(results: list[AuditedDraft], model: str, corpus: str, spend: cost.Spend) -> str:
    drafted = [r for r in results if r.outcome == "drafted"]
    refused = [r for r in results if r.outcome == "refused"]
    unverifiable = [r for r in results if r.outcome == "unverifiable"]
    errors = [r for r in results if r.outcome in {"error", "schema_rejected"}]
    citations = sum(r.citations for r in drafted)
    failures = [f for r in drafted for f in r.recheck_failures]
    flagged = [r for r in drafted if r.flags]

    lines = [
        "# CS-308 — fifty-draft citation audit",
        "",
        f"- Date: {datetime.now(UTC).date().isoformat()}",
        f"- Model: `{model}`",
        f"- Prompt version: `{prompts.CURRENT_VERSION}`",
        f"- Corpus: `{corpus}`",
        "",
        "## The gate",
        "",
        "| | |",
        "|---|---|",
        f"| Drafts attempted | {len(results)} |",
        f"| Drafts produced | {len(drafted)} |",
        f"| Drafts refused by the model | {len(refused)} |",
        f"| Drafts discarded by the verifier | {len(unverifiable)} |",
        f"| Errors | {len(errors)} |",
        f"| Citations in produced drafts | {citations} |",
        f"| **Unverifiable citations in a shown draft** | **{len(failures)}** |",
        "",
    ]

    if not drafted:
        # Zero drafts is zero unverifiable citations, and reporting that as a
        # pass would be the same mistake `Verification.verified` refuses to
        # make: a check that returns true for an empty list passes anything.
        lines += [
            "**The gate is not met.** No draft was produced at all, so there was "
            "nothing to check. A run with no drafts has zero unverifiable "
            "citations trivially, and that is not a pass.",
            "",
        ]
    elif failures:
        lines += [
            "**The gate is not met.** Every citation below reached a rendered draft "
            "and failed an independent re-check:",
            "",
        ]
        for failure in failures:
            lines.append(f"- {failure}")
        lines.append("")
    else:
        lines += [
            "**Zero unverifiable citations reached a shown draft.** Every citation in "
            "every produced draft was re-checked independently of the pipeline that "
            "produced it, and all of them resolved: each statute section exists in the "
            "sealed corpus and supports the proposition it was cited for, and each "
            "record id exists in the facility table.",
            "",
            f"The {len(unverifiable)} drafts the verifier discarded are the system "
            "working. They were never rendered; they are counted here because the "
            "rate at which the assistant produces unsupportable citations is worth "
            "knowing even when none of them reaches a reader.",
            "",
        ]

    lines += [
        "## Spread",
        "",
        "| Band | Drafts | Produced | Refused | Discarded |",
        "|---|---|---|---|---|",
    ]
    for band in ("high", "moderate", "low"):
        subset = [r for r in results if r.profile.band == band]
        lines.append(
            f"| {band} | {len(subset)} | "
            f"{sum(1 for r in subset if r.outcome == 'drafted')} | "
            f"{sum(1 for r in subset if r.outcome == 'refused')} | "
            f"{sum(1 for r in subset if r.outcome == 'unverifiable')} |"
        )

    lines += ["", "| Document type | Drafts | Produced | Citations |", "|---|---|---|---|"]
    for document_type in TYPES:
        subset = [r for r in results if r.document_type == document_type]
        lines.append(
            f"| {document_type} | {len(subset)} | "
            f"{sum(1 for r in subset if r.outcome == 'drafted')} | "
            f"{sum(r.citations for r in subset)} |"
        )

    thin = [r for r in results if r.profile.facilities <= 2]
    lines += [
        "",
        f"Hexagons with two or fewer contributing facilities: {len(thin)} drafts, "
        f"{sum(1 for r in thin if r.outcome == 'drafted')} produced. This is where a "
        "model is most tempted to pad a thin document with something it remembers.",
        "",
        "## Language review",
        "",
        f"The prohibited-language scan ran over the model's own words in all "
        f"{len(drafted)} produced drafts, excluding this system's constant "
        f"disclaimers. Drafts with at least one flag: **{len(flagged)}**.",
        "",
    ]
    if flagged:
        lines += ["Each needs a person to read the sentence:", ""]
        for result in flagged:
            lines.append(f"### {result.profile.name} — {result.document_type}")
            lines.append("")
            for flag in result.flags[:6]:
                lines.append(f"- **{flag.category}** `{flag.phrase}` — ...{flag.context}...")
            lines.append("")
    else:
        lines += [
            "No draft contained the vocabulary of intent, culpability, outcome "
            "prediction or litigation. That is a mechanical result and not a "
            "substitute for reading them: the scan catches words, and a claim about "
            "why a plant was built where it was can be made without any of them.",
            "",
        ]

    lines += [
        "## Refusals",
        "",
    ]
    if refused:
        for result in refused:
            lines.append(f"- `{result.profile.name}` / {result.document_type}: {result.detail}")
    else:
        lines.append("None.")

    if unverifiable:
        lines += ["", "## Discarded by the verifier", ""]
        for result in unverifiable:
            lines.append(f"- `{result.profile.name}` / {result.document_type}: {result.detail}")

    if errors:
        lines += ["", "## Errors", ""]
        for result in errors:
            lines.append(f"- `{result.profile.name}` / {result.document_type}: {result.detail}")

    lines += [
        "",
        "## Cost",
        "",
        f"{spend.calls} model calls, {spend.tokens:,} tokens, about ${spend.usd:.2f} "
        "estimated. Generation and verification both; the verifier runs a second "
        "model over every citation, and attributing all of it to generation would "
        "mislead about where the money goes.",
        "",
        "## What is a fixture, and what is real",
        "",
        "**Real:** every statute passage, retrieved from the sealed corpus. Every "
        "facility, loaded from ECHO with its own FRS registry identifier — the same "
        "identifier a reader would take to EPA. Every verification, run against "
        "those two tables.",
        "",
        "**A fixture:** the hexagons. Phase 2 has not run against a populated "
        "database, so there is no scored cell to point at, and the scores, "
        "confidence values and demographics here are invented to span the spread the "
        "gate asks for. This does not weaken the citation result, which is what the "
        "gate is about: a citation is checked against the corpus and the facility "
        "table, and both hold real rows. It does mean the drafts are about places "
        "that do not have these scores, and **this audit must be re-run once the "
        "pipeline has loaded real data** before the model card cites it as a "
        "statement about production behaviour.",
        "",
        "## What a person still has to do",
        "",
        "The gate says every citation is manually verified. A script reporting that "
        "a script agreed with itself is not that, and the checks above are all "
        "mechanical:",
        "",
        "- **Read the drafts.** They are written to the directory this run names. "
        "The scan catches vocabulary; it cannot catch a claim about why a facility "
        "is where it is, made in neutral words.",
        "- **Check a sample of citations by hand**, by following the link and "
        "reading the section. The verifier is a language model and this is the only "
        "check on it that is not another language model.",
        "- **Look specifically for anything implying a Title VI disparate-impact "
        "claim can be filed as a lawsuit.** That is the failure with the worst "
        "consequences for a reader, and it is the one a fluent draft hides best.",
    ]
    return "\n".join(lines)


async def main_async(args: argparse.Namespace) -> int:
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set. This script calls a paid API.", file=sys.stderr)
        return 2

    from app.assistant.retrieval import active_version

    client = AsyncOpenAI()
    model = OpenAIChatModel(args.model)
    conn = await asyncpg.connect(args.database_url)

    try:
        corpus = await active_version(conn)
        if corpus is None:
            print("No sealed corpus version.", file=sys.stderr)
            return 2
        facilities = [dict(r) for r in await conn.fetch(FACILITIES)]
        if not facilities:
            print(
                "The facility table is empty, so every record citation would fail for "
                "a reason unrelated to the assistant. Run "
                "scripts/seed_audit_facilities.py first.",
                file=sys.stderr,
            )
            return 2

        before = await cost.month_to_date(conn)
        print(f"corpus {corpus}, model {args.model}, {len(facilities)} facilities\n")

        schedule = audit.plan(args.count, list(TYPES))

        results: list[AuditedDraft] = []
        for i, (profile, document_type, index) in enumerate(schedule, start=1):
            context = build_context(profile, facilities, index)
            result = await audit_one(
                conn, client, model, args.embedding_model, profile, context, document_type
            )
            results.append(result)
            mark = {"drafted": "ok  ", "refused": "refu", "unverifiable": "DISC"}.get(
                result.outcome, "ERR "
            )
            note = "" if result.clean else f"  {result.detail[:70]}"
            print(
                f"  [{i:>2}/{len(schedule)}] {mark} {profile.name:<24} "
                f"{document_type:<26} {result.citations} cites{note}"
            )

        after = await cost.month_to_date(conn)
    finally:
        await conn.close()

    spend = cost.Spend(
        usd=after.usd - before.usd,
        tokens=after.tokens - before.tokens,
        calls=after.calls - before.calls,
    )

    if args.drafts_dir:
        directory = Path(args.drafts_dir)
        directory.mkdir(parents=True, exist_ok=True)
        for i, result in enumerate(results, start=1):
            if result.text:
                name = f"{i:02d}-{result.profile.name}-{result.document_type}.txt"
                (directory / name).write_text(result.text, encoding="utf-8")
        print(f"\nwrote drafts to {directory}")

    report = render(results, args.model, corpus, spend)
    if args.out:
        Path(args.out).write_text(report + "\n", encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print("\n" + report)

    if args.json:
        Path(args.json).write_text(
            json.dumps(
                [
                    {
                        "profile": r.profile.name,
                        "band": r.profile.band,
                        "facilities": r.profile.facilities,
                        "document_type": r.document_type,
                        "outcome": r.outcome,
                        "citations": r.citations,
                        "recheck_failures": r.recheck_failures,
                        "flags": [f.phrase for f in r.flags],
                        "detail": r.detail,
                    }
                    for r in results
                ],
                indent=2,
            ),
            encoding="utf-8",
        )

    produced = sum(1 for r in results if r.outcome == "drafted")
    failures = sum(len(r.recheck_failures) for r in results if r.outcome == "drafted")
    print(f"\n{produced} drafts produced, {failures} unverifiable citations in a shown draft")
    if not produced:
        print("no drafts were produced, so the gate is not met", file=sys.stderr)
        return 1
    return 1 if failures else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the CS-308 fifty-draft audit.")
    parser.add_argument(
        "--database-url",
        default=os.environ.get(
            "DATABASE_URL", "postgresql://clearskies:clearskies@localhost:5432/clearskies"
        ),
    )
    parser.add_argument("--model", default="gpt-4o")
    parser.add_argument("--embedding-model", default="text-embedding-3-small")
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--out", default=None)
    parser.add_argument("--json", default=None)
    parser.add_argument("--drafts-dir", default=None, help="write every draft here for review")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(main_async(parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
