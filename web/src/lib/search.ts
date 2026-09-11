/**
 * What the search box will accept, and how it decides.
 *
 * Three kinds of query, because three kinds of person use this map. Someone
 * reading a report has an H3 index. Someone with a coordinate from a permit
 * filing has a latitude and longitude. Everybody else types the name of a town.
 *
 * Parsing lives here rather than in the component so the rules can be tested
 * without mounting a map, and so the component is about focus and keystrokes
 * rather than about regular expressions.
 *
 * **Place-name search is optional on purpose.** It needs a geocoder, and a
 * geocoder is a third-party service with its own terms, rate limits and privacy
 * implications. Quietly sending every keystroke a user types to an external host
 * is not something to switch on by default, so it is off unless
 * `VITE_GEOCODER_URL` is set, and the box says so rather than silently doing
 * nothing. Coordinates and cell indexes work either way, offline and always.
 */

export type Query =
  | { kind: "h3"; h3: string }
  | { kind: "coords"; lat: number; lon: number }
  | { kind: "place"; text: string };

/** An H3 index is 15 hex characters. Res-8 cells start "88", but the check is
 *  deliberately looser so a pasted index at another resolution is recognised as
 *  an index and reported as not found, rather than searched for as a town. */
const H3_INDEX = /^[0-9a-f]{15}$/i;

/** "30.45, -91.15" or "30.45 -91.15". Latitude first, the order a person reads
 *  off a map and the order every consumer mapping tool prints. */
const COORDS = /^\s*(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)\s*$/;

export function parseQuery(raw: string): Query | null {
  const text = raw.trim();
  if (!text) return null;

  if (H3_INDEX.test(text)) {
    return { kind: "h3", h3: text.toLowerCase() };
  }

  const coords = COORDS.exec(text);
  if (coords) {
    const lat = Number(coords[1]);
    const lon = Number(coords[2]);
    // Out of range is a typo, not a place. Falling through to a place search
    // would hand "91, -300" to a geocoder and get nothing useful back.
    if (lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180) {
      return { kind: "coords", lat, lon };
    }
    return null;
  }

  return { kind: "place", text };
}

/** Roughly Louisiana, for warning that a coordinate is off the scored grid. */
const PILOT_BOUNDS = { west: -94.1, south: 28.8, east: -88.7, north: 33.1 };

export function insidePilotState(lat: number, lon: number): boolean {
  return (
    lon >= PILOT_BOUNDS.west &&
    lon <= PILOT_BOUNDS.east &&
    lat >= PILOT_BOUNDS.south &&
    lat <= PILOT_BOUNDS.north
  );
}

export interface Place {
  label: string;
  lat: number;
  lon: number;
}

/**
 * Resolve a place name through a Nominatim-compatible geocoder.
 *
 * Bounded to the pilot state so a search for "Springfield" cannot fly the map
 * to Illinois, and capped at one result because the box is a jump-to, not a
 * browse.
 */
export async function geocode(
  text: string,
  signal?: AbortSignal,
): Promise<Place | null> {
  const base = import.meta.env.VITE_GEOCODER_URL;
  if (!base) return null;

  const url = new URL(base);
  url.searchParams.set("q", text);
  url.searchParams.set("format", "jsonv2");
  url.searchParams.set("limit", "1");
  url.searchParams.set("bounded", "1");
  url.searchParams.set(
    "viewbox",
    `${PILOT_BOUNDS.west},${PILOT_BOUNDS.north},${PILOT_BOUNDS.east},${PILOT_BOUNDS.south}`,
  );

  const response = await fetch(url, { signal });
  if (!response.ok) return null;

  const body: unknown = await response.json();
  if (!Array.isArray(body) || body.length === 0) return null;

  const first: unknown = body[0];
  if (!first || typeof first !== "object") return null;
  const record = first as Record<string, unknown>;

  const lat = Number(record.lat);
  const lon = Number(record.lon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;

  return {
    label: typeof record.display_name === "string" ? record.display_name : text,
    lat,
    lon,
  };
}
