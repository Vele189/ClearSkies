-- Reverts 0012_source_pulls.
--
-- The two child tables go first. Both reference source_pull, and dropping the
-- parent while a child stands would leave the schema describing pulls that no
-- longer exist.

DROP TABLE IF EXISTS source_pull_artifact;
DROP TABLE IF EXISTS source_pull_gap;
DROP TABLE IF EXISTS source_pull;
