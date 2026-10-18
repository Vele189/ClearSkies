/** Where the map is allowed to be.
 *
 *  Louisiana is the only scored state (docs/expansion.md section 7), so the map
 *  and the search both stay inside it. Held here once so the camera, the pan
 *  limit and the geocoder cannot disagree about where Louisiana is.
 */

export type LngLat = [number, number];
export type Bounds = [LngLat, LngLat];

/** The scored extent: the tile archive's own header, rounded outward. The grid
 *  carries a buffer past the state line, so this is a little wider than the
 *  TIGER boundary on every side. */
export const LOUISIANA_BOUNDS: Bounds = [
  [-94.05, 28.85],
  [-88.75, 33.03],
];

/** How far the camera may pan. A margin past the scored extent so an edge
 *  parish can be centred on screen, and no further: past it there are no
 *  hexagons, only basemap. */
export const MAX_BOUNDS: Bounds = [
  [-96.3, 27.6],
  [-86.5, 34.4],
];

/** The archive starts at zoom 6. Below it there are no tiles, so zooming out
 *  past it does not show more of Louisiana, it shows none of it. */
export const MIN_ZOOM = 6;

export const LOUISIANA_CENTER: LngLat = [
  (LOUISIANA_BOUNDS[0][0] + LOUISIANA_BOUNDS[1][0]) / 2,
  (LOUISIANA_BOUNDS[0][1] + LOUISIANA_BOUNDS[1][1]) / 2,
];

/** Whether a point falls in the scored extent. A box, not the state line, so a
 *  few places just over the border in Texas, Arkansas and Mississippi pass; the
 *  map then shows them unscored, which is true. */
export function inLouisiana([lon, lat]: LngLat): boolean {
  const [[west, south], [east, north]] = LOUISIANA_BOUNDS;
  return lon >= west && lon <= east && lat >= south && lat <= north;
}
