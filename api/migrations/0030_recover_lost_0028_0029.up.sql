-- 0030: recover the schema that two lost migrations left behind
--
-- `schema_migration` records 0028 `tract_health` and 0029
-- `drop_low_value_indexes` as applied, on 2026-10-01, with checksums. Their
-- files are in no commit on any ref in this repository, and not in a dangling
-- object either. They were applied through the runner from a working tree that
-- was never committed, and that tree is gone.
--
-- `drift()` has been reporting this the whole time -- "0028 is recorded as
-- applied but its file is gone" -- so `make migrate-verify` fails today. The
-- check worked; nobody ran it. docs/database.md section 3 is the rule this
-- broke: "A schema that exists because somebody ran a statement once cannot be
-- rebuilt, and this project's whole claim is that its output is reproducible
-- from public inputs."
--
-- The checksum is `sha256(up file)`, so a reconstruction cannot be proved
-- identical unless it is byte-exact, which guessing will not achieve. This
-- migration therefore does not pretend to be those files. It restates their
-- *effects* from the live schema, so that a database built from this directory
-- and the database that exists converge.
--
-- **The ledger is repaired before this migration, not by it.** `up` refuses to
-- apply anything while `drift` reports a problem, and "recorded as applied but
-- its file is gone" is one, so the orphan rows block every migration including
-- this one. That is a loop a migration cannot break out of. Run the ledger
-- repair first:
--
--     python -m app.migrate forget 0028 0029
--
-- `forget` will not touch a version that still has a file, so it cannot be
-- used to hide a real migration. docs/expansion.md section 2.2 is the record of
-- why it was needed here.
--
-- **Every statement is guarded.** This has to be a no-op against dev-seed,
-- which already has 0028 and 0029 applied, and effective against an empty
-- database replaying the set from 0001. That is the one case where `IF EXISTS`
-- earns its place here rather than hiding a mistake.
--
-- Numbered 0030 and not 0028: `out_of_order()` rejects a pending migration
-- below the highest applied one, and 0029 is applied. `discover()` does not
-- require contiguity, so the gap is legal and is the record of what happened.

-- ---------------------------------------------------------------------------
-- 0028's effect: tract_health
--
-- Reconstructed column for column from the live table. Three CDC-PLACES
-- measures with their confidence intervals, keyed by tract and release year.
--
-- **Nothing reads it.** No module under api/, etl/, scoring/, assistant/ or
-- web/ mentions it, and it holds 1,367 rows. methodology.md section 3 names
-- health outcomes as the project's largest gap and section 16 records it as out
-- of scope for v0, so wiring these into the score is a methodology revision,
-- not a code change. It is recovered rather than dropped because the rows are
-- real and the work was done; docs/expansion.md section 6 is where the decision
-- to use it or drop it belongs.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS tract_health (
    tract_geoid    char(11)  NOT NULL REFERENCES census_tract(geoid) ON DELETE CASCADE,
    release_year   smallint  NOT NULL,
    asthma_pct     numeric   CHECK (asthma_pct     BETWEEN 0 AND 100),
    asthma_ci_low  numeric   CHECK (asthma_ci_low  BETWEEN 0 AND 100),
    asthma_ci_high numeric   CHECK (asthma_ci_high BETWEEN 0 AND 100),
    copd_pct       numeric   CHECK (copd_pct       BETWEEN 0 AND 100),
    copd_ci_low    numeric   CHECK (copd_ci_low    BETWEEN 0 AND 100),
    copd_ci_high   numeric   CHECK (copd_ci_high   BETWEEN 0 AND 100),
    chd_pct        numeric   CHECK (chd_pct        BETWEEN 0 AND 100),
    chd_ci_low     numeric   CHECK (chd_ci_low     BETWEEN 0 AND 100),
    chd_ci_high    numeric   CHECK (chd_ci_high    BETWEEN 0 AND 100),
    snapshot_id    bigint    NOT NULL REFERENCES source_snapshot(snapshot_id),
    PRIMARY KEY (tract_geoid, release_year)
);

COMMENT ON TABLE tract_health IS
    'CDC PLACES tract measures, recovered in 0030 from a lost migration. Read by '
    'nothing: section 16 keeps health outcomes out of the v0 score, so using these '
    'is a methodology revision. See docs/expansion.md section 6.';

-- ---------------------------------------------------------------------------
-- 0029's effect: two indexes, and only one of them stays dropped
--
-- 0029 was called `drop_low_value_indexes`. Comparing the `CREATE INDEX`
-- statements in this directory against `pg_indexes` on dev-seed shows it
-- dropped exactly two.
--
-- `hex_pilot_idx` stays dropped. It was `ON hex (h3) WHERE in_pilot_state`, a
-- partial index on the single-state flag that 0031 removes outright, so
-- restoring it would be restoring an index on a column that is about to go.
--
-- `statute_chunk_embedding_idx` is restored, because dropping it contradicted a
-- decision this repository had already written down. 0010 chose it
-- deliberately: "HNSW rather than IVFFlat because the corpus is small and
-- static, so build time is irrelevant and recall is not." Without it every
-- retrieval is a sequential scan over 2,841 chunks of 1536-dimensional vectors,
-- which is survivable at this size and is still not what the assistant was
-- built against. A documented decision is not reversed by an undocumented
-- migration; if it should be reversed, that argument goes in 0010's successor
-- with its reasoning attached.
-- ---------------------------------------------------------------------------

DROP INDEX IF EXISTS hex_pilot_idx;

CREATE INDEX IF NOT EXISTS statute_chunk_embedding_idx
    ON statute_chunk USING hnsw (embedding vector_cosine_ops);

-- ---------------------------------------------------------------------------
-- What is not here
--
-- No `DELETE FROM schema_migration`. The orphan rows are gone before this file
-- runs, for the reason at the top, and a migration that edited the ledger it is
-- recorded in would be a migration that cannot be reasoned about.
--
-- 0028 and 0029 are left as spent numbers rather than reused. `out_of_order()`
-- rejects a pending migration below the highest applied one, and a future
-- migration carrying either number would make this history unreadable. The gap
-- in this directory is the record; `tests/test_migrations.py` names both
-- numbers so that a third gap still fails.
-- ---------------------------------------------------------------------------
