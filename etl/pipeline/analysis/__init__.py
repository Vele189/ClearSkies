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
package depends on no database driver, and the ETL has no Postgres door of its
own yet. Until the Postgres sink lands there is no `python -m pipeline` command
here, because a command that cannot connect to anything is worse than none.

`analyse` is the half with no I/O at all. It takes rows and returns the report,
which is what the tests exercise and what any caller with its own connection can
reach after `load_rows`.
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

__all__ = [
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
