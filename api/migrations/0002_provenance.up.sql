-- 0002: source snapshots and pipeline runs
--
-- Methodology section 6 requires every adapter to record the exact URL and
-- retrieval date it used and to checksum what it downloaded, and section 9
-- requires each run's indicator distributions to be kept so a score can be
-- recomputed and audited later. Both are provenance, so both hang off these
-- two tables and every fact table below carries a snapshot_id.
--
-- This is also what makes the availability risk in section 6 survivable: when
-- a source disappears the pipeline continues on the last good snapshot, and
-- because vintage_end travels with the row, the recency term degrades on its
-- own rather than needing anyone to remember.

CREATE TABLE source_snapshot (
    snapshot_id  bigserial   PRIMARY KEY,
    source       text        NOT NULL CHECK (source IN (
                     'echo', 'tri', 'airtoxscreen', 'openaq', 'acs',
                     'census_tract', 'census_block', 'rsei'
                 )),
    url          text        NOT NULL,
    retrieved_at timestamptz NOT NULL,
    checksum     text        NOT NULL,
    record_count integer,
    vintage      text        NOT NULL,
    vintage_end  date        NOT NULL,
    is_mirror    boolean     NOT NULL DEFAULT false,
    notes        text
);

COMMENT ON COLUMN source_snapshot.checksum IS
    'sha256 of the downloaded artifact, so a re-run can prove it read the same bytes.';
COMMENT ON COLUMN source_snapshot.vintage IS
    'Upstream release identifier as published, e.g. ''TRI 2023'' or ''ACS 2019-2023''.';
COMMENT ON COLUMN source_snapshot.vintage_end IS
    'Last date the data describes. Drives the c_recency term, methodology section 12.';
COMMENT ON COLUMN source_snapshot.is_mirror IS
    'True when the adapter read an archived mirror rather than the upstream host.';

-- Two snapshots of the same source with the same bytes are the same snapshot.
CREATE UNIQUE INDEX source_snapshot_content_key
    ON source_snapshot (source, checksum);

CREATE TABLE pipeline_run (
    run_id              bigserial   PRIMARY KEY,
    started_at          timestamptz NOT NULL DEFAULT now(),
    finished_at         timestamptz,
    status              text        NOT NULL DEFAULT 'running'
                            CHECK (status IN ('running', 'succeeded', 'failed')),
    git_sha             text        NOT NULL,
    methodology_version text        NOT NULL,
    scored_hexes        integer,
    is_current          boolean     NOT NULL DEFAULT false,
    notes               text,
    CONSTRAINT pipeline_run_finished_when_done
        CHECK ((status = 'running') = (finished_at IS NULL)),
    CONSTRAINT pipeline_run_current_must_have_succeeded
        CHECK (NOT is_current OR status = 'succeeded')
);

COMMENT ON COLUMN pipeline_run.methodology_version IS
    'Version of docs/methodology.md this run implemented, e.g. 0.1.1.';
COMMENT ON COLUMN pipeline_run.is_current IS
    'The run the API and the tiles serve. Exactly one run may hold it.';

-- Enforces "at most one current run" without a trigger. The index covers only
-- rows where is_current holds, and in those rows the key is the same value, so
-- a second one collides with the first.
CREATE UNIQUE INDEX pipeline_run_one_current
    ON pipeline_run (is_current) WHERE is_current;

-- Which vintage of each source a given run actually read. This is what fills
-- the data_vintage map on the hex detail payload.
CREATE TABLE pipeline_run_source (
    run_id      bigint NOT NULL REFERENCES pipeline_run(run_id) ON DELETE CASCADE,
    snapshot_id bigint NOT NULL REFERENCES source_snapshot(snapshot_id),
    PRIMARY KEY (run_id, snapshot_id)
);
