-- Restoring the key will fail if any monitor outside the pilot-state grid has
-- been loaded since, which is the point of having dropped it. Clear those rows
-- first, knowing that doing so discards the out-of-state monitors section 5
-- asks for.

ALTER TABLE monitor
    ADD CONSTRAINT monitor_h3_fkey FOREIGN KEY (h3) REFERENCES hex(h3);

COMMENT ON COLUMN monitor.h3 IS NULL;
