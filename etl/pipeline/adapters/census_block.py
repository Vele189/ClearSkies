"""2020 Decennial census blocks: the ancillary layer of methodology section 7 (CS-112).

Section 7 moves tract values onto hexagons by apportioning them through block
populations rather than by area, because a tract that straddles a hex boundary
does not hold its people evenly across it. `pipeline.dasymetric` has that
arithmetic and its tests; this is the source that gives it something to run on.

The blocks are not a scored source and provide no indicator. They exist so that
`tract_hex_weight` can be built, which every tract-sourced indicator then reads.
`SourceSpec.provides` is empty for that reason, and the quality gate's
group-minimum checks will not look for it.

**Why the counts come from TIGERweb rather than the PL 94-171 API.** The block
layer carries `POP100`, and `POP100` *is* the PL 94-171 count: checked against
`api.census.gov/data/2020/dec/pl` for every block of tract 22001960101 on
2026-09-20, 126 of 126 matched exactly, totals 3,405 against 3,405. Taking both
from one response means the geometry and the count are the same vintage over the
same block set by construction, where two sources could disagree about which
blocks exist and strand the difference. The trade is that the provenance URL is
TIGERweb's, which is recorded as what it is.

**On vintages.** Blocks come from `tigerWMS_Census2020` and the tracts CS-105
loaded come from `tigerWMS_ACS2024`. Those are the same 2020 tract boundaries —
tract geography is fixed for the decade — and it was verified rather than
assumed: all 142,874 Louisiana blocks resolve to one of the 1,388 loaded tracts,
and every loaded tract has at least one block. The ticket warns that two
vintages that disagree strand blocks on tract boundaries and surface as a grid
defect, so the check is worth repeating if either vintage is ever bumped.

**A zero-population block is a fact, not an absence.** Most of Louisiana's
water and marsh blocks hold nobody, and section 7 needs that zero: it is what
keeps an uninhabited overlap from drawing population into a hexagon. So
`population` is a plain int and not a `Measurement`; the Decennial census is a
count of everyone, and a block it reports as empty is empty rather than
unmeasured.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

from pipeline.adapters.base import FetchResult, SourceAdapter
from pipeline.adapters.census_acs import Polygon, _geojson_features, rings_of, to_wkt
from pipeline.adapters.registry import register
from pipeline.context import RunContext
from pipeline.errors import PermanentSourceError, RecordRejected
from pipeline.metadata import Artifact, SourceSpec
from pipeline.policy import RateLimit, SourcePolicy
from pipeline.quality.checks import (
    Bounds,
    NullRate,
    RowCount,
    SourceExpectations,
    TableExpectations,
)
from pipeline.records import NormalizedRecord

#: The 2020 Decennial geography. Blocks are defined once a decade and this one
#: is the vintage the PL 94-171 counts are published on, so it is a constant
#: somebody bumps in 2030 rather than something to probe for.
TIGER_SERVICE = "tigerWMS_Census2020"
TIGERWEB = (
    f"https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/{TIGER_SERVICE}/MapServer"
)
BLOCK_LAYER = 10

VINTAGE = "dec2020_pl94171"

STATE_FIPS: Mapping[str, str] = {"LA": "22"}

#: Blocks are far smaller polygons than tracts, so a page holds more of them
#: before the response approaches the size the firewall in front of TIGERweb
#: refuses. 1,000 keeps a page near a few megabytes; the layer would allow
#: 100,000 and the firewall would not.
GEOMETRY_PAGE_SIZE = 1_000

#: Decimal places of longitude and latitude to ask TIGERweb for. Six is about
#: 0.11 m, which is an order of magnitude finer than TIGER's own positional
#: accuracy for a block boundary, and the layer is consumed by an area
#: intersection in EPSG:5070 where a tenth of a metre on a vertex changes
#: nothing. It is one digit coarser than the tract layer's `WKT_PRECISION`,
#: and it is worth it: full precision costs 2.16 MB and 14 s a page against
#: 1.27 MB and 8.4 s, measured on 2026-09-20, over 143 pages.
GEOMETRY_PRECISION = 6

#: Refuses to page forever if upstream stops honouring resultOffset.
MAX_PAGES = 400

#: Louisiana's published 2020 Decennial resident population. The statewide block
#: total is checked against it, per CS-112: a block layer that silently lost a
#: parish is one whose weights would be quietly wrong everywhere downstream.
LOUISIANA_POPULATION_2020 = 4_657_757

#: How far the summed block population may sit from the published figure. Tight
#: on purpose — these are counts of the same universe from the same release, so
#: they should agree exactly and any drift is a loading fault rather than
#: sampling.
POPULATION_TOLERANCE = 0.005


@dataclass(frozen=True, slots=True)
class RawBlock:
    """One block as TIGERweb returned it."""

    geoid: str
    tract_geoid: str
    population: int
    aland_m2: int | None
    polygons: tuple[Polygon, ...]


class CensusBlock(NormalizedRecord):
    """One 2020 block: where it is, and how many people the census counted in it."""

    table: ClassVar[str] = "census_block"

    geoid: str
    tract_geoid: str
    geom_wkt: str
    population: int
    aland_m2: int | None

    def natural_key(self) -> tuple[str, ...]:
        return (self.geoid,)


@register
class CensusBlockAdapter(SourceAdapter[RawBlock]):
    """2020 Decennial blocks with their PL 94-171 counts, for section 7."""

    spec = SourceSpec(
        name="census_block",
        title="US Census 2020 Decennial block population and geography (PL 94-171)",
        homepage="https://www.census.gov/programs-surveys/decennial-census/about/rdo/summary-files.html",
        cadence="decennial; fixed until the 2030 census",
        native_geography="census block",
        # Ancillary. It carries no indicator of its own; it is what lets the
        # tract-sourced ones reach a hexagon at all.
        provides=(),
    )

    # Same reasoning as the ACS adapter, which queries the same host: TIGERweb
    # sits behind a firewall that has refused an oversized query before, and a
    # geometry page is megabytes rather than kilobytes.
    policy: ClassVar[SourcePolicy] = SourcePolicy(
        rate_limit=RateLimit(requests_per_second=2.0, burst=2),
        request_timeout_s=90.0,
    )

    expectations: ClassVar[SourceExpectations | None] = SourceExpectations(
        source="census_block",
        tables=(
            TableExpectations(
                table="census_block",
                # Grounded: TIGERweb reported 142,874 Louisiana blocks on
                # 2026-09-20. Block geography is fixed until 2030, so the range
                # is tight on both sides — a materially different count means
                # the query or the vintage changed, not that Louisiana did.
                rows=RowCount(135_000, 150_000, note="Live layer returned 142,874 blocks for LA."),
                null_rates=(
                    NullRate("geoid", 0.0),
                    NullRate("tract_geoid", 0.0),
                    NullRate(
                        "population",
                        0.0,
                        note="A count, never an estimate. Zero is a value, not an absence.",
                    ),
                ),
                bounds=(
                    # No Louisiana block approaches this; it catches a parsing
                    # fault that shifts a digit rather than a real settlement.
                    Bounds("population", 0, 50_000),
                ),
            ),
        ),
    )

    async def fetch(self, ctx: RunContext) -> FetchResult[RawBlock]:
        fips = STATE_FIPS.get(ctx.pilot_state)
        if fips is None:
            raise PermanentSourceError(
                f"no state FIPS for pilot state {ctx.pilot_state!r}; "
                f"known: {', '.join(sorted(STATE_FIPS))}"
            )

        records: list[RawBlock] = []
        seen: set[str] = set()
        artifacts: list[Artifact] = []
        url = f"{TIGERWEB}/{BLOCK_LAYER}/query"

        for page in range(MAX_PAGES):
            offset = page * GEOMETRY_PAGE_SIZE
            query = (
                f"{url}?where=STATE%3D%27{fips}%27"
                f"&outFields=GEOID,TRACT,COUNTY,STATE,POP100,AREALAND"
                f"&returnGeometry=true&outSR=4326&geometryPrecision={GEOMETRY_PRECISION}"
                f"&orderByFields=GEOID"
                f"&resultOffset={offset}&resultRecordCount={GEOMETRY_PAGE_SIZE}&f=geojson"
            )
            download = await ctx.http.get(query)
            artifacts.append(download.artifact)
            features = _geojson_features(download.content, query)
            if not features:
                break

            for feature in features:
                raw = _raw_block(feature)
                if raw is not None and raw.geoid not in seen:
                    seen.add(raw.geoid)
                    records.append(raw)

            if len(features) < GEOMETRY_PAGE_SIZE:
                break
        else:
            raise PermanentSourceError(
                f"{TIGERWEB}/{BLOCK_LAYER}: still returning full pages after "
                f"{MAX_PAGES} of them; upstream is probably ignoring resultOffset"
            )

        if not records:
            raise PermanentSourceError(f"{TIGERWEB}/{BLOCK_LAYER}: state {fips} returned no blocks")

        return FetchResult(
            records=records,
            vintage=VINTAGE,
            artifacts=tuple(artifacts),
            notes=(
                f"{len(records)} blocks over {len({r.tract_geoid for r in records})} tracts.",
                _population_note(records),
            ),
        )

    def validate(self, record: RawBlock, ctx: RunContext) -> None:
        if len(record.geoid) != 15:
            raise RecordRejected(
                f"block geoid {record.geoid!r} is {len(record.geoid)} characters, not 15"
            )
        if not record.geoid.startswith(record.tract_geoid):
            raise RecordRejected(
                f"block {record.geoid} does not sit in the tract it names, {record.tract_geoid}"
            )
        if record.population < 0:
            raise RecordRejected(f"block {record.geoid} reports population {record.population}")
        if not record.polygons:
            # Not a warning. `census_block.geom` is NOT NULL and the
            # interpolation intersects it; a block with no geometry cannot
            # contribute and would fail at the sink instead of here.
            raise RecordRejected(f"block {record.geoid} carries no usable geometry")

    def normalize(self, record: RawBlock, ctx: RunContext) -> Iterable[NormalizedRecord]:
        yield CensusBlock(
            geoid=record.geoid,
            tract_geoid=record.tract_geoid,
            geom_wkt=to_wkt(record.polygons),
            population=record.population,
            aland_m2=record.aland_m2,
        )


def _raw_block(feature: Mapping[str, Any]) -> RawBlock | None:
    """One GeoJSON feature as a `RawBlock`, or None when it is unusable.

    Returning None rather than raising: a feature missing the identifier cannot
    be reported against a block, so there is nothing for a rejection to name.
    The count of what arrived is in the manifest either way.
    """
    attributes = feature.get("properties") or {}
    geoid = str(attributes.get("GEOID") or "").strip()
    if not geoid:
        return None

    population = attributes.get("POP100")
    land = attributes.get("AREALAND")
    return RawBlock(
        geoid=geoid,
        # Composed rather than read: TIGERweb returns TRACT as the six-digit
        # code within the county, and census_tract is keyed on the full eleven.
        tract_geoid=geoid[:11],
        population=int(population) if population is not None else 0,
        aland_m2=int(land) if land is not None else None,
        polygons=rings_of(feature.get("geometry") or {}),
    )


def _population_note(records: Sequence[RawBlock]) -> str:
    """CS-112's statewide check, reported rather than enforced.

    A note and not a rejection: the adapter cannot tell a genuinely changed
    published figure from a bad load, and the run that fails this is one whose
    numbers a person should look at rather than one the pipeline should discard.
    The gate's row-count expectation is what refuses an obviously short pull.
    """
    total = sum(record.population for record in records)
    error = abs(total - LOUISIANA_POPULATION_2020) / LOUISIANA_POPULATION_2020
    verdict = "matches" if error <= POPULATION_TOLERANCE else "DOES NOT MATCH"
    return (
        f"Block population totals {total:,} against {LOUISIANA_POPULATION_2020:,} "
        f"published for the 2020 census, {error:.2%} apart: {verdict}."
    )
