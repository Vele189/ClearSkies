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

/** A fallback only.
 *
 *  The name now travels with the hexagon: `scored_state` holds it and
 *  `/hex` returns it as `state_name`, so the client no longer has to keep a
 *  table of FIPS codes in step with which states are scored. This stays for
 *  the case where an older API answers without the field, and for the
 *  neighbouring codes a hexagon on the state line can carry. */
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
export function placeName(hex: {
  parish: string | null;
  state: string;
  state_name?: string | null;
}): string {
  if (hex.parish) return `${hex.parish} Parish`;

  const state = hex.state_name ?? stateName(hex.state);
  if (state) return state;

  // An unknown code is still not a name. Saying so is better than printing it
  // and better than an empty heading, and it tells whoever sees it that the
  // gap is in the data rather than in the map.
  return "Location not recorded";
}
