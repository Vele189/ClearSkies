-- 0011: the section 7 mapping of modeled air toxics onto the hex grid
--
-- 0006 stores AirToxScreen as published, at census tract level, and says the
-- interpolation to hexes happens through tract_hex_weight rather than on the way
-- in. That still holds and this table does not change it: tract_exposure remains
-- the source of record, a hex value can still be walked back to the tract rows
-- it came from, and this table is derived, so a change to the interpolation is a
-- recompute and never a re-download. What it adds is somewhere to put the
-- result, because CS-103 requires every hex in the pilot state to hold either a
-- value or an explicit, counted absence, and a mapping whose output is thrown
-- away can make no such guarantee.
--
-- E1 and E2 are intensive: modeled risks are rates and do not sum across space.
-- Section 7 combines them as a population-weighted mean of the tract values
-- overlapping the hex, never by area share and never by recomputing a rate from
-- separately interpolated parts. That arithmetic is pipeline/interpolate.py; the
-- columns here record what it produced and how well supported it was.

CREATE TABLE hex_exposure (
    h3                         h3_cell  NOT NULL REFERENCES hex(h3) ON DELETE CASCADE,
    vintage_year               smallint NOT NULL,
    cancer_risk_per_million    numeric  CHECK (cancer_risk_per_million >= 0),
    respiratory_hazard_index   numeric  CHECK (respiratory_hazard_index >= 0),
    cancer_risk_absence        text     CHECK (cancer_risk_absence IN (
                                   'no_overlapping_source', 'no_source_value', 'no_population'
                               )),
    respiratory_hazard_absence text     CHECK (respiratory_hazard_absence IN (
                                   'no_overlapping_source', 'no_source_value', 'no_population'
                               )),
    tract_count                integer  NOT NULL CHECK (tract_count >= 0),
    population                 numeric  NOT NULL CHECK (population >= 0),
    snapshot_id                bigint   NOT NULL REFERENCES source_snapshot(snapshot_id),
    PRIMARY KEY (h3, vintage_year),

    -- A hex holds a value or the reason it holds none, never both and never
    -- neither. Same shape as hex_score's scored-xor-reason rule and for the same
    -- reason: a map has to be able to explain every cell it draws, and "NULL"
    -- on its own explains nothing.
    CONSTRAINT hex_exposure_cancer_value_xor_absence
        CHECK ((cancer_risk_per_million IS NULL) = (cancer_risk_absence IS NOT NULL)),
    CONSTRAINT hex_exposure_respiratory_value_xor_absence
        CHECK ((respiratory_hazard_index IS NULL) = (respiratory_hazard_absence IS NOT NULL))
);

COMMENT ON TABLE hex_exposure IS
    'Section 7 applied to tract_exposure: one row per hex per AirToxScreen vintage, '
    'including hexes that received no value. Derived and rebuildable; tract_exposure '
    'is the source of record.';

COMMENT ON COLUMN hex_exposure.vintage_year IS
    'AirToxScreen release year, matching tract_exposure.vintage_year. The emissions '
    'inventory behind it is older still, which is what c_recency accounts for.';
COMMENT ON COLUMN hex_exposure.cancer_risk_absence IS
    'Why this hex has no E1 value. no_overlapping_source: the crosswalk knows of no '
    'tract overlapping it. no_source_value: the overlapping tracts are absent from the '
    'release. no_population: every contributing overlap held zero population, so the '
    'population-weighted mean is undefined rather than unknown, and falling back to an '
    'area-weighted mean is what section 7 rules out.';
COMMENT ON COLUMN hex_exposure.tract_count IS
    'Tracts that actually contributed a value, not tracts that overlap. Support for the '
    'value, and an input a reviewer needs to tell one tract from five.';
COMMENT ON COLUMN hex_exposure.population IS
    'Sum of P(t n h) over the contributing tracts: the denominator of the section 7 '
    'population-weighted mean.';

CREATE INDEX hex_exposure_vintage_idx ON hex_exposure (vintage_year);
