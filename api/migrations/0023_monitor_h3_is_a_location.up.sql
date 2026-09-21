-- 0023: monitor.h3 is a location, not a membership claim
--
-- The same change migration 0014 made to facility.h3, for the same reason and
-- on the same authority, applied to the one table that was left holding the
-- old key.
--
-- The foreign key from monitor.h3 to hex.h3 said a monitor must sit in a cell
-- the pilot-state grid contains. Section 5 says the opposite: a source close
-- enough to affect a Louisiana hexagon counts, whichever side of the line it
-- sits on. A PM2.5 monitor in Bay St. Louis measures air that blows over
-- St. Tammany, and the OpenAQ adapter pulls it deliberately for that reason --
-- it queries the pilot state's bounding box widened by the interaction radius,
-- not the state boundary.
--
-- Under the old key such a monitor could not be stored at all. The CS-112 load
-- surfaced it as a foreign key violation on cell 884455465bfffff, which is at
-- 30.39N 89.05W, in Mississippi.
--
-- So h3 records which cell the monitor is in, full stop, and joins from
-- monitor to hex are outer joins. Whether a monitor reaches a given hexagon is
-- the interpolation radius's question, answered on distance, not a foreign
-- key's.
--
-- hex_air_quality.h3 keeps its key, and should: that table holds a fact *about*
-- a hexagon and is meaningless without one. The distinction is the same one
-- 0014 drew between a facility's location and a hexagon's score.

ALTER TABLE monitor DROP CONSTRAINT monitor_h3_fkey;

COMMENT ON COLUMN monitor.h3 IS
    'Resolution 8 cell containing the monitor, computed in Python with h3-py. Not a '
    'foreign key: a monitor outside the pilot state still has a cell, and section 5 '
    'requires it to keep contributing. Join to hex with an outer join.';
