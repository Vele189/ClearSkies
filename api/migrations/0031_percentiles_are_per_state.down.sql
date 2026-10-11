-- Reverses 0031. Safe only while exactly one state is scored, which is the
-- state this migration found the database in and the only state it can return
-- it to: the old primary key cannot hold two states' distributions for one
-- run, so the revert refuses rather than discarding rows it cannot key.

DO $$
DECLARE n integer;
BEGIN
    SELECT count(*) INTO n FROM scored_state;
    IF n > 1 THEN
        RAISE EXCEPTION
            'cannot revert 0031: % states are scored, and the pre-0031 primary '
            'key (run_id, indicator_id) holds one. Deactivate the others first.', n;
    END IF;
END $$;

ALTER TABLE hex_score DROP CONSTRAINT hex_score_no_score_reason_check;

ALTER TABLE hex_score
    ADD CONSTRAINT hex_score_no_score_reason_check
    CHECK (no_score_reason IN (
        'low_population',
        'insufficient_pollution_data',
        'insufficient_population_data',
        'outside_pilot_state'
    ));

UPDATE hex_score
   SET no_score_reason = 'outside_pilot_state'
 WHERE no_score_reason = 'outside_scored_states';

ALTER TABLE indicator_distribution
    DROP CONSTRAINT indicator_distribution_pkey,
    DROP CONSTRAINT indicator_distribution_state_is_scored,
    DROP COLUMN state_fips,
    ADD PRIMARY KEY (run_id, indicator_id);

DROP INDEX IF EXISTS hex_scored_by_state_idx;

ALTER TABLE hex DROP CONSTRAINT hex_state_is_scored;

ALTER TABLE hex RENAME COLUMN centroid_in_state TO in_pilot_state;

DROP TABLE scored_state;
