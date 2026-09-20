# Anchor verification — CS-111

**Run 2026-09-11 against methodology v0.1.1, before any file under `scoring/` existed.**

Result: **29 of 30 anchors verified.** Three anchors named a community they did
not sit in and were corrected under §17.4. One parish label was wrong and was
fixed without moving its anchor. One site could not be verified and stays in the
set, unverified and reported, exactly as §17.4 requires.

No score existed when this ran. Nothing here could have been motivated by a
result, because there was no result.

---

## 1. Why this was needed

`scripts/check_validation_set.py` already proved the fixture consistent with
itself: every anchor is the cell its coordinates produce, and every cell list is
the disk around its anchor. That is a closed loop. It cannot tell you that the
anchor labelled "Welcome" is anywhere near Welcome, because nothing in the file
knows where Welcome is.

The thirty anchors were chosen from documentation and typed in by hand. Nobody
had checked them against a map. Until that happened the CS-206 gate measured
whether the score lights up wherever those coordinates happen to land, which is
not the same claim at all.

## 2. Method

Every anchor was checked against coordinates from outside the project, recorded
with their sources in `docs/validation/anchor-references.yml`:

| Source | Used for |
|---|---|
| USGS GNIS Domestic Names, state files retrieved 2026-09-11 | the federal authority on where a named place is |
| US Census Bureau TIGERweb, current vintage | which parish or county, and which city or CDP, a coordinate actually falls in |
| EPA ECHO and EPA Envirofacts FRS | coordinates for the plants and sites each citation names |

EPA ECHO is already a registered ClearSkies source
(`etl/pipeline/adapters/echo.py`), so the facility coordinates come from the
same place the pipeline will.

Two checks gate verification, both run by `scripts/verify_anchors.py`:

**Administrative.** The parish or county recorded for the site is the one the
Census says the anchor coordinate falls in.

**Community.** The anchor is tied to a community the site names, by one of two
routes. **Point**: a community's published coordinate resolves to a resolution 8
cell that is *in* the site's frozen cell list. **Boundary**: the Census place the
anchor falls in *is* the community the site names. The second route exists
because a named point is a single coordinate. Port Arthur's GNIS point is
downtown, four rings outside a k=2 disk, while the anchor is unambiguously
inside the city. Being within the boundary settles the question the point was
standing in for. The route is printed for every site, because the two are not
equally strong: point puts the community inside the scored cells, boundary only
puts the anchor inside the community.

Cited facilities and second communities in compound names are reported with
their ring distance but do not gate. A refinery outside the frozen cells is a
fact worth printing, not a failure. The cells are anchored on where people
live, not on the fence line, and §13.2 asks only that one scored cell of the
site reach the top decile.

`scripts/verify_anchors.py` fails CI if any `verified` flag in the fixture
disagrees with its own verdict, so the flags cannot drift away from the
evidence. It runs alongside the consistency check in `make check`.

## 3. Corrections that moved an anchor

Three. Each is a §17.4 revision, recorded in methodology §18, and together they
trigger a re-run of the full §13 protocol before any score is published.

Every move was **mechanical**: the anchor was set to the community's published
GNIS coordinate, unrounded and unchosen. `k` was not touched for any of them.
That matters, because the one discretionary knob that could improve a result is
`k`, and leaving it fixed means the correction could not have been tuned.

### Site 2 — Welcome, 5th District, St. James Parish

The registered anchor sat at `30.045, -90.828`, which is the historical Uncle
Sam site, 4.21 km east of Welcome. Its k=2 disk was six rings away from
Welcome: not merely off-centre, but sharing no cell at all with the community
the site is named for. The site's citations are the FG LA Sunshine Project
permits and *RISE St. James v. LDEQ*, both of which are about Welcome in the
5th District.

Moved to the GNIS coordinate for Welcome, `30.05937, -90.86843`. The corrected
anchor falls inside Welcome CDP, which the old one did not.

The FG LA Sunshine Project's ECHO coordinate remains 5.92 km away and outside
the cells. That coordinate is a single point registered for a roughly
2,400-acre site, so the distance overstates the separation; it is recorded
rather than acted on.

### N-WARREN — Afton, Warren County, North Carolina

The registered anchor sat at `36.204, -78.083`, which is in **Franklin County**,
19.16 km and twenty-five rings from Afton. The site is the origin of the US
environmental justice movement, and the anchor was in the wrong county.

Moved to the GNIS coordinate for Afton, Warren County, `36.33876, -78.2161`.
The site remains inactive; its `activate_when` trigger is unchanged.

### N3 — Bocage, East Baton Rouge Parish

The registered anchor sat at `30.418, -91.128`, in the Stafford Place and
Concord Estates neighbourhoods, 1.91 km from Bocage and three rings outside its
own k=1 disk. No cell of this negative control covered the community it names.

Moved to the GNIS coordinate for Bocage, `30.42797, -91.11177`.

## 4. Correction that did not move an anchor

### SB3 — Port Hudson mill vicinity

The anchor is 0.20 km from GNIS Port Hudson and correct. The **parish label was
wrong**: the fixture recorded West Feliciana, but the anchor and the
Georgia-Pacific Port Hudson mill are both in East Baton Rouge Parish.

The label was corrected and the anchor left untouched. This is a metadata fix,
not a re-anchoring: no coordinate moved, no cell changed, and `pilot_state`
gating is on `state`, not `parish`, so nothing downstream sees a difference.
Recording the distinction is the point. A wrong label and a wrong anchor are
different failures and only the second is a §17.4 revision.

The mill itself is 3.36 km from the anchor and outside the frozen cells. As a
"not an emissions map" stress case this is a weaker probe than intended: the
cells sit in the Port Hudson community near a large emitter rather than on it.
Recorded, not fixed, because fixing it means moving an anchor that is in the
right place.

## 5. The site that did not verify

### Site 4 — Alsen / North Baton Rouge, East Baton Rouge Parish

`verified: false`. The anchor is **not** moved.

The anchor sits among the Crestworth and North Maryland neighbourhoods, which
is North Baton Rouge, the second half of the site's compound name. Alsen is
2.62 km away and three rings outside the frozen cells. Two of the site's three
citations — Bullard's *Dumping in Dixie* and the Rollins Environmental Services
and Alsen landfill Superfund records — are specifically about Alsen. The third,
EPA ECHO records for the Baton Rouge refinery complex, does describe what the
cells cover.

This is the distinction §17.4 draws, and it cuts the other way from the three
corrections above. An anchor that names the wrong community may be corrected.
This anchor names two communities and sits in one of them, which makes the site
poorly chosen rather than misnamed, and a poorly chosen site "stays in the set
with a documented note explaining the problem, and continues to be reported."

It would have been easy to move it 2.62 km north and take a thirtieth green
tick. That is precisely the edit §17.4 exists to forbid, and the fact that
nobody knows yet which way the score would move is not a licence to make it.

CS-206 will score this site on cells that cover North Baton Rouge and not
Alsen. Whatever it returns should be read with that in mind.

## 6. Full results

Ring distance is grid steps from the anchor cell. A k=1 site has rings 0–1, a
k=2 site rings 0–2, a k=3 site rings 0–3; anything beyond is outside the
frozen cells.

| Site | Verified | Route | Community reference | km | Ring |
|---|---|---|---|---|---|
| 1 Reserve / LaPlace | yes | point | GNIS Reserve | 0.34 | 0 |
| 2 Welcome, 5th District | yes, corrected | point | GNIS Welcome | 0.00 | 0 |
| 3 Mossville | yes | point | GNIS Mossville | 0.90 | 1 |
| 4 Alsen / North Baton Rouge | **no** | — | GNIS Alsen | 2.62 | 3 |
| 5 Norco | yes | point | GNIS Norco | 0.25 | 0 |
| 6 Plaquemine | yes | point | GNIS Plaquemine | 0.07 | 0 |
| 7 Chalmette | yes | point | GNIS Chalmette | 0.05 | 0 |
| 8 Geismar | yes | point | GNIS Geismar | 1.76 | 2 |
| 9 Gordon Plaza | yes | point | Agriculture Street Landfill boundary | 0.65 | 1 |
| 10 Port Allen / Brusly | yes | point | GNIS Port Allen | 0.30 | 0 |
| N-FLINT | yes | point | GNIS Flint | 0.06 | 0 |
| N-CHESTER | yes | point | GNIS Chester | 0.88 | 1 |
| N-MANCHESTER | yes | point | GNIS Manchester | 0.56 | 1 |
| N-PORTARTHUR | yes | boundary | inside City of Port Arthur | 3.45 | 4 |
| N-WESTOAKLAND | yes | point | GNIS West Oakland | 0.22 | 0 |
| N-KETTLEMAN | yes | point | GNIS Kettleman City | 0.19 | 0 |
| N-INSTITUTE | yes | point | GNIS Institute | 0.09 | 0 |
| N-UNIONTOWN | yes | point | GNIS Uniontown | 0.07 | 0 |
| N-WARREN | yes, corrected | point | GNIS Afton | 0.00 | 0 |
| N-EASTCHICAGO | yes | point | GNIS East Chicago | 0.70 | 1 |
| N1 Mandeville | yes | point | GNIS Mandeville | 0.07 | 0 |
| N2 Old Metairie | yes | boundary | inside Metairie CDP | 2.43 | 3 |
| N3 Bocage | yes, corrected | point | GNIS Bocage | 0.00 | 0 |
| N4 South Lafayette | yes | boundary | inside City of Lafayette | 4.24 | 5 |
| SA1 Lake Providence | yes | point | GNIS Lake Providence | 0.19 | 0 |
| SA2 Tallulah | yes | point | GNIS Tallulah | 0.06 | 0 |
| SA3 St. Joseph | yes | point | GNIS Saint Joseph | 0.18 | 0 |
| SB1 Alliance Refinery vicinity | yes | point | GNIS Alliance | 1.29 | 2 |
| SB2 Krotz Springs | yes | point | GNIS Krotz Springs | 0.22 | 1 |
| SB3 Port Hudson mill vicinity | yes, parish fixed | point | GNIS Port Hudson | 0.20 | 0 |

### Cited facilities outside the frozen cells

Reported, not gating. These are the fence lines the citations name, measured
from anchors that sit on the communities instead.

| Site | Facility | km | Ring |
|---|---|---|---|
| 1 | Denka Performance Elastomer, Pontchartrain Works | 2.96 | 3 |
| 2 | FG LA LLC Sunshine Project (early works point) | 5.92 | 7 |
| 3 | Sasol Lake Charles Chemical Complex | 2.60 | 3 |
| 6 | Dow Louisiana Operations, Plaquemine | 3.56 | 4 |
| 8 | NOVA Chemicals Geismar, former Williams Olefins | 3.32 | 4 |
| 9 | Agriculture Street Landfill, EPA mailing address | 1.58 | 2 |
| 10 | Placid Refining, Port Allen | 2.89 | 4 |
| N-KETTLEMAN | Chemical Waste Management, Kettleman Hills | 4.80 | 6 |
| N-UNIONTOWN | Arrowhead Landfill | 3.59 | 5 |
| SB1 | Alliance Refinery terminal | 2.23 | 3 |
| SB3 | Georgia-Pacific Port Hudson mill | 3.36 | 3 |

Facilities that *are* inside their site's cells: Shell Norco (site 5, ring 1),
Chalmette Refining (site 7, ring 1), Bayer CropScience Institute
(N-INSTITUTE, ring 1).

### Second communities in compound names

`Reserve / LaPlace`, `Alsen / North Baton Rouge` and `Port Allen / Brusly` each
name two communities and can only cover one at their registered `k`. LaPlace is
7.7 km from site 1's anchor, Brusly 7.37 km from site 10's. Both are far outside
their disks. The names overstate what the cells measure. Left as registered, and
noted here and in the fixture, because renaming a site is not among the changes
§17.4 permits.

## 7. What this changes for CS-206

The primary gate is unchanged: 8 of the 10 active Louisiana sites must have a
pre-registered cell in the statewide top decile. Two of those ten now read
differently than they did before this run.

- **Site 2** is now scored on Welcome rather than on a stretch of river road
  four kilometres east of it. This is the site whose cells changed most, and it
  changed from cells that had nothing to do with the citation to cells that do.
- **Site 4** is scored on cells that cover North Baton Rouge and not Alsen, and
  is the one site in the set carrying `verified: false`.

The three moved anchors make this a §17 revision, so the full §13 protocol
re-runs from the beginning once scoring exists. Since no scoring code exists
yet, "re-run from the beginning" costs nothing here, which is the whole reason
CS-111 was scheduled before CS-206 rather than after it.
