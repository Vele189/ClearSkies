-- Reverts 0021_draft_cache.
--
-- Drops the cache and the usage log. Losing the cache costs money to rebuild
-- and nothing else; losing the usage log loses the record of what has already
-- been spent, which is why production rolls forward.

DROP TABLE IF EXISTS llm_usage;
DROP TABLE IF EXISTS draft;
