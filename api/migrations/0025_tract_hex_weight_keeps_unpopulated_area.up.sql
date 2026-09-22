-- 0025: tract_hex_weight keeps the area that holds no one
--
-- Migration 0003 required pop_weight > 0, and c5c9ac0 stopped emitting the
-- rows that broke it: overlaps of a populated tract holding none of its 2020
-- block population, which is any tract spanning housing and marsh. Section 7
-- multiplies such a row by zero in both of its formulas, so for the score that
-- was right, and it stays right: the ETL still keeps these rows out of every
-- weight the section 7 formulas read.
--
-- What it broke was section 13.5. The areal counterpart spreads a tract's
-- people over its whole area, and with those cells gone a tract's area_weight
-- no longer sums to 1, so the counterpart refuses the tract rather than
-- quietly redistributing its population over part of it. Once the block layer
-- is discarded this table is the only place that geometry survives, so the
-- rows come back, with a pop_weight of exactly 0.
--
-- The second check keeps a 0 weight meaning one thing. A row may carry no
-- share of its tract's people only if it carries none of them either; a zero
-- weight over a nonzero population would be an arithmetic fault, not a marsh.

ALTER TABLE tract_hex_weight DROP CONSTRAINT tract_hex_weight_pop_weight_check;

ALTER TABLE tract_hex_weight
    ADD CONSTRAINT tract_hex_weight_pop_weight_check
        CHECK (pop_weight >= 0 AND pop_weight <= 1),
    ADD CONSTRAINT tract_hex_weight_zero_weight_holds_no_one
        CHECK (pop_weight > 0 OR population = 0);

COMMENT ON COLUMN tract_hex_weight.pop_weight IS
    'Share of the tract''s population falling in this hex, the weight for extensive values. '
    '0 marks area of a populated tract holding none of its block population: never read '
    'by section 7, kept for the section 13.5 areal counterpart.';
