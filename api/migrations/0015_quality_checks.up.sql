-- 0015: data quality checks, kept per run (CS-108)
--
-- The adapter interface already records what a pull did, in source_snapshot and
-- in the manifest each run produces. What it has never recorded is what anyone
-- concluded about it: that 13,180 facilities is a normal night, that a tract
-- coverage of 0.93 is not, that the TRI-to-ECHO match rate has been falling for
-- a fortnight. Those judgements lived in a log line and were gone by morning.
--
-- Two tables, because there are two questions. quality_run answers "did last
-- night's load pass", which the API and the deploy both need as one row. Each
-- quality_check_result answers "what has this particular check measured", which
-- is only useful as a series.
--
-- Passing checks are stored too, and that is the point rather than an oversight.
-- Most thresholds in pipeline/quality/expectations.py are deliberately loose
-- envelopes, set before four of the five adapters had ever run against live
-- upstream. Narrowing them safely needs a month of observed values, and a table
-- that keeps only failures cannot supply one.

CREATE TABLE quality_run (
    run_id          text        PRIMARY KEY,
    checked_at      timestamptz NOT NULL,
    verdict         text        NOT NULL CHECK (verdict IN ('pass', 'warn', 'fail', 'skip')),
    passed          boolean     NOT NULL,
    sources         text[]      NOT NULL DEFAULT '{}',
    checks_passed   integer     NOT NULL DEFAULT 0,
    checks_warned   integer     NOT NULL DEFAULT 0,
    checks_failed   integer     NOT NULL DEFAULT 0,
    checks_skipped  integer     NOT NULL DEFAULT 0,
    git_sha         text        NOT NULL DEFAULT '',
    -- Set once the run this gate judged is known. Left null for a gate run
    -- against a dry run or a single source, which has no pipeline_run row.
    pipeline_run_id bigint      REFERENCES pipeline_run(run_id) ON DELETE SET NULL,

    -- A run that failed a check must never read as having passed. The gate does
    -- not roll anything back, so this constraint is the only thing standing
    -- between a failed check and a deploy that promotes the run anyway.
    CONSTRAINT quality_run_passed_matches_verdict
        CHECK (passed = (verdict <> 'fail'))
);

COMMENT ON TABLE quality_run IS
    'One CS-108 gate run: the verdict over one night''s load of every source.';
COMMENT ON COLUMN quality_run.verdict IS
    'Worst status among the run''s checks. fail means the load must not become current.';
COMMENT ON COLUMN quality_run.checks_skipped IS
    'Checks that could not run. A skip is not a pass, and a skip on a required source is a fail.';

CREATE TABLE quality_check_result (
    result_id   bigserial   PRIMARY KEY,
    run_id      text        NOT NULL REFERENCES quality_run(run_id) ON DELETE CASCADE,
    checked_at  timestamptz NOT NULL,
    -- The source registry name, or 'cross' for a check spanning sources.
    scope       text        NOT NULL,
    table_name  text,
    check_name  text        NOT NULL,
    field_name  text,
    status      text        NOT NULL CHECK (status IN ('pass', 'warn', 'fail', 'skip')),
    -- The number measured. Null for a check that is not a measurement, such as
    -- an unmapped category code, and for every skip.
    observed    double precision,
    expected    text,
    detail      text        NOT NULL
);

COMMENT ON COLUMN quality_check_result.observed IS
    'What this check measured. Stored for passing runs too, so a threshold can be narrowed from history rather than from memory.';
COMMENT ON COLUMN quality_check_result.detail IS
    'One sentence a reader who did not write the check can act on.';

-- One row per check per run. A second row for the same check in the same run
-- means the gate ran it twice, which would double-count it in any trend.
CREATE UNIQUE INDEX quality_check_result_once_per_run
    ON quality_check_result (run_id, scope, check_name, coalesce(table_name, ''));

-- The query this table exists to serve: one check's history, newest first.
CREATE INDEX quality_check_result_series
    ON quality_check_result (scope, check_name, checked_at DESC);

-- Finding last night's failures without scanning the series.
CREATE INDEX quality_check_result_failures
    ON quality_check_result (checked_at DESC)
    WHERE status IN ('fail', 'warn');
