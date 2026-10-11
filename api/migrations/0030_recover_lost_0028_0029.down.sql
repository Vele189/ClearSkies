-- Reverses 0030: the recovered table goes and the index decision goes back to
-- what the lost 0029 left behind.
--
-- It does not restore the two orphan ledger rows. 0030 did not delete them --
-- `app.migrate forget` did, before 0030 could run at all -- so re-inserting
-- them here would not be a reverse of this migration, and it would put the
-- database straight back into the state where no migration can be applied.
-- Their checksums, if they are ever wanted, are in docs/expansion.md section
-- 2.2.

DROP INDEX IF EXISTS statute_chunk_embedding_idx;

CREATE INDEX IF NOT EXISTS hex_pilot_idx ON hex (h3) WHERE in_pilot_state;

-- 0030 did not create these rows. It re-declared a table that already held
-- 1,367 of them on dev-seed, which is why the up migration uses
-- CREATE TABLE IF NOT EXISTS and left them untouched. Dropping the table on the
-- way back down would therefore delete data this migration never put there and
-- cannot put back: the pull that produced it is the lost 0028's, and nobody has
-- that script.
--
-- So the revert refuses while the table has rows, the same way 0031's refuses
-- while more than one state is scored. Emptying it first is a decision someone
-- makes on purpose; it is not a side effect of reverting a migration.
DO $$
DECLARE n bigint;
BEGIN
    IF to_regclass('public.tract_health') IS NOT NULL THEN
        EXECUTE 'SELECT count(*) FROM tract_health' INTO n;
        IF n > 0 THEN
            RAISE EXCEPTION
                'cannot revert 0030: tract_health holds % rows that 0030 did not '
                'create and cannot restore. Export or delete them first, on purpose.', n;
        END IF;
    END IF;
END $$;

DROP TABLE IF EXISTS tract_health;
