-- Revert 0032. Refuses while a snapshot is recorded as 'sems', because the
-- restored constraint would reject the rows that already exist.

DROP TABLE IF EXISTS cleanup_site;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM source_snapshot WHERE source = 'sems') THEN
        RAISE EXCEPTION 'source_snapshot holds sems rows; delete them before reverting 0032';
    END IF;
END
$$;

ALTER TABLE source_snapshot DROP CONSTRAINT IF EXISTS source_snapshot_source_check;
ALTER TABLE source_snapshot ADD CONSTRAINT source_snapshot_source_check CHECK (source IN (
    'echo', 'tri', 'airtoxscreen', 'openaq', 'acs', 'census_tract', 'census_block',
    'rsei', 'places'
));
