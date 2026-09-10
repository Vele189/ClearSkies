-- 0005: TRI air releases and the toxicity weights that scale them
--
-- The two halves of the E3 formula in methodology section 8.1:
--
--     E3(h) = sum_f [ sum_c w_c * m_{f,c} ] / max(d_{h,f}, 250 m)^2
--
-- m_{f,c} is tri_release.air_lb and w_c is chemical_toxicity_weight.rsei_weight.
-- Keeping the weights in their own table means a new RSEI edition is a data
-- load, not a schema change, and it makes the weight a facility's contribution
-- was computed with recoverable after the fact.

CREATE TABLE chemical_toxicity_weight (
    cas_number     text    PRIMARY KEY,
    chemical_name  text    NOT NULL,
    rsei_weight    numeric NOT NULL CHECK (rsei_weight > 0),
    source_edition text    NOT NULL,
    snapshot_id    bigint  NOT NULL REFERENCES source_snapshot(snapshot_id)
);

COMMENT ON TABLE chemical_toxicity_weight IS
    'EPA RSEI inhalation toxicity weights. w_c in the E3 formula, methodology section 8.1.';

CREATE TABLE tri_release (
    release_id      bigserial PRIMARY KEY,
    facility_id     text     NOT NULL REFERENCES facility(facility_id) ON DELETE CASCADE,
    reporting_year  smallint NOT NULL,
    cas_number      text     NOT NULL,
    chemical_name   text     NOT NULL,
    fugitive_air_lb numeric  NOT NULL DEFAULT 0 CHECK (fugitive_air_lb >= 0),
    stack_air_lb    numeric  NOT NULL DEFAULT 0 CHECK (stack_air_lb >= 0),
    air_lb          numeric  GENERATED ALWAYS AS (fugitive_air_lb + stack_air_lb) STORED,
    snapshot_id     bigint   NOT NULL REFERENCES source_snapshot(snapshot_id),
    UNIQUE (facility_id, reporting_year, cas_number)
);

-- On-site air only. TRI also reports water, land, and off-site transfers, and
-- scoring those against an air burden indicator would be wrong, so they are not
-- stored here at all rather than stored and hopefully filtered later.
COMMENT ON TABLE tri_release IS
    'On-site air releases by facility, chemical and reporting year. Air only, by design.';

-- No foreign key to chemical_toxicity_weight on purpose. TRI reports chemicals
-- that RSEI has no weight for, and a release with no weight is still a fact
-- worth holding: it appears in the drill-down and is excluded from E3, which is
-- the missing-data rule of section 11 rather than a silent drop.
CREATE INDEX tri_release_cas_idx ON tri_release (cas_number);
CREATE INDEX tri_release_year_idx ON tri_release (reporting_year);
