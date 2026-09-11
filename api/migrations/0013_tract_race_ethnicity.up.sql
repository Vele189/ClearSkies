-- 0013: tract-level race and ethnicity, deliberately not in tract_demographics
--
-- Section 8.5 ingests race and ethnicity; section 14 keeps them out of the
-- score. 0008 already honours that after interpolation, where the three hex
-- columns are commented as displayed and never scored. It left nothing to hold
-- them before interpolation, and the only place they would otherwise fit is
-- tract_demographics, which is the table every indicator reads.
--
-- A variable filter is a weak boundary. `WHERE variable LIKE 'B%'` widened by
-- one careless character would pull racial composition into an indicator, and
-- nothing would fail; the score would simply become the thing section 14 says
-- it must not be. A separate table is a boundary that holds, because reaching
-- across it takes a join somebody has to write and a reviewer would see.
--
-- Same grain and same columns as tract_demographics on purpose: CS-106
-- interpolates both through one code path, and the hex_demographics columns
-- these feed already exist.

CREATE TABLE tract_race_ethnicity (
    tract_geoid     char(11) NOT NULL REFERENCES census_tract(geoid) ON DELETE CASCADE,
    acs_vintage     text     NOT NULL,
    variable        text     NOT NULL,
    estimate        numeric,
    margin_of_error numeric CHECK (margin_of_error >= 0),
    is_extensive    boolean  NOT NULL,
    snapshot_id     bigint   NOT NULL REFERENCES source_snapshot(snapshot_id),
    PRIMARY KEY (tract_geoid, acs_vintage, variable)
);

COMMENT ON TABLE tract_race_ethnicity IS
    'Recorded, displayed and used in the section 13.6 disparity analysis. Never an input '
    'to an indicator or a component. Section 14 argues that keeping race out of the '
    'arithmetic is what makes the disparity finding an independent result rather than a '
    'built-in one, so no query that computes a score may read this table.';

COMMENT ON COLUMN tract_race_ethnicity.acs_vintage IS 'Five-year window as published, e.g. 2020-2024.';
COMMENT ON COLUMN tract_race_ethnicity.variable IS
    'ACS variable id, e.g. B03002_004E. B03002 crosses race with Hispanic origin; '
    'B02001_003E is the Black or African American alone total of any ethnicity.';
COMMENT ON COLUMN tract_race_ethnicity.margin_of_error IS
    'Published ACS margin of error, kept for the same reason as in tract_demographics: '
    'a tract-level margin for a small subgroup is frequently larger than the estimate, '
    'and a disparity analysis that ignored that would overstate its own precision.';
