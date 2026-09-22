/** What to call the place a hexagon is in.
 *
 *  The panel heading used to be `parish ? "<parish> Parish" : state`, and
 *  `state` is a FIPS code, not a name. Against the loaded pilot-state grid not
 *  one of the 173,424 hexagons carries a parish name, so every heading fell
 *  through to the else branch and read **"22"**. A reader who clicked a
 *  hexagon in Baton Rouge was shown a two-digit number as the name of where
 *  they live.
 *
 *  Filling `hex.parish_name` is a pipeline job and is tracked separately. This
 *  is the part the frontend owes regardless: never render an internal
 *  identifier as though it were a place.
 */

/** FIPS state codes the pilot touches. Louisiana and its neighbours, because a
 *  hexagon on the state line can carry a facility from across it. */
const STATE_NAMES: Record<string, string> = {
  "01": "Alabama",
  "05": "Arkansas",
  "22": "Louisiana",
  "28": "Mississippi",
  "48": "Texas",
};

export function stateName(fips: string): string | null {
  return STATE_NAMES[fips] ?? null;
}

/** The heading for one hexagon: the most specific name we actually have. */
export function placeName(hex: { parish: string | null; state: string }): string {
  if (hex.parish) return `${hex.parish} Parish`;

  const state = stateName(hex.state);
  if (state) return state;

  // An unknown code is still not a name. Saying so is better than printing it
  // and better than an empty heading, and it tells whoever sees it that the
  // gap is in the data rather than in the map.
  return "Location not recorded";
}
