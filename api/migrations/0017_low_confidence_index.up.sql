-- 0017: find the hexes a run does not trust, in one query (CS-205)
--
-- Section 12 gives every scored hex a confidence value and a band, and treats
-- the bottom two bands as operationally different from the top two: a low hex
-- renders hatched and leads its panel with the caveat, and an insufficient one
-- is hidden behind a toggle, kept out of validation statistics, and barred from
-- producing an advocacy document.
--
-- QA therefore asks one question of every run, and asks it before the run is
-- published rather than after: which hexes came out in those two bands, and
-- how bad are they. Without an index that is a scan of every hex in the state
-- to find what should be a small minority of them.
--
--     SELECT h3, confidence, confidence_band, c_coverage, c_recency,
--            c_spatial, c_monitor, nearest_monitor_km
--       FROM hex_score
--      WHERE run_id = $1
--        AND confidence_band IN ('low', 'insufficient')
--      ORDER BY confidence;
--
-- The index is partial, on exactly that predicate, so it holds only the rows
-- the question is about and stays small even though the table does not. It
-- carries `confidence` as its second key so the ordering comes out of the index
-- rather than out of a sort.
--
-- No new column. `confidence` and `confidence_band` have been on hex_score
-- since 0009; what was missing was a way to ask about them that does not get
-- slower every time the grid grows.

CREATE INDEX hex_score_low_confidence_idx
    ON hex_score (run_id, confidence)
    WHERE confidence_band IN ('low', 'insufficient');

COMMENT ON INDEX hex_score_low_confidence_idx IS
    'The QA sweep of section 12: every hex of a run in the low or insufficient band, '
    'worst first. Partial, because those bands should be the minority of any run that '
    'is fit to publish, and an index that grows with the healthy rows would defeat '
    'the point.';
