-- Reverses 0032: the District is no longer scored.
--
-- This will fail while any hex row carries state_fips = '11', and that is the
-- foreign key 0031 added doing its job rather than an obstacle. A state cannot
-- stop being scored while its cells are still ranked against each other: the
-- percentiles in `hex_score` were computed over that state's denominator, and
-- leaving them behind with nothing to say whose they are is the exact
-- confusion sections 9 and 15 exist to prevent.
--
-- So reverting this means dropping the District's grid first, on purpose.

DELETE FROM scored_state WHERE state_fips = '11';
