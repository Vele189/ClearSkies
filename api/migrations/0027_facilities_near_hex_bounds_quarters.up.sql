-- 0027: the drill-down counts the same twelve quarters the score does
--
-- AUD-18. `facilities_near_hex` counted every non-compliant quarter
-- `facility_compliance_quarter` held, over any window, while F2 counts the
-- twelve quarters ending with the one containing the run's `as_of`
-- (scoring/burden/inputs.py, COMPLIANCE_QUARTERS = 12, methodology §8.2).
--
-- The two agreed only while the table held exactly twelve quarters per
-- facility. AUD-05 bounded the score's window explicitly; nothing bounded the
-- panel's. As soon as ECHO's history runs deeper than twelve quarters the
-- panel says a facility was out of compliance for eighteen quarters next to a
-- score that counted twelve, and a reader checking the arithmetic finds it
-- does not check out. That is the one thing the detail panel exists not to do.
--
-- `quarters_since` is a parameter for the same reason `actions_since` is: a
-- run scoring last night's data asks about that night's twelve quarters, not
-- about the twelve ending whenever somebody opens the panel. NULL keeps the
-- old default of "twelve quarters back from today", which is right for a
-- reader browsing the current promoted run.
--
-- Quarters are stored as the date of the quarter's first day, so the bound is
-- date_trunc('quarter', ...) minus eleven quarters: eleven and not twelve,
-- because the window is inclusive of the quarter containing the reference
-- date. Expressed in months, because Postgres has no 'quarter' interval
-- unit -- date_trunc takes the field name, interval input does not.

DROP FUNCTION facilities_near_hex(h3_cell, double precision, date);

CREATE FUNCTION facilities_near_hex(
        cell h3_cell,
        radius_m double precision DEFAULT 10000,
        actions_since date DEFAULT NULL,
        quarters_since date DEFAULT NULL
    )
    RETURNS SETOF hex_facility_detail
    LANGUAGE sql
    STABLE
    PARALLEL SAFE
    AS '
        SELECT f.facility_id,
               f.registry_id,
               f.name,
               link.distance_m,
               link.decay_weight,
               link.is_containing,
               f.is_major_source,
               f.has_title_v,
               f.is_rcra_lqg,
               f.is_rcra_tsdf,
               f.geocode_quality,
               f.echo_url,
               quarters.noncompliant,
               actions.formal,
               actions.penalties
          FROM hex_facility_links(cell, radius_m) AS link
          JOIN facility f ON f.facility_id = link.facility_id
          LEFT JOIN LATERAL (
              SELECT count(*)::integer AS noncompliant
                FROM facility_compliance_quarter c
               WHERE c.facility_id = f.facility_id
                 AND c.status IN (''violation'', ''high_priority_violation'')
                 AND c.quarter >= coalesce(
                         date_trunc(''quarter'', quarters_since)::date,
                         (date_trunc(''quarter'', current_date)
                              - interval ''33 months'')::date
                     )
          ) AS quarters ON true
          LEFT JOIN LATERAL (
              SELECT count(*)::integer AS formal,
                     coalesce(sum(a.penalty_usd), 0) AS penalties
                FROM enforcement_action a
               WHERE a.facility_id = f.facility_id
                 AND a.is_formal
                 AND a.settled_on >= coalesce(
                         actions_since, (current_date - interval ''5 years'')::date
                     )
          ) AS actions ON true
         ORDER BY link.distance_m
    ';

COMMENT ON FUNCTION facilities_near_hex(h3_cell, double precision, date, date) IS
    'The contributing facilities list behind GET /hex/{h3}, nearest first. '
    'Counts the same twelve quarters and five years the score does, so the '
    'panel and F2/F3 cannot disagree.';
