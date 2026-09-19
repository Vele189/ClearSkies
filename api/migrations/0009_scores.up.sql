-- 0009: indicator values, run distributions, and the scores themselves
--
-- Everything here is keyed by run. Percentiles are computed once per run over
-- the scored hexes of that run (section 9), so a value only means anything
-- beside the distribution it was ranked against, and indicator_distribution is
-- that distribution kept.

CREATE TABLE hex_indicator (
    run_id       bigint  NOT NULL REFERENCES pipeline_run(run_id) ON DELETE CASCADE,
    h3           h3_cell NOT NULL REFERENCES hex(h3) ON DELETE CASCADE,
    indicator_id text    NOT NULL CHECK (indicator_id ~ '^[EFSP][0-9]$'),
    value        numeric,
    percentile   numeric CHECK (percentile > 0 AND percentile < 100),
    observed     boolean NOT NULL,
    PRIMARY KEY (run_id, h3, indicator_id),
    -- Zero is an observation and NULL is an absence; section 11 is emphatic
    -- that the pipeline never coerces one into the other. This constraint only
    -- forbids the incoherent direction, an unobserved indicator that somehow
    -- carries a value.
    CONSTRAINT hex_indicator_absent_has_no_value CHECK (observed OR value IS NULL)
);

COMMENT ON TABLE hex_indicator IS
    'One row per indicator per hex per run, including the ones that were absent. A row '
    'with observed = false is what the detail panel renders as a dropped indicator, so '
    'a user can always see which of the fifteen actually produced the score.';

-- Percentiles use the Hazen convention, 100 * (r - 0.5) / n, which is bounded
-- strictly inside 0 and 100. That is not a rounding detail: the score
-- multiplies components together, so an exact zero would annihilate a hex's
-- whole pollution burden on the strength of one indicator at the state minimum.
COMMENT ON COLUMN hex_indicator.percentile IS
    'Statewide percentile, Hazen convention, strictly between 0 and 100. Section 9.';

CREATE INDEX hex_indicator_h3_idx ON hex_indicator (h3);

CREATE TABLE indicator_distribution (
    run_id       bigint   NOT NULL REFERENCES pipeline_run(run_id) ON DELETE CASCADE,
    indicator_id text     NOT NULL CHECK (indicator_id ~ '^[EFSP][0-9]$'),
    n_hexes      integer  NOT NULL CHECK (n_hexes >= 0),
    n_zero       integer  NOT NULL CHECK (n_zero >= 0),
    min_value    numeric,
    max_value    numeric,
    breakpoints  numeric[] NOT NULL,
    vintage_end  date     NOT NULL,
    PRIMARY KEY (run_id, indicator_id),
    CONSTRAINT indicator_distribution_zero_block_fits CHECK (n_zero <= n_hexes)
);

COMMENT ON COLUMN indicator_distribution.n_hexes IS
    'Hexes holding a valid value for this indicator, the n_k denominator of section 9.';
COMMENT ON COLUMN indicator_distribution.n_zero IS
    'Hexes whose value is exactly zero. For E3 and F1 through F4 this is most of the '
    'state, and it is published because below that share the indicator carries no '
    'information: a hex with no facility within 10 km is not cleaner than 40% of Louisiana.';
COMMENT ON COLUMN indicator_distribution.breakpoints IS
    'The run''s percentile breakpoints, so a stored score can be re-derived without '
    'reloading the source data it was computed from.';

CREATE TABLE hex_score (
    run_id                     bigint  NOT NULL REFERENCES pipeline_run(run_id) ON DELETE CASCADE,
    h3                         h3_cell NOT NULL REFERENCES hex(h3) ON DELETE CASCADE,
    score                      numeric CHECK (score > 0 AND score <= 100),
    percentile                 numeric CHECK (percentile > 0 AND percentile < 100),
    pollution_burden           numeric CHECK (pollution_burden BETWEEN 0 AND 10),
    population_characteristics numeric CHECK (population_characteristics BETWEEN 0 AND 10),
    exposures_mean             numeric,
    env_effects_mean           numeric,
    sensitive_mean             numeric,
    socioeconomic_mean         numeric,
    confidence                 numeric CHECK (confidence > 0 AND confidence <= 1),
    confidence_band            text CHECK (confidence_band IN (
                                   'high', 'moderate', 'low', 'insufficient'
                               )),
    c_coverage                 numeric CHECK (c_coverage BETWEEN 0 AND 1),
    c_recency                  numeric CHECK (c_recency BETWEEN 0 AND 1),
    c_spatial                  numeric CHECK (c_spatial BETWEEN 0 AND 1),
    c_monitor                  numeric CHECK (c_monitor BETWEEN 0 AND 1),
    nearest_monitor_km         numeric CHECK (nearest_monitor_km >= 0),
    no_score_reason            text CHECK (no_score_reason IN (
                                   'low_population',
                                   'insufficient_pollution_data',
                                   'insufficient_population_data',
                                   'outside_pilot_state'
                               )),
    PRIMARY KEY (run_id, h3),
    -- A hex is scored or it carries a reason it is not. Both or neither would
    -- leave the map with a colour it cannot explain.
    CONSTRAINT hex_score_scored_xor_reason
        CHECK ((score IS NULL) = (no_score_reason IS NOT NULL))
);

COMMENT ON TABLE hex_score IS
    'One row per hex per run, including unscored hexes. GET /health counts this table to '
    'decide whether the pipeline has run at all.';
COMMENT ON COLUMN hex_score.score IS
    'Pollution burden times population characteristics, range (0, 100]. Multiplicative, '
    'so a hex at the 60th percentile on both outscores one at the 95th and the 20th.';
COMMENT ON COLUMN hex_score.confidence IS
    'Weighted geometric mean of the four c_ terms, each floored at 0.05. How well '
    'supported the score is, never how severe the burden is; the interface must not '
    'conflate the two.';
COMMENT ON COLUMN hex_score.confidence_band IS
    'A hex in the insufficient band is excluded from validation statistics and cannot '
    'produce an advocacy document at all. Section 12.';

-- The validation protocol asks whether a named site sits in the statewide top
-- decile, which is a percentile lookup over one run.
CREATE INDEX hex_score_run_percentile_idx ON hex_score (run_id, percentile DESC);
CREATE INDEX hex_score_h3_idx ON hex_score (h3);

-- The contributing facilities on the detail panel are derived at read time from
-- facility and hex geometry through the PostGIS index, not stored. They are a
-- distance query against a few thousand rows, and materialising them per hex
-- per run would be the largest table in the database by a wide margin.
