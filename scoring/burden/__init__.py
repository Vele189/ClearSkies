"""ClearSkies scoring.

The burden score, built in the order docs/methodology.md builds it: normalization
to statewide percentiles (section 9), the two components, and their product
(section 10). Nothing in here decides what an indicator is or what it weighs;
that is declared once in `api/app/indicators.py` and locked to section 8.
"""
