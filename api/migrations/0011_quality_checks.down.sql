-- Reverts 0011_quality_checks.
--
-- quality_check_result goes first: it references quality_run, and dropping the
-- parent while the child stands would leave the ledger describing a schema that
-- does not exist.

DROP TABLE IF EXISTS quality_check_result;
DROP TABLE IF EXISTS quality_run;
