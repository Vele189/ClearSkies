-- 0032: cleanup_site, the Superfund sites behind indicator F5
--
-- Methodology v0.4.0 section 8.2 adds F5, a distance-decayed count of
-- Superfund sites currently on the Final National Priorities List or proposed
-- for it. The source is EPA's Superfund Enterprise Management System as
-- Envirofacts publishes it, loaded by `pipeline.adapters.sems`.
--
-- Every SEMS site in the state with an NPL status is stored, not only the two
-- statuses F5 counts. Deleted, removed and part-of-site rows are what the hex
-- panel needs to say why a nearby site does not count, and which statuses
-- count is section 8.2's decision, made in the scoring query, not here.
--
-- No link function. F5 aggregates through `facility_decay_weight`, the one
-- definition of decay 0014 already holds, so cleanup sites and facilities are
-- decayed by the same expression and cannot drift apart.

ALTER TABLE source_snapshot DROP CONSTRAINT IF EXISTS source_snapshot_source_check;
ALTER TABLE source_snapshot ADD CONSTRAINT source_snapshot_source_check CHECK (source IN (
    'echo', 'tri', 'airtoxscreen', 'openaq', 'acs', 'census_tract', 'census_block',
    'rsei', 'places', 'sems'
));

CREATE TABLE cleanup_site (
    site_id          text        PRIMARY KEY,
    epa_id           text,
    name             text        NOT NULL,
    city             text,
    county_fips      char(5),
    state            char(2)     NOT NULL,
    -- SEMS's own codes: F final, P proposed, D deleted, R removed from
    -- proposed, A part of another NPL site. 'N' sites are not stored.
    npl_status_code  char(1)     NOT NULL CHECK (npl_status_code IN ('F', 'P', 'D', 'R', 'A')),
    npl_status_name  text        NOT NULL,
    is_federal       boolean     NOT NULL,
    geom             geometry(Point, 4326) NOT NULL,
    h3               h3_cell     NOT NULL,
    snapshot_id      bigint      NOT NULL REFERENCES source_snapshot(snapshot_id),
    first_seen_at    timestamptz NOT NULL DEFAULT now(),
    last_seen_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX cleanup_site_geog_idx ON cleanup_site USING gist ((geom::geography));

COMMENT ON TABLE cleanup_site IS
    'Superfund sites with an NPL status, from EPA SEMS via Envirofacts. F5 counts '
    'statuses F and P (methodology section 8.2); the others explain why a nearby '
    'site does not count.';
