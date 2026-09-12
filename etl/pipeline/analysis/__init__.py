"""Analysis over scores that have already been computed (CS-213).

Kept apart from scoring for the reason migration 0013 keeps race in its own
table. Section 14's rule is that racial composition enters no query that computes
a score, and this is the one place in the codebase that reads those columns. A
package boundary is a boundary a reviewer sees: a module under `scoring/` that
read `black_pct` would look ordinary in a diff, and a module here that computed a
score would not.

Nothing in this package returns a verdict. The quality gate of CS-108 exists to
fail a run; this exists to report a finding, and section 13.6 is explicit that
there is no threshold the finding must meet.

    disparity.py    the section 13.6 analysis, its framing, and its report
    statistics.py   population-weighted correlation and its intervals

The entry point is `run_disparity`, which takes a connection rather than opening
one. That follows `pipeline.dasymetric.postgis`, and for the same reason: this
package depends on no database driver, and a connection passed in is a
connection a test can fake. `pipeline/db.py` is what opens one in production.

`analyse` is the half with no I/O at all. It takes rows and returns the report,
which is what the tests exercise and what any caller with its own connection can
reach after `load_rows`.

`python -m pipeline disparity` is the command that supplies the connection. It
lives in `__main__.py` rather than here for the reason every other command does:
this package stays importable without a driver, and the composition root is the
one place allowed to know which driver there is.
"""

from pipeline.analysis.disparity import (
    FRAMING,
    INDEPENDENCE,
    TOP_DECILE,
    Cohort,
    CohortSummary,
    ContrastResult,
    CorrelationResult,
    DisparityReport,
    HexRow,
    Interval,
    Measure,
    analyse,
    build_cohorts,
    contrasts_for,
    correlations_for,
    load_rows,
    run_disparity,
)
from pipeline.analysis.statistics import (
    DEFAULT_LEVEL,
    DEFAULT_RESAMPLES,
    DEFAULT_SEED,
    NotComputable,
)

__all__ = [
    "DEFAULT_LEVEL",
    "DEFAULT_RESAMPLES",
    "DEFAULT_SEED",
    "NotComputable",
    "FRAMING",
    "INDEPENDENCE",
    "TOP_DECILE",
    "Cohort",
    "CohortSummary",
    "ContrastResult",
    "CorrelationResult",
    "DisparityReport",
    "HexRow",
    "Interval",
    "Measure",
    "analyse",
    "build_cohorts",
    "contrasts_for",
    "correlations_for",
    "load_rows",
    "run_disparity",
]
