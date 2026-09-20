-- Reverts 0014_facility_hex_assignment.
--
-- Down migrations exist so a review branch can be unwound locally. Production
-- rolls forward: to undo a shipped migration, write the next one.
--
-- One thing to know before running this against a database that holds data.
-- Restoring the foreign key from facility.h3 to hex.h3 will fail if any facility
-- sits outside the pilot-state grid, which is exactly the case 0014 exists to
-- allow. That is not a defect in this file: the old key and out-of-state
-- contributors cannot both be true, and unwinding means going back to the schema
-- that forbade them. Reload the facilities afterwards.

DROP FUNCTION facilities_near_hex(h3_cell, double precision, date);
DROP TYPE hex_facility_detail;

DROP FUNCTION hex_facility_links_all(double precision);
DROP FUNCTION hex_facility_links(h3_cell, double precision);
DROP TYPE hex_facility_link;

DROP FUNCTION facility_decay_weight(double precision);

DROP INDEX hex_centroid_geography_idx;
DROP INDEX facility_geography_idx;

ALTER TABLE facility
    DROP CONSTRAINT facility_quality_matches_status,
    DROP CONSTRAINT facility_geocode_quality_check,
    DROP COLUMN reported_longitude,
    DROP COLUMN reported_latitude,
    DROP COLUMN geocode_accuracy_m,
    DROP COLUMN geocode_quality;

ALTER TABLE facility DROP CONSTRAINT facility_geom_matches_status;
ALTER TABLE facility ADD CONSTRAINT facility_geom_matches_status
    CHECK ((geom IS NULL) = (coordinate_status = 'missing'));

ALTER TABLE facility DROP CONSTRAINT facility_coordinate_status_check;
ALTER TABLE facility ADD CONSTRAINT facility_coordinate_status_check
    CHECK (coordinate_status IN ('ok', 'missing', 'outside_state', 'zip_mismatch'));

COMMENT ON COLUMN facility.h3 IS NULL;

ALTER TABLE facility ADD CONSTRAINT facility_h3_fkey FOREIGN KEY (h3) REFERENCES hex(h3);
