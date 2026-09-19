-- Reverts 0011_hex_exposure.
--
-- Down migrations exist so a review branch can be unwound locally. Production
-- rolls forward: to undo a shipped migration, write the next one.

DROP TABLE IF EXISTS hex_exposure;
