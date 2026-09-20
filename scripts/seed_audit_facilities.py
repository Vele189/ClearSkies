#!/usr/bin/env python3
"""Load real Louisiana facilities into a database, for the CS-308 audit.

The audit checks whether the assistant's citations are verifiable. Half of them
are record citations, and a record citation can only be verified against a
facility table with rows in it. Phase 1's nightly ETL has not run on any
deployment, so the table is empty and every record citation would fail
verification for a reason that has nothing to do with the assistant.

So this loads a set of **real** facilities, from ECHO, with their real FRS
registry identifiers — the same identifiers a reader would take to EPA and look
up. Nothing here is invented. What it is not is the Phase 1 adapter: no
snapshotting, no provenance, no quality gate, no geocoding verdicts, and no
coordinates. It exists so the audit has real identifiers to verify against, and
`docs/validation/citation-audit.md` says so rather than presenting the result as
a full pipeline run.

    python scripts/seed_audit_facilities.py --database-url ... --limit 60
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "api"))

import asyncpg  # noqa: E402
import httpx  # noqa: E402

ECHO = "https://echodata.epa.gov/echo/air_rest_services"

# A snapshot row the facilities can point at. `facility.snapshot_id` is NOT
# NULL and references source_snapshot, which is correct for a real pull and
# inconvenient for a seed, so the seed creates one honestly labelled row rather
# than making the column nullable.
SNAPSHOT = """
INSERT INTO source_snapshot (
    source, url, retrieved_at, checksum, record_count, vintage, vintage_end, notes
) VALUES ('echo', $1, now(), $2, $3, 'CS-308 audit seed', current_date, $4)
ON CONFLICT (source, checksum) DO UPDATE SET retrieved_at = now()
RETURNING snapshot_id
"""

# ECHO publishes coordinates, so they are loaded, and they are loaded as
# 'unverified' because they are self-reported: section 6 of the methodology is
# about exactly that, and some of them land in the wrong parish. A facility
# without a coordinate is stored as 'missing'/'absent', which is the pairing
# migration 0014's constraint requires and the only honest one.
FACILITY = """
INSERT INTO facility (
    facility_id, registry_id, name, street, city, state, zip5,
    naics_code, coordinate_status, geocode_quality, geom,
    reported_latitude, reported_longitude,
    is_major_source, has_title_v, echo_url, snapshot_id
) VALUES (
    $1, $2, $3, $4, $5, 'LA', $6, $7,
    CASE WHEN $8::numeric IS NULL THEN 'missing' ELSE 'ok' END,
    CASE WHEN $8::numeric IS NULL THEN 'absent' ELSE 'unverified' END,
    CASE WHEN $8::numeric IS NULL THEN NULL
         ELSE ST_SetSRID(ST_MakePoint($9::numeric, $8::numeric), 4326) END,
    $8, $9, $10, $11, $12, $13
)
ON CONFLICT (facility_id) DO NOTHING
"""


async def fetch_facilities(limit: int) -> list[dict[str, Any]]:
    """Major air sources in Louisiana, from ECHO's REST service."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        start = await client.get(
            f"{ECHO}.get_facilities",
            params={"output": "JSON", "p_st": "LA", "p_maj": "Y", "responseset": "1"},
        )
        start.raise_for_status()
        qid = start.json()["Results"]["QueryID"]

        # One request for the whole set. ECHO rate-limits, and a paging loop
        # that asks for more than a page holds keeps asking and earns a 429;
        # the service will return the requested count in one response.
        response = await client.get(
            f"{ECHO}.get_qid",
            params={
                "qid": qid,
                "output": "JSON",
                "pageno": 1,
                "responseset": str(max(limit, 1)),
            },
        )
        response.raise_for_status()
        rows: list[dict[str, Any]] = response.json().get("Results", {}).get("Facilities") or []
        return rows[:limit]


def decimal(value: str | None) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation):
        return None


def zip5(value: str | None) -> str | None:
    digits = "".join(c for c in (value or "") if c.isdigit())[:5]
    return digits if len(digits) == 5 else None


async def seed(conn: asyncpg.Connection, rows: list[dict[str, Any]]) -> int:
    # The checksum is deliberately not a hash of anything. This is not a pull,
    # and a plausible-looking checksum on a row that never checksummed a
    # download would be the kind of audit trail that lies about itself.
    snapshot_id = await conn.fetchval(
        SNAPSHOT,
        f"{ECHO}.get_qid",
        "not-a-checksum-this-is-an-audit-seed",
        len(rows),
        "CS-308 audit seed. Real ECHO facilities, loaded without the Phase 1 "
        "adapter: no checksummed snapshot, no quality gate, no coordinates.",
    )

    written = 0
    for row in rows:
        registry = (row.get("RegistryID") or "").strip()
        if not registry:
            continue
        naics = (row.get("AIRNAICS") or "").split(" ")[0] or None
        programs = row.get("AIRPrograms") or ""
        await conn.execute(
            FACILITY,
            registry,
            registry,
            (row.get("AIRName") or "").strip(),
            (row.get("AIRStreet") or "").strip() or None,
            (row.get("AIRCity") or "").strip() or None,
            zip5(row.get("AIRZip")),
            naics,
            decimal(row.get("FacLat")),
            decimal(row.get("FacLong")),
            "Major Emissions" in (row.get("AIRClassification") or ""),
            "V" in programs.split(", "),
            f"https://echo.epa.gov/detailed-facility-report?fid={registry}",
            snapshot_id,
        )
        written += 1
    return written


async def main_async(args: argparse.Namespace) -> int:
    if args.from_file:
        # Replaying a saved response rather than asking again. ECHO rate-limits,
        # and this seed is run repeatedly while the audit harness is developed;
        # re-fetching the same facilities each time earns a 429 and teaches
        # nothing.
        payload = json.loads(Path(args.from_file).read_text())
        rows = (
            payload.get("Results", {}).get("Facilities", [])
            if isinstance(payload, dict)
            else payload
        )
        rows = rows[: args.limit]
        print(f"replayed {len(rows)} facilities from {args.from_file}")
    else:
        rows = await fetch_facilities(args.limit)
        print(f"fetched {len(rows)} Louisiana major air sources from ECHO")

    conn = await asyncpg.connect(args.database_url)
    try:
        written = await seed(conn, rows)
        total = await conn.fetchval("SELECT count(*) FROM facility")
    finally:
        await conn.close()

    print(f"seeded {written}; facility now holds {total} rows")
    if args.out:
        Path(args.out).write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed real ECHO facilities for the audit.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument("--out", default=None, help="also write the raw rows here")
    parser.add_argument(
        "--from-file", default=None, help="replay a saved ECHO response instead of fetching"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(main_async(parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
