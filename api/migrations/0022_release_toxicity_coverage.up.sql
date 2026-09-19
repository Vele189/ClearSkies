-- 0022: the toxicity-weighted release total, and how much of it is actually weighted
--
-- Migration 0005 created the two halves of the E3 formula in methodology
-- section 8.1 and deliberately left them unjoined:
--
--     E3(h) = sum_f [ sum_c w_c * m_{f,c} ] / max(d_{h,f}, 250 m)^2
--
-- `tri_release.air_lb` is m_{f,c} and `chemical_toxicity_weight.rsei_weight` is
-- w_c. This migration writes the inner sum once, as a view, so that the scoring
-- run and the drill-down panel cannot drift into computing a facility's toxic
-- release burden two different ways. It is the same argument 0014 makes for
-- `hex_facility_links`: a panel that showed a number the score did not use is
-- the kind of discrepancy nobody notices until somebody has to defend it.
--
-- No table, and no new column on `tri_release`. The view is cheap over a few
-- thousand rows, and materialising it would mean a fact that goes stale the
-- moment either half is reloaded. It also means a new RSEI edition stays a data
-- load rather than a schema change, which is the property 0005 set out to keep.
--
-- ---- why a coverage share and not just a total --------------------------
--
-- RSEI publishes an inhalation toxicity weight for 461 of the 823 chemicals and
-- categories on the TRI list. A chemical it has no weight for is excluded from
-- E3 rather than scored as harmless: there is no weight row, so the join below
-- finds nothing to multiply and contributes nothing. That is section 11's
-- missing-data rule applied to a weight instead of to a measurement, and it is
-- correct, but on its own it is invisible. A facility releasing a million pounds
-- of an unweighted chemical and a facility releasing nothing both arrive at the
-- scoring step with a toxicity-weighted total of zero.
--
-- So the view reports the share of each facility's reported air poundage that
-- carries a weight alongside the weighted total. Against Louisiana's loaded 2024
-- releases the state-wide share is 99.81%, which is reassuring and also exactly
-- why the per-facility number is the one worth having: two of the 373 facilities
-- have no weighted poundage at all, and six are below half. Those eight are
-- invisible in the state-wide figure and are precisely the rows where a low E3
-- means "not measured" rather than "not much".
--
-- `weighted_air_lb_share` is NULL, not zero, for a facility that reported no air
-- poundage at all. A Form R reporting zero pounds is an observation, and the
-- share of nothing that carries a weight is undefined rather than 0%.

CREATE VIEW facility_release_toxicity AS
SELECT r.facility_id,
       r.reporting_year,
       -- The inner sum of the E3 formula. A LEFT JOIN and a plain sum are what
       -- make an unweighted chemical contribute nothing rather than zero: the
       -- product is NULL and sum() skips it. COALESCE here would be the bug this
       -- whole view exists to make visible.
       coalesce(sum(w.rsei_weight * r.air_lb), 0)                 AS toxicity_weighted_lb,
       sum(r.air_lb)                                              AS air_lb,
       -- The coalesces are the difference between "nothing carried a weight"
       -- and "there was nothing to weigh". sum() over no rows is NULL, so a
       -- facility whose every chemical is unweighted would otherwise report the
       -- same NULL share as a facility that released nothing at all, and it is
       -- the first of those two this view exists to make visible.
       coalesce(sum(r.air_lb) FILTER (WHERE w.cas_number IS NOT NULL), 0) AS weighted_air_lb,
       coalesce(sum(r.air_lb) FILTER (WHERE w.cas_number IS NULL), 0)     AS unweighted_air_lb,
       coalesce(sum(r.air_lb) FILTER (WHERE w.cas_number IS NOT NULL), 0)
           / NULLIF(sum(r.air_lb), 0)                             AS weighted_air_lb_share,
       count(*)                                                   AS chemicals,
       count(w.cas_number)                                        AS weighted_chemicals,
       count(*) - count(w.cas_number)                             AS unweighted_chemicals,
       -- Which RSEI edition scaled this facility's releases. Held on every
       -- weight row rather than only on the snapshot so that it survives the
       -- next pull, and reported here so a contribution computed last year can
       -- be told from the same contribution recomputed under a new edition. The
       -- count is a tripwire: one pull loads one edition, so anything above 1
       -- means two loads were mixed and the total spans both.
       min(w.source_edition)                                      AS rsei_edition,
       count(DISTINCT w.source_edition)                           AS rsei_editions
  FROM tri_release r
  LEFT JOIN chemical_toxicity_weight w ON w.cas_number = r.cas_number
 GROUP BY r.facility_id, r.reporting_year;

COMMENT ON VIEW facility_release_toxicity IS
    'Per facility and reporting year: the inner sum of the E3 formula (methodology '
    'section 8.1), and the share of reported air poundage that carried an RSEI '
    'weight. An unweighted chemical is excluded from the weighted total, never '
    'scored as zero; the share is what keeps that exclusion legible.';
