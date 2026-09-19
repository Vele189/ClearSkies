-- Reverts 0017_low_confidence_index.
--
-- Only an index. The confidence columns it reads belong to 0009 and stay.

DROP INDEX IF EXISTS hex_score_low_confidence_idx;
