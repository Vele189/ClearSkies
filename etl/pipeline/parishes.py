"""Louisiana parish names, by FIPS county code (CP-26).

`hex.parish_name` existed and nothing filled it. The grid assigns
`county_fips` from the tract layer, and the tract layer carries tract names --
"Census Tract 19.06" -- not parish names, so there was no name to assign. The
visible cost was the drill-down heading falling through to `state`, which is a
FIPS code, and every panel in Louisiana reading "22".

**Why a literal and not a download.** The county code is already resolved,
geometrically, by the grid. What is missing is only the label for it, and FIPS
codes and their names are fixed reference data: Louisiana has had these 64
parishes and these 64 codes since 1971, when the last one was created. A second
download is a second thing that can be unreachable on the night it is needed,
and a second source that can disagree with the code already assigned -- and a
parish name that disagrees with the parish geometry is worse than none, because
a drafted document would carry it.

The set is asserted against the tract layer in `tests/test_parishes.py`: these
are exactly the 64 codes the loaded pilot-state tracts use, no more and no
fewer, so a typo in a code cannot pass.

Names follow the Census Bureau's own spelling, which is what a reader
cross-checking against a federal record will see. That is why "De Soto" is two
words, "LaSalle" is one, and the saints are abbreviated.
"""

from __future__ import annotations

#: FIPS county code within Louisiana (state 22) to parish name, without the
#: word "Parish": the panel adds it, and a draft may need the bare name.
LOUISIANA_PARISHES: dict[str, str] = {
    "001": "Acadia",
    "003": "Allen",
    "005": "Ascension",
    "007": "Assumption",
    "009": "Avoyelles",
    "011": "Beauregard",
    "013": "Bienville",
    "015": "Bossier",
    "017": "Caddo",
    "019": "Calcasieu",
    "021": "Caldwell",
    "023": "Cameron",
    "025": "Catahoula",
    "027": "Claiborne",
    "029": "Concordia",
    "031": "De Soto",
    "033": "East Baton Rouge",
    "035": "East Carroll",
    "037": "East Feliciana",
    "039": "Evangeline",
    "041": "Franklin",
    "043": "Grant",
    "045": "Iberia",
    "047": "Iberville",
    "049": "Jackson",
    "051": "Jefferson",
    "053": "Jefferson Davis",
    "055": "Lafayette",
    "057": "Lafourche",
    "059": "LaSalle",
    "061": "Lincoln",
    "063": "Livingston",
    "065": "Madison",
    "067": "Morehouse",
    "069": "Natchitoches",
    "071": "Orleans",
    "073": "Ouachita",
    "075": "Plaquemines",
    "077": "Pointe Coupee",
    "079": "Rapides",
    "081": "Red River",
    "083": "Richland",
    "085": "Sabine",
    "087": "St. Bernard",
    "089": "St. Charles",
    "091": "St. Helena",
    "093": "St. James",
    "095": "St. John the Baptist",
    "097": "St. Landry",
    "099": "St. Martin",
    "101": "St. Mary",
    "103": "St. Tammany",
    "105": "Tangipahoa",
    "107": "Tensas",
    "109": "Terrebonne",
    "111": "Union",
    "113": "Vermilion",
    "115": "Vernon",
    "117": "Washington",
    "119": "Webster",
    "121": "West Baton Rouge",
    "123": "West Carroll",
    "125": "West Feliciana",
    "127": "Winn",
}

#: Keyed by state FIPS, so a second pilot state adds a table rather than a
#: branch. The grid asks for the state it is building and gets nothing for a
#: state nobody has tabulated, which leaves `parish_name` null -- the state it
#: was already in.
BY_STATE: dict[str, dict[str, str]] = {"22": LOUISIANA_PARISHES}


def names_for(state_fips: str) -> dict[str, str]:
    """County code to name for one state, empty when there is no table."""
    return BY_STATE.get(state_fips, {})


def as_arrays(state_fips: str) -> tuple[list[str], list[str]]:
    """The same mapping as two parallel arrays, for `unnest` in SQL.

    Passed as parameters rather than written into the statement so the mapping
    has one home. A copy of it in a migration is a copy that drifts.
    """
    names = names_for(state_fips)
    codes = sorted(names)
    return codes, [names[code] for code in codes]
