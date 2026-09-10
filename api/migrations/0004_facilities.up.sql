-- 0004: facilities, compliance history, and enforcement actions
--
-- The point sources behind E3 and F1 through F4. Compliance quarters and
-- enforcement actions live here rather than in their own migration because
-- they are facts about a facility and are meaningless without one.
--
-- Section 8.2 is worth reading before using F2 and F3: a facility accumulates
-- violations when somebody inspects it, so these tables partly measure
-- regulatory attention rather than pollution. That is why their group carries
-- weight 0.5, and it is a known bias rather than a solved problem.

CREATE TABLE facility (
    facility_id       text PRIMARY KEY,
    registry_id       text,
    tri_facility_id   text,
    name              text NOT NULL,
    street            text,
    city              text,
    state             char(2),
    zip5              char(5),
    county_fips       char(3),
    naics_code        text,
    geom              geometry(Point, 4326),
    h3                h3_cell REFERENCES hex(h3),
    coordinate_status text NOT NULL DEFAULT 'ok' CHECK (coordinate_status IN (
                          'ok', 'missing', 'outside_state', 'zip_mismatch'
                      )),
    is_major_source   boolean NOT NULL DEFAULT false,
    has_title_v       boolean NOT NULL DEFAULT false,
    is_rcra_lqg       boolean NOT NULL DEFAULT false,
    is_rcra_tsdf      boolean NOT NULL DEFAULT false,
    echo_url          text,
    snapshot_id       bigint  NOT NULL REFERENCES source_snapshot(snapshot_id),
    first_seen_at     timestamptz NOT NULL DEFAULT now(),
    last_seen_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT facility_geom_matches_status
        CHECK ((geom IS NULL) = (coordinate_status = 'missing'))
);

COMMENT ON COLUMN facility.facility_id IS
    'EPA FRS registry id where the facility has one, otherwise the TRI id prefixed ''tri:''.';

-- Section 6, positional accuracy. ECHO and TRI coordinates are self-reported
-- and some of them land in the wrong parish or in open water. Flagged
-- facilities stay in the table, because the exclusion count is published, but
-- proximity indicators must filter on coordinate_status = 'ok'. Deleting them
-- would hide the problem and make the count unrecoverable.
COMMENT ON COLUMN facility.coordinate_status IS
    'Geocoding verdict from section 6. Only ''ok'' facilities enter proximity indicators.';

CREATE INDEX facility_geom_idx ON facility USING gist (geom)
    WHERE coordinate_status = 'ok';
CREATE INDEX facility_h3_idx ON facility (h3);
CREATE INDEX facility_registry_idx ON facility (registry_id);

-- F2, over the trailing twelve quarters.
CREATE TABLE facility_compliance_quarter (
    facility_id text NOT NULL REFERENCES facility(facility_id) ON DELETE CASCADE,
    quarter     date NOT NULL,
    program     text NOT NULL,
    status      text NOT NULL CHECK (status IN (
                    'in_compliance', 'violation', 'high_priority_violation', 'unknown'
                )),
    snapshot_id bigint NOT NULL REFERENCES source_snapshot(snapshot_id),
    PRIMARY KEY (facility_id, quarter, program),
    -- The cast to timestamp is not decoration. Unqualified, Postgres resolves
    -- date_trunc against timestamptz, which is only STABLE and so cannot appear
    -- in a check constraint at all.
    CONSTRAINT facility_compliance_quarter_is_quarter_start
        CHECK (date_trunc('quarter', quarter::timestamp)::date = quarter)
);

COMMENT ON COLUMN facility_compliance_quarter.status IS
    '''unknown'' is distinct from ''in_compliance''. An uninspected quarter is not a clean one.';

-- F3, over the trailing five years.
CREATE TABLE enforcement_action (
    action_id   text PRIMARY KEY,
    facility_id text NOT NULL REFERENCES facility(facility_id) ON DELETE CASCADE,
    program     text,
    action_type text,
    settled_on  date,
    penalty_usd numeric(14, 2) CHECK (penalty_usd >= 0),
    is_formal   boolean NOT NULL DEFAULT true,
    snapshot_id bigint  NOT NULL REFERENCES source_snapshot(snapshot_id)
);

COMMENT ON COLUMN enforcement_action.penalty_usd IS
    'Assessed penalty. F3 log-scales this, so a zero-penalty formal action still counts.';

CREATE INDEX enforcement_action_facility_idx ON enforcement_action (facility_id, settled_on);
