-- Reverses 0027: the four-argument function goes, the three-argument one comes
-- back with its unbounded quarter count, exactly as 0014 defined it.

DROP FUNCTION facilities_near_hex(h3_cell, double precision, date, date);

CREATE FUNCTION facilities_near_hex(
        cell h3_cell,
        radius_m double precision DEFAULT 10000,
        actions_since date DEFAULT NULL
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

COMMENT ON FUNCTION facilities_near_hex(h3_cell, double precision, date) IS
    'The contributing facilities list behind GET /hex/{h3}, nearest first.';
