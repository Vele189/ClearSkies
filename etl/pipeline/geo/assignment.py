"""Putting a facility on the grid, and deciding whether to believe where it says it is.

Two questions, answered here for every source that publishes a point, because
answering them twice is how two sources end up disagreeing about which parish a
refinery is in.

**Which cell contains it.** `containing_cell` is the whole of it: an H3
resolution 8 index, computed in Python with h3-py during the job and stored as
text. Nothing in the pipeline may depend on the `h3-pg` extension, which is
present only for queries a human writes at a prompt (docs/database.md section
1), so the cell is settled here and travels as data.

**Whether the coordinate is usable.** Methodology section 6: ECHO and TRI
coordinates are self-reported and some of them land in the wrong parish, in open
water, or on Null Island. `classify` returns one of six verdicts and a quality
band. Facilities that fail are *quarantined, not dropped*: the row is written,
the verdict is stored on it, and the count reaches the run manifest and from
there docs/provenance.md. Deleting them would hide the problem and make the
exclusion count unrecoverable, which is the one thing section 6 asks the
pipeline not to do.

The six verdicts separate three different upstream mistakes that a single
"bad coordinate" flag would blur together, and the counts are published
separately because they have different causes and different fixes:

    missing        no coordinate was reported at all
    null_island    a placeholder zero, the classic data-entry artefact
    out_of_range   not a point on Earth: a swapped sign, a truncated field
    outside_state  a real point, but too far from the pilot state to interact
    zip_mismatch   a real point, implausibly far from the ZIP also reported
    ok             usable

Note what `outside_state` does *not* mean. Methodology section 5 requires
out-of-state facilities within the interaction radius to count, so that a hex on
the Texas line near a Beaumont-area facility is not artificially clean. The
envelope tested here is therefore the pilot state's bounding box widened by the
interaction radius, and a genuine Texas facility near the line passes as `ok`.
The box is a loose outer bound and nothing more: because Louisiana's western
boundary is the Sabine River rather than a meridian, a point inside the box can
still be tens of kilometres from the state. Deciding which facilities actually
reach which hexagons is the neighbour query's job, on real geometry, in
migration 0011. This only throws out coordinates that cannot be about Louisiana
at all, where being outside the state is evidence about the coordinate rather
than about the facility.
"""

from dataclasses import dataclass
from math import asin, cos, isfinite, pi, radians, sin, sqrt
from typing import Literal

import h3

# Fixed by methodology section 5 and by a check constraint on hex.resolution.
# Serving another resolution is a methodology revision, so it is not a parameter.
HEX_RESOLUTION = 8

# Methodology section 8.1. Facilities beyond this contribute nothing to E3 or to
# F1 through F4: the inverse-square term has fallen far enough by 10 km that
# including them costs computation without changing ranks. It is also what makes
# the envelope below the right width, since a coordinate further outside the
# state than this cannot reach any hexagon in the grid.
INTERACTION_RADIUS_M = 10_000.0

# Section 6. A self-reported coordinate this far from the ZIP code the same
# operator reported is not trustworthy enough to attribute releases to a hexagon.
ZIP_MISMATCH_KM = 2.0

# About 55 m of latitude. A coordinate this close to (0, 0) is a placeholder an
# operator or a loader wrote into an empty field, not a facility in the Gulf of
# Guinea. The envelope test below would catch it anyway; it is called out
# separately because "somebody zeroed the field" and "somebody transcribed the
# coordinate wrongly" are different upstream defects, and section 6 publishes
# the counts rather than one total.
NULL_ISLAND_DEG = 0.0005

# EPA publishes its own positional accuracy estimate per facility
# (CALCULATED_ACCURACY_METERS). At or below this, a coordinate that also passes
# the ZIP check is as good as this pipeline can establish it. Roughly three
# quarters of Louisiana air facilities report an estimate far above it, which is
# itself the reason section 6 does not simply trust the coordinate.
ACCURACY_VERIFIED_M = 100.0

EARTH_RADIUS_KM = 6371.0088

# Metres in a degree of latitude, derived from the same sphere `haversine_km`
# measures on rather than quoted from a table. The usual 111 320 figure is the
# equatorial value on the WGS 84 ellipsoid and is 0.11% larger than this, which
# is enough to make a buffer computed from it come out just under the radius it
# was asked for. Longitude additionally needs the cosine of the latitude, which
# is why `Envelope.buffered` works it out per box rather than using a constant.
METRES_PER_DEGREE_LAT = EARTH_RADIUS_KM * 1000.0 * pi / 180.0

CoordinateStatus = Literal[
    "ok", "missing", "null_island", "out_of_range", "outside_state", "zip_mismatch"
]

GeocodeQuality = Literal["verified", "plausible", "unverified", "suspect", "absent"]

# The verdicts that keep a facility out of the proximity indicators. Every query
# that decays a facility over distance filters on `coordinate_status = 'ok'`, so
# this set and that filter say the same thing from two sides.
QUARANTINED: frozenset[str] = frozenset(
    {"missing", "null_island", "out_of_range", "outside_state", "zip_mismatch"}
)

# Verdicts for which there is no point worth storing. A quarantined coordinate
# that is still a real place on Earth keeps its geometry, because a reviewer
# asking why a facility was excluded needs to see where upstream put it; a
# placeholder zero or an impossible latitude does not survive as geometry at all.
WITHOUT_POINT: frozenset[str] = frozenset({"missing", "null_island", "out_of_range"})


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance on a sphere.

    Used for the ZIP-centroid check and nothing else. Distances that reach an
    indicator are computed by PostGIS on the spheroid, in the neighbour query of
    migration 0011, so that one definition of "within 10 km" serves both the
    drill-down panel and the scoring step. The two differ by roughly 0.3%, which
    matters at a cutoff and does not matter against a 2 km plausibility test.
    """
    r_lat1, r_lat2 = radians(lat1), radians(lat2)
    d_lat = r_lat2 - r_lat1
    d_lon = radians(lon2 - lon1)
    a = sin(d_lat / 2) ** 2 + cos(r_lat1) * cos(r_lat2) * sin(d_lon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


@dataclass(frozen=True, slots=True)
class Envelope:
    """A bounding box in degrees.

    A box rather than the state boundary polygon on purpose. The question this
    answers is whether a self-reported coordinate is close enough to the pilot
    state to be about the pilot state, and a box answers it without the loader
    having to hold TIGER geometry in memory to validate a row. The precise
    boundary is `census_tract` and `hex`, and the grid is what decides which
    hexagons exist.
    """

    south: float
    north: float
    west: float
    east: float

    def contains(self, latitude: float, longitude: float) -> bool:
        return self.south <= latitude <= self.north and self.west <= longitude <= self.east

    def buffered(self, metres: float) -> "Envelope":
        """The same box widened by a distance on the ground.

        Longitude is scaled by the cosine of the latitude furthest from the
        equator, so the buffer is at least `metres` everywhere in the box rather
        than exactly `metres` at its middle and less at its top.
        """
        d_lat = metres / METRES_PER_DEGREE_LAT
        widest = max(abs(self.south), abs(self.north))
        d_lon = metres / (METRES_PER_DEGREE_LAT * cos(radians(widest)))
        return Envelope(
            south=self.south - d_lat,
            north=self.north + d_lat,
            west=self.west - d_lon,
            east=self.east + d_lon,
        )


# Louisiana's extreme latitudes and longitudes, unbuffered. `interaction_envelope`
# is what callers want; this is kept separate so the buffer stays visible as the
# interaction radius rather than as a number somebody once rounded.
PILOT_BOUNDS: dict[str, Envelope] = {
    "LA": Envelope(south=28.92, north=33.02, west=-94.05, east=-88.76),
}


def interaction_envelope(state: str) -> Envelope:
    """The pilot state's bounding box widened by the interaction radius.

    Coordinates inside it are judged on their own merits; coordinates outside it
    cannot be about the pilot state at all, so being outside is evidence the
    coordinate is wrong rather than evidence about where the facility is.
    """
    bounds = PILOT_BOUNDS.get(state.upper())
    if bounds is None:
        raise KeyError(f"no bounding box for pilot state {state!r}; add one to PILOT_BOUNDS")
    return bounds.buffered(INTERACTION_RADIUS_M)


@dataclass(frozen=True, slots=True)
class Geocode:
    """What section 6 concluded about one reported coordinate."""

    status: CoordinateStatus
    quality: GeocodeQuality
    accuracy_m: float | None = None
    # None when the check could not run: no ZIP reported, or one the pinned
    # gazetteer does not carry. Not the same fact as passing, and counted
    # separately in the manifest for that reason.
    zip_distance_km: float | None = None

    @property
    def usable(self) -> bool:
        """True when this facility may enter a proximity indicator."""
        return self.status == "ok"

    @property
    def has_point(self) -> bool:
        """True when the reported coordinate is a real place worth storing as geometry."""
        return self.status not in WITHOUT_POINT

    @property
    def zip_checked(self) -> bool:
        return self.zip_distance_km is not None


def classify(
    latitude: float | None,
    longitude: float | None,
    *,
    state: str,
    zip_centroid: tuple[float, float] | None = None,
    accuracy_m: float | None = None,
) -> Geocode:
    """Judge one reported coordinate. Never raises; every input has a verdict.

    `zip_centroid` is the centroid of the ZIP code the operator reported, from a
    gazetteer pinned to a vintage, or None when the check cannot run. Passing
    None is not a failure and is not silently a pass either: it produces `ok`
    with quality `unverified`, which the manifest counts on its own.
    """
    if latitude is None or longitude is None:
        return Geocode(status="missing", quality="absent", accuracy_m=accuracy_m)

    if not (isfinite(latitude) and isfinite(longitude)):
        return Geocode(status="out_of_range", quality="absent", accuracy_m=accuracy_m)

    if abs(latitude) < NULL_ISLAND_DEG and abs(longitude) < NULL_ISLAND_DEG:
        return Geocode(status="null_island", quality="absent", accuracy_m=accuracy_m)

    if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
        return Geocode(status="out_of_range", quality="absent", accuracy_m=accuracy_m)

    if not interaction_envelope(state).contains(latitude, longitude):
        return Geocode(status="outside_state", quality="suspect", accuracy_m=accuracy_m)

    if zip_centroid is None:
        return Geocode(status="ok", quality="unverified", accuracy_m=accuracy_m)

    distance = haversine_km(latitude, longitude, zip_centroid[0], zip_centroid[1])
    if distance > ZIP_MISMATCH_KM:
        return Geocode(
            status="zip_mismatch",
            quality="suspect",
            accuracy_m=accuracy_m,
            zip_distance_km=distance,
        )

    verified = accuracy_m is not None and accuracy_m <= ACCURACY_VERIFIED_M
    return Geocode(
        status="ok",
        quality="verified" if verified else "plausible",
        accuracy_m=accuracy_m,
        zip_distance_km=distance,
    )


def containing_cell(latitude: float | None, longitude: float | None) -> str | None:
    """The resolution 8 cell containing a point, or None if there is no point.

    Deliberately not conditional on the cell existing in the `hex` table. A
    facility outside the grid still sits in a cell, and `facility.h3` records
    which one so that a Beaumont-area facility can be told apart from a facility
    with no location at all. Migration 0011 drops the foreign key that used to
    say otherwise; joins from `facility` to `hex` are outer joins for the same
    reason.
    """
    if latitude is None or longitude is None:
        return None
    return str(h3.latlng_to_cell(latitude, longitude, HEX_RESOLUTION))
