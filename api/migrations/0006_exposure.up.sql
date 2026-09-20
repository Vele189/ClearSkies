-- 0006: modeled air toxics exposure at its native geography
--
-- E1 and E2 arrive from AirToxScreen as census tract values. They are stored
-- here as published and interpolated to hexes at scoring time through
-- tract_hex_weight, rather than being interpolated on the way in. Keeping the
-- source values means a hex's E1 can be walked back to the tract record it came
-- from, which is design principle 1, and it means a change to the interpolation
-- does not require re-downloading anything.
--
-- Both are intensive quantities: modeled risks are rates and do not sum across
-- space, so section 7 combines them as a population-weighted mean and never by
-- area share.

CREATE TABLE tract_exposure (
    tract_geoid              char(11) NOT NULL REFERENCES census_tract(geoid) ON DELETE CASCADE,
    vintage_year             smallint NOT NULL,
    cancer_risk_per_million  numeric CHECK (cancer_risk_per_million >= 0),
    respiratory_hazard_index numeric CHECK (respiratory_hazard_index >= 0),
    snapshot_id              bigint   NOT NULL REFERENCES source_snapshot(snapshot_id),
    PRIMARY KEY (tract_geoid, vintage_year)
);

COMMENT ON COLUMN tract_exposure.cancer_risk_per_million IS
    'E1. Modeled lifetime inhalation cancer risk per million.';
COMMENT ON COLUMN tract_exposure.respiratory_hazard_index IS
    'E2. Modeled respiratory hazard index.';
COMMENT ON COLUMN tract_exposure.vintage_year IS
    'AirToxScreen release year. The emissions inventory behind it is older still, '
    'which is what the c_recency term in section 12 accounts for.';

-- A NULL here is an absence and stays one. Section 11 is explicit that no
-- AirToxScreen value for a tract is not the same fact as a zero, and the
-- pipeline never coerces one into the other.
