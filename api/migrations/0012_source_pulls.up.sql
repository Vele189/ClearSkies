-- 0012: every pull, kept, not just the latest one (CS-110)
--
-- `source_snapshot` records the bytes a run downloaded. `pipeline_run` records
-- that a night happened. Neither records what one adapter's pull of one source
-- actually did: which release it read, how many records survived validation,
-- how many it rejected and for what reasons, what it is known not to cover, and
-- whether it ended ok, partial, stale or failed. That is `PullMetadata`, the
-- manifest every run emits, and until now it lived in a JSON file beside the run
-- and was gone as soon as the next night overwrote the directory.
--
-- Keeping it matters for a reason the provenance page makes concrete. The page
-- answers "where did this number come from", and the honest version of that
-- answer is not "the latest pull" but "this pull, on this date, of this release,
-- which also missed these counties". A reader checking a claim from a month ago
-- needs the manifest from a month ago.
--
-- Three tables because a manifest has three shapes. The pull is one row. Its
-- known gaps are a list that outlives any single pull and is worth querying
-- across sources: "which sources currently have a geographic gap" is a question
-- the drill-down panel asks. Its artifacts are a list of checksummed files,
-- which is what lets a later run tell "upstream republished" from "upstream
-- moved the same file".
--
-- The rejection histogram stays a JSONB column rather than becoming a fourth
-- table. It is a small map read whole, and the question asked of it is "why did
-- this pull lose rows", never "show me this reason across every source".

CREATE TABLE source_pull (
    pull_id         bigserial   PRIMARY KEY,
    -- The nightly run this pull belonged to, as the ledger names it. Text
    -- rather than a foreign key because a pull can happen outside a nightly run
    -- (`python -m pipeline run epa_echo`) and still deserves a provenance row.
    run_id          text,
    source          text        NOT NULL,
    source_title    text        NOT NULL,
    -- The upstream release identifier, not the download date. A six-year-old
    -- file downloaded tonight is still six years old, and the recency term in
    -- methodology section 12 is computed from this.
    vintage         text        NOT NULL,
    pulled_at       timestamptz NOT NULL,
    status          text        NOT NULL
                        CHECK (status IN ('ok', 'partial', 'stale', 'failed')),

    records_fetched    integer  NOT NULL DEFAULT 0,
    records_validated  integer  NOT NULL DEFAULT 0,
    records_rejected   integer  NOT NULL DEFAULT 0,
    records_normalized integer  NOT NULL DEFAULT 0,
    records_loaded     integer  NOT NULL DEFAULT 0,

    -- Reason to count, e.g. {"latitude outside pilot state": 12}. Read whole.
    rejection_reasons  jsonb    NOT NULL DEFAULT '{}'::jsonb,
    duration_s         double precision NOT NULL DEFAULT 0,
    notes              text[]   NOT NULL DEFAULT '{}',

    -- Set when this pull was part of a nightly run that reached the database.
    pipeline_run_id bigint      REFERENCES pipeline_run(run_id) ON DELETE SET NULL,

    -- A failed pull loaded nothing. Recording one as having loaded rows would
    -- put a row count on the provenance page for data that is not there.
    CONSTRAINT source_pull_failed_loads_nothing
        CHECK (status <> 'failed' OR records_loaded = 0)
);

COMMENT ON TABLE source_pull IS
    'One adapter run of one source: the PullMetadata manifest, kept per run.';
COMMENT ON COLUMN source_pull.vintage IS
    'Upstream release identifier as published. Not the download time.';
COMMENT ON COLUMN source_pull.status IS
    'ok, partial (some records rejected within tolerance), stale (served from snapshot), failed.';
COMMENT ON COLUMN source_pull.records_loaded IS
    'Rows that reached the database. The count the provenance page publishes.';

-- The query the provenance page and the API endpoint both run: the most recent
-- pull of each source, newest first.
CREATE INDEX source_pull_latest
    ON source_pull (source, pulled_at DESC);

-- One pull of one source per nightly run. A second means the run pulled the
-- same source twice, which would double-count it in any history.
CREATE UNIQUE INDEX source_pull_once_per_run
    ON source_pull (run_id, source) WHERE run_id IS NOT NULL;


-- What a pull does not cover, recorded rather than smoothed over. A gap is not
-- a failure: it is the difference between a value that is absent and a value
-- that is zero, carried forward so the confidence term and the drill-down panel
-- can both show it (methodology sections 11 and 12).
CREATE TABLE source_pull_gap (
    gap_id   bigserial PRIMARY KEY,
    pull_id  bigint    NOT NULL REFERENCES source_pull(pull_id) ON DELETE CASCADE,
    scope    text      NOT NULL CHECK (scope IN (
                 'geographic', 'temporal', 'attribute', 'population', 'methodological'
             )),
    detail   text      NOT NULL,
    -- Indicator ids this gap degrades, e.g. {'E4'}. Empty when it degrades none
    -- in particular.
    affects  text[]    NOT NULL DEFAULT '{}',
    since    date
);

COMMENT ON TABLE source_pull_gap IS
    'Known gaps for one pull. Feeds the confidence term and the drill-down panel.';

-- "Which sources currently have a geographic gap", without scanning every pull.
CREATE INDEX source_pull_gap_by_scope ON source_pull_gap (scope);


-- One downloaded file, checksummed. Several EPA datasets were withdrawn from
-- public hosting during 2025 (methodology section 6), so the exact URL and date
-- are recorded and the bytes are hashed. The hash is what distinguishes
-- "upstream republished the data" from "upstream is serving the same file at a
-- new address", and it is what makes the stale fallback auditable.
CREATE TABLE source_pull_artifact (
    artifact_id   bigserial   PRIMARY KEY,
    pull_id       bigint      NOT NULL REFERENCES source_pull(pull_id) ON DELETE CASCADE,
    url           text        NOT NULL,
    retrieved_at  timestamptz NOT NULL,
    sha256        text        NOT NULL,
    size_bytes    bigint      NOT NULL DEFAULT 0,
    media_type    text,
    -- True when these bytes came from the last good snapshot rather than the
    -- network, which is what a `stale` pull means in concrete terms.
    from_snapshot boolean     NOT NULL DEFAULT false
);

COMMENT ON COLUMN source_pull_artifact.sha256 IS
    'Full sha256 of the downloaded bytes. The provenance page prints the first twelve.';

CREATE INDEX source_pull_artifact_by_pull ON source_pull_artifact (pull_id);

-- The same file served twice in one pull is one artifact.
CREATE UNIQUE INDEX source_pull_artifact_once
    ON source_pull_artifact (pull_id, url, sha256);
