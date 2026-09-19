-- 0008: ACS estimates at tract level and the interpolated hex profile
--
-- tract_demographics is long rather than wide because the seven ACS indicators
-- of sections 8.3 and 8.4 need roughly thirty underlying variables, each with
-- its own margin of error, and because section 7 forbids recomputing a rate
-- from independently interpolated parts. Storing the published numerator and
-- denominator as separate rows and deriving the rate once at the end is the
-- rule, and a wide table would quietly invite the opposite.

CREATE TABLE tract_demographics (
    tract_geoid     char(11) NOT NULL REFERENCES census_tract(geoid) ON DELETE CASCADE,
    acs_vintage     text     NOT NULL,
    variable        text     NOT NULL,
    estimate        numeric,
    margin_of_error numeric CHECK (margin_of_error >= 0),
    is_extensive    boolean  NOT NULL,
    snapshot_id     bigint   NOT NULL REFERENCES source_snapshot(snapshot_id),
    PRIMARY KEY (tract_geoid, acs_vintage, variable)
);

COMMENT ON COLUMN tract_demographics.acs_vintage IS 'Five-year window as published, e.g. 2019-2023.';
COMMENT ON COLUMN tract_demographics.variable IS 'ACS variable id, e.g. B17002_001E.';
COMMENT ON COLUMN tract_demographics.is_extensive IS
    'True for counts, which are apportioned across hexes; false for rates and ratios, '
    'which are combined as a population-weighted mean. Section 7 calls confusing these '
    'the most common source of error in the whole step.';
COMMENT ON COLUMN tract_demographics.margin_of_error IS
    'Published ACS margin of error. Combined in quadrature and carried into c_spatial; '
    'a high margin degrades confidence and never causes the estimate to be dropped, '
    'because dropping preferentially removes small and rural populations.';

-- The interpolated profile, one row per hex per run.
--
-- Keyed by run because section 9 requires a score to be recomputable and
-- auditable later, which is impossible if a later run has overwritten the
-- inputs the earlier score was built from. The scored subset of these columns
-- also appears in hex_indicator with its percentile; the duplication is
-- deliberate, so that everything that entered one run's arithmetic can be read
-- from one table.
CREATE TABLE hex_demographics (
    run_id                   bigint  NOT NULL REFERENCES pipeline_run(run_id) ON DELETE CASCADE,
    h3                       h3_cell NOT NULL REFERENCES hex(h3) ON DELETE CASCADE,
    population               numeric NOT NULL CHECK (population >= 0),
    households               numeric CHECK (households >= 0),
    under_5_pct              numeric,
    over_64_pct              numeric,
    poverty_200pct           numeric,
    no_hs_diploma_pct        numeric,
    linguistic_isolation_pct numeric,
    unemployment_pct         numeric,
    housing_burden_pct       numeric,
    black_pct                numeric,
    hispanic_pct             numeric,
    people_of_color_pct      numeric,
    max_coefficient_variation numeric CHECK (max_coefficient_variation >= 0),
    mean_block_area_m2       numeric,
    acs_vintage              text    NOT NULL,
    PRIMARY KEY (run_id, h3)
);

-- Recorded, displayed on every hex, and used in the disparity analysis of
-- section 13.6. Never an input to the score. Section 14 argues at length that
-- keeping race out of the arithmetic is what makes the disparity finding an
-- independent result rather than a built-in one, so these three columns must
-- not appear in any indicator or component query.
COMMENT ON COLUMN hex_demographics.black_pct IS 'Displayed and analysed, never scored. Section 14.';
COMMENT ON COLUMN hex_demographics.hispanic_pct IS 'Displayed and analysed, never scored. Section 14.';
COMMENT ON COLUMN hex_demographics.people_of_color_pct IS
    'Displayed and analysed, never scored. Section 14.';

COMMENT ON COLUMN hex_demographics.max_coefficient_variation IS
    'Worst coefficient of variation among the estimates behind this hex. Above 0.30 the '
    'estimate is still used and c_spatial falls instead.';

CREATE INDEX hex_demographics_h3_idx ON hex_demographics (h3);
