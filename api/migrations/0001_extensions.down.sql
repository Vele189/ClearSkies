-- Reverts 0001_extensions.
--
-- The extensions themselves are left installed. Dropping postgis would cascade
-- through every geometry column in the database, which is a far larger action
-- than undoing this migration, and a local container is cheaper to recreate
-- than to repair. Removing them is `docker compose down -v`.

DROP DOMAIN IF EXISTS h3_cell;
DROP VIEW IF EXISTS clearskies_extensions;
