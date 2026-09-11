"""Data source adapters.

Importing this package registers every adapter it knows about. Phase 1 adds the
five real sources next to the reference implementation:

    epa_echo      facilities, permits, violations, enforcement   (F1-F4)
    epa_tri       annual on-site air releases                    (E3)
    airtoxscreen  modeled cancer risk and respiratory hazard     (E1, E2)
    openaq        measured PM2.5                                 (E4)
    census_acs    income, poverty, education, language, age      (S1-S2, P1-P5)

Each is one module here plus one line in this file.
"""

from pipeline.adapters.airtoxscreen import AirToxScreenAdapter
from pipeline.adapters.base import FetchResult, SourceAdapter
from pipeline.adapters.echo import EpaEchoAdapter
from pipeline.adapters.fake import FakeAirAdapter
from pipeline.adapters.registry import REGISTRY, get, names, register, specs
from pipeline.adapters.tri import EpaTriAdapter

__all__ = [
    "REGISTRY",
    "AirToxScreenAdapter",
    "EpaEchoAdapter",
    "EpaTriAdapter",
    "FakeAirAdapter",
    "FetchResult",
    "SourceAdapter",
    "get",
    "names",
    "register",
    "specs",
]
