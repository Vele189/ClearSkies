-- Reverts 0022_release_toxicity_coverage.
--
-- The view holds no data of its own, so unwinding it loses nothing. What it
-- does lose is the single definition of a facility's toxicity-weighted release
-- total: anything still computing E3 after this runs is computing it from its
-- own join.

DROP VIEW IF EXISTS facility_release_toxicity;
