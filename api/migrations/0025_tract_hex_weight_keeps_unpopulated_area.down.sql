-- The old check cannot be restored over the rows 0025 exists to allow, so they
-- are deleted first rather than left to make the ALTER fail. Section 7 never
-- reads them, so no score changes; what is lost is section 13.5's areal
-- counterpart, which refuses a crosswalk without them. Rebuilding the
-- crosswalk under 0025 brings them back, and it needs the 2020 block layer
-- loaded to do it.

DELETE FROM tract_hex_weight WHERE pop_weight = 0;

ALTER TABLE tract_hex_weight
    DROP CONSTRAINT tract_hex_weight_zero_weight_holds_no_one,
    DROP CONSTRAINT tract_hex_weight_pop_weight_check;

ALTER TABLE tract_hex_weight
    ADD CONSTRAINT tract_hex_weight_pop_weight_check
        CHECK (pop_weight > 0 AND pop_weight <= 1);

COMMENT ON COLUMN tract_hex_weight.pop_weight IS
    'Share of the tract''s population falling in this hex, the weight for extensive values.';
