"""Data quality checks and the pipeline gate (CS-108).

A bad load should fail loudly, not quietly poison the score.

The adapter interface already carries the generic half: rejections are counted
per record, one tolerance rule refuses a pull that lost too much, a repeated
natural key fails the run, and every run produces a manifest including the runs
that failed. All of that judges a source against itself. None of it can tell that
a source returned every row it was asked for and still covered a third of the
state, or that the rows it returned no longer join to anything.

This package adds the two halves the interface cannot reach:

    expectations.py   per source: row count ranges, null rates, geometry
                      validity, plausible value bounds, known code sets
    cross.py          between sources: TRI matching ECHO, tract coverage,
                      hex grid agreement, section 11 group minimums

and three things that make a failure land somewhere a person sees it:

    gate.py           runs everything, returns one verdict for the night
    store.py          keeps every check's measurement, passing ones included,
                      so a threshold can be argued from a month of history
    results.py        renders the report as a page and as workflow annotations

The entry point is `run_gate`. The nightly job calls it through
`python -m pipeline check` and exits non-zero when it fails, which is what keeps
the run from becoming the current one.
"""

from pipeline.quality.checks import (
    Bounds,
    Categories,
    Geometry,
    NullRate,
    RowCount,
    SourceExpectations,
    TableExpectations,
    check_table,
)
from pipeline.quality.cross import run_cross_checks
from pipeline.quality.dataset import Dataset, DictDataset, EmptyDataset
from pipeline.quality.expectations import TUNED, for_source
from pipeline.quality.gate import run_gate, run_id_for
from pipeline.quality.results import CheckResult, CheckStatus, QualityReport, Severity
from pipeline.quality.store import JsonQualityStore, QualityStore, summarise_history

__all__ = [
    "TUNED",
    "Bounds",
    "Categories",
    "CheckResult",
    "CheckStatus",
    "Dataset",
    "DictDataset",
    "EmptyDataset",
    "Geometry",
    "JsonQualityStore",
    "NullRate",
    "QualityReport",
    "QualityStore",
    "RowCount",
    "Severity",
    "SourceExpectations",
    "TableExpectations",
    "check_table",
    "for_source",
    "run_cross_checks",
    "run_gate",
    "run_id_for",
    "summarise_history",
]
