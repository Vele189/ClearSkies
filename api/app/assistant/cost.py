"""What a call cost, estimated, and what has been spent this month.

Estimated is the operative word. The prices below are a table in an application
that the provider can change without telling it, so every number here is
indicative and the provider's invoice is the truth.

That is precisely why **the hard cap belongs with the provider and not here**.
A limit the application enforces is a limit that stops working when the
application has a bug, and the bug that matters is the one that makes it call
the API in a loop. `docs/drafting.md` records the cap as an operator step,
because it is a dashboard action and cannot be set from a repository.

What this module is for is the softer job: knowing what has been spent, refusing
to start work that would obviously blow a budget, and making the bill legible
before it arrives rather than after.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Price:
    """US dollars per million tokens."""

    input_usd: float
    output_usd: float


# Indicative, as of 2026-09. A model absent from this table costs nothing as far
# as this code knows, which is the safe direction for an estimate that gates
# nothing: an unknown model produces a visibly zero cost rather than a
# confidently wrong one.
PRICES: dict[str, Price] = {
    "gpt-4o": Price(2.50, 10.00),
    "gpt-4o-mini": Price(0.15, 0.60),
    "gpt-4.1": Price(2.00, 8.00),
    "gpt-4.1-mini": Price(0.40, 1.60),
    "text-embedding-3-small": Price(0.02, 0.0),
    "text-embedding-3-large": Price(0.13, 0.0),
}


def estimate_usd(model: str, request_tokens: int, response_tokens: int) -> float:
    price = PRICES.get(model.split(":")[-1])
    if price is None:
        log.info("no price recorded for model %s; cost logged as zero", model)
        return 0.0
    return (
        request_tokens / 1_000_000 * price.input_usd
        + response_tokens / 1_000_000 * price.output_usd
    )


RECORD = """
INSERT INTO llm_usage (
    purpose, model, h3, document_type,
    request_tokens, response_tokens, usd, outcome, detail
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
"""

MONTH_TO_DATE = """
SELECT coalesce(sum(usd), 0)::float8 AS usd,
       coalesce(sum(request_tokens + response_tokens), 0)::bigint AS tokens,
       count(*) AS calls
  FROM llm_usage
 WHERE called_at >= $1
"""


async def record(
    conn: Any,
    purpose: str,
    model: str,
    request_tokens: int,
    response_tokens: int,
    outcome: str,
    h3: str | None = None,
    document_type: str | None = None,
    detail: str = "",
) -> float:
    """Log one call and return what it is estimated to have cost.

    Called for every attempt, including refusals, verifier rejections and
    provider errors. Cost is incurred by attempts and not by successes, and a
    usage table that recorded only successes would understate the bill by
    exactly the amount worth worrying about.
    """
    usd = estimate_usd(model, request_tokens, response_tokens)
    await conn.execute(
        RECORD,
        purpose,
        model,
        h3,
        document_type,
        request_tokens,
        response_tokens,
        usd,
        outcome,
        detail,
    )
    log.info(
        "llm usage",
        extra={
            "purpose": purpose,
            "model": model,
            "request_tokens": request_tokens,
            "response_tokens": response_tokens,
            "usd": round(usd, 6),
            "outcome": outcome,
            "h3": h3,
        },
    )
    return usd


@dataclass(frozen=True)
class Spend:
    usd: float
    tokens: int
    calls: int


def month_start(now: datetime | None = None) -> datetime:
    moment = now or datetime.now(UTC)
    return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def month_to_date(conn: Any, now: datetime | None = None) -> Spend:
    row = await conn.fetchrow(MONTH_TO_DATE, month_start(now))
    return Spend(usd=float(row["usd"]), tokens=int(row["tokens"]), calls=int(row["calls"]))
