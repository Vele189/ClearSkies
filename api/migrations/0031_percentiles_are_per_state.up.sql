-- 0031: a percentile belongs to a state, not to the database
--
-- Methodology section 9 converts every indicator to a percentile "against the
-- rest of Louisiana", and section 15 repeats that the result is not comparable
-- across states because it is the most common way a score like this is
-- misread. The schema has never encoded that. `indicator_distribution` is keyed
-- `(run_id, indicator_id)` and `hex_score.percentile` is a single column, so
-- "the scored universe" and "Louisiana" have been the same set by accident of
-- there being one state.
--
-- **Loading a second state without this migration silently rewrites every
-- Louisiana score.** Nothing errors. The denominators simply become two-state
-- denominators, every stored percentile shifts, and the pre-registered
-- criterion in section 13.2 -- eight of ten documented sites in the *statewide*
-- top decile -- starts measuring something it was not registered against.
-- Appendix A would still print a pass or a fail and the number would mean
-- nothing. That is the failure this migration exists to prevent, and it is why
-- it lands before any second state's rows do.
--
-- `scoring/burden/percentile.py` needs no new idea to support this. It already
-- says so: "`rank` takes the scored universe as a required argument rather than
-- trusting its callers to have filtered already: the denominator is the thing
-- this module exists to get right." The caller passes one state at a time; this
-- migration gives the stored output somewhere to say which state that was.

-- ---------------------------------------------------------------------------
-- 1. Which states are scored
--
-- One row per state whose hexes are ranked against each other. This is the
-- switch: a state with no row here is not scored, and `PILOT_STATE` in the
-- environment stops being the thing that decides it. A single-valued
-- environment variable cannot express "Louisiana and West Virginia", and
-- scoring coverage is a property of the data in the database rather than of
-- the process that happens to be reading it.
--
-- `activated_at` is here because docs/validation/sites.yml keys its
-- out-of-state sites on `activate_when: "scoring coverage includes <ST>"`.
-- When that becomes a check rather than a sentence, this column is what it
-- reads, and the date a state was activated is what dates the validation
-- result that followed.
-- ---------------------------------------------------------------------------

CREATE TABLE scored_state (
    state_fips   char(2)     PRIMARY KEY CHECK (state_fips ~ '^[0-9]{2}$'),
    usps         char(2)     NOT NULL UNIQUE CHECK (usps ~ '^[A-Z]{2}$'),
    name         text        NOT NULL,
    activated_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE scored_state IS
    'States whose hexes are percentile-ranked against each other (section 9). '
    'Membership here is what "scoring coverage includes <ST>" means in '
    'docs/validation/sites.yml.';

INSERT INTO scored_state (state_fips, usps, name, activated_at)
VALUES ('22', 'LA', 'Louisiana', '2026-09-20T18:49:57Z');

-- ---------------------------------------------------------------------------
-- 2. The grid knows which state it is ranked in
--
-- `hex.state_fips` already exists and already carries the right value. What it
-- did not have was a reason to be trusted, so this adds one: a hex may only
-- belong to a state that is being scored.
--
-- `in_pilot_state` is renamed, not removed. It is not a duplicate of
-- `state_fips` and the two are not interchangeable. Every hex on dev-seed has
-- `state_fips = '22'`, including the 1,699 whose flag is false: section 6
-- builds the grid over the state's land area plus a buffer, and includes a
-- boundary hex only "if its centroid falls inside Louisiana". So `state_fips`
-- is which state's ranking this cell joins, and the flag is whether the cell's
-- centroid is actually inside that state's line. Both are load-bearing and
-- "pilot" is simply the wrong word for either once there is more than one.
-- ---------------------------------------------------------------------------

ALTER TABLE hex RENAME COLUMN in_pilot_state TO centroid_in_state;

COMMENT ON COLUMN hex.centroid_in_state IS
    'Whether this cell''s centroid falls inside state_fips'' boundary (section 6). '
    'Cells in the interaction-radius buffer are stored with the flag false and are '
    'excluded from percentile denominators. Renamed from in_pilot_state in 0031.';

ALTER TABLE hex
    ADD CONSTRAINT hex_state_is_scored
    FOREIGN KEY (state_fips) REFERENCES scored_state(state_fips);

-- The multi-state successor to `hex_pilot_idx`, which 0030 left dropped. The
-- scoring run walks one state's scored cells at a time, so the state leads.
CREATE INDEX hex_scored_by_state_idx ON hex (state_fips, h3) WHERE centroid_in_state;

-- ---------------------------------------------------------------------------
-- 3. The distribution a percentile was computed against
--
-- The whole point. `breakpoints`, `n_hexes` and `n_zero` describe one state's
-- ranking, and until now there was one row per indicator per run with nowhere
-- to say whose. Backfilling to '22' is exact rather than an assumption: every
-- row in this table was computed over Louisiana, because Louisiana is all there
-- has ever been.
-- ---------------------------------------------------------------------------

ALTER TABLE indicator_distribution ADD COLUMN state_fips char(2);

UPDATE indicator_distribution SET state_fips = '22';

ALTER TABLE indicator_distribution
    ALTER COLUMN state_fips SET NOT NULL,
    ADD CONSTRAINT indicator_distribution_state_is_scored
        FOREIGN KEY (state_fips) REFERENCES scored_state(state_fips),
    DROP CONSTRAINT indicator_distribution_pkey,
    ADD PRIMARY KEY (run_id, state_fips, indicator_id);

-- ---------------------------------------------------------------------------
-- 4. "Outside the pilot state" becomes "outside every scored state"
--
-- Same meaning, and the old wording stops being true the moment a second state
-- is scored: a hex in West Virginia is outside the pilot state and is not
-- unscored for that reason.
-- ---------------------------------------------------------------------------

UPDATE hex_score
   SET no_score_reason = 'outside_scored_states'
 WHERE no_score_reason = 'outside_pilot_state';

ALTER TABLE hex_score DROP CONSTRAINT hex_score_no_score_reason_check;

ALTER TABLE hex_score
    ADD CONSTRAINT hex_score_no_score_reason_check
    CHECK (no_score_reason IN (
        'low_population',
        'insufficient_pollution_data',
        'insufficient_population_data',
        'outside_scored_states'
    ));
