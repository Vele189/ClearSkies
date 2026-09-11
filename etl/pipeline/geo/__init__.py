"""Geospatial operations shared by every source that carries a location.

Kept out of the adapters because two sources already need the same answers.
ECHO and TRI both publish self-reported facility coordinates, both have to
decide which of those coordinates are trustworthy enough to attribute a release
to a neighbourhood, and both have to name the resolution 8 cell a facility sits
in. One implementation is what stops the two from drifting into disagreeing
about what a bad coordinate is, which would surface as a parish that is clean on
the map for a reason nobody could reconstruct.
"""

from pipeline.geo.assignment import (
    ACCURACY_VERIFIED_M,
    EARTH_RADIUS_KM,
    HEX_RESOLUTION,
    INTERACTION_RADIUS_M,
    NULL_ISLAND_DEG,
    PILOT_BOUNDS,
    QUARANTINED,
    WITHOUT_POINT,
    ZIP_MISMATCH_KM,
    CoordinateStatus,
    Envelope,
    Geocode,
    GeocodeQuality,
    classify,
    containing_cell,
    haversine_km,
    interaction_envelope,
)

__all__ = [
    "ACCURACY_VERIFIED_M",
    "EARTH_RADIUS_KM",
    "HEX_RESOLUTION",
    "INTERACTION_RADIUS_M",
    "NULL_ISLAND_DEG",
    "PILOT_BOUNDS",
    "QUARANTINED",
    "WITHOUT_POINT",
    "ZIP_MISMATCH_KM",
    "CoordinateStatus",
    "Envelope",
    "Geocode",
    "GeocodeQuality",
    "classify",
    "containing_cell",
    "haversine_km",
    "interaction_envelope",
]
