/** Search-to-location.
 *
 *  Photon rather than Nominatim. Nominatim's usage policy requires a
 *  descriptive User-Agent on every request, and a browser will not let us set
 *  that header, so calling it from the frontend is a policy violation we cannot
 *  fix from here. Photon is the same OpenStreetMap data, is CORS-open, and asks
 *  for no key. The endpoint is configurable so a self-hosted instance can be
 *  dropped in without a code change.
 */

const ENDPOINT = import.meta.env.VITE_GEOCODER_URL ?? "https://photon.komoot.io/api";

/** Bias results toward the pilot state instead of returning the Springfield of
 *  whichever country indexed first. Not a hard filter: a user pasting a
 *  coordinate outside Louisiana still gets taken there, and finding out that
 *  the map has nothing to show them is a legitimate answer. */
const BIAS: [number, number] = [-91.5, 30.6];

export interface Place {
  /** Stable enough to key a list on within a single response. */
  id: string;
  name: string;
  /** Parish, state, country — whatever of it the record carries. */
  context: string;
  center: [number, number];
}

/** A pasted or typed coordinate pair, in either order convention people
 *  actually use: "30.05, -90.55" and "-90.55 30.05" both mean the same place
 *  in Louisiana, and guessing wrong sends the reader to the Indian Ocean.
 *  Latitude is the one constrained to ±90, which resolves it unambiguously
 *  here because Louisiana's longitude is outside that range. */
export function parseCoordinates(query: string): Place | null {
  const match = query.trim().match(/^(-?\d+(?:\.\d+)?)\s*[,\s]\s*(-?\d+(?:\.\d+)?)$/);
  if (!match) return null;

  const a = Number(match[1]);
  const b = Number(match[2]);

  let lat: number;
  let lon: number;
  if (Math.abs(a) <= 90 && Math.abs(b) > 90) {
    [lat, lon] = [a, b];
  } else if (Math.abs(b) <= 90 && Math.abs(a) > 90) {
    [lat, lon] = [b, a];
  } else {
    // Both plausible as a latitude. Fall back to the written convention,
    // latitude first, rather than guessing from the values.
    [lat, lon] = [a, b];
  }

  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;

  return {
    id: `coord:${lat},${lon}`,
    name: `${lat.toFixed(4)}, ${lon.toFixed(4)}`,
    context: "Coordinates",
    center: [lon, lat],
  };
}

interface PhotonFeature {
  geometry?: { coordinates?: unknown };
  properties?: Record<string, unknown>;
}

function str(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function toPlace(feature: PhotonFeature, index: number): Place | null {
  const coords = feature.geometry?.coordinates;
  if (!Array.isArray(coords) || typeof coords[0] !== "number" || typeof coords[1] !== "number") {
    return null;
  }
  const props = feature.properties ?? {};
  const name = str(props.name) ?? str(props.street) ?? str(props.city);
  if (!name) return null;

  const context = [str(props.county), str(props.state), str(props.country)]
    .filter((part): part is string => part !== null)
    .join(", ");

  const osmId = typeof props.osm_id === "number" || typeof props.osm_id === "string"
    ? String(props.osm_id)
    : String(index);

  return {
    id: `${str(props.osm_type) ?? "f"}${osmId}`,
    name,
    context,
    center: [coords[0], coords[1]],
  };
}

export async function searchPlaces(query: string, signal?: AbortSignal): Promise<Place[]> {
  const trimmed = query.trim();
  if (trimmed.length < 3) return [];

  const coordinate = parseCoordinates(trimmed);
  if (coordinate) return [coordinate];

  const url = new URL(ENDPOINT);
  url.searchParams.set("q", trimmed);
  url.searchParams.set("limit", "5");
  url.searchParams.set("lon", String(BIAS[0]));
  url.searchParams.set("lat", String(BIAS[1]));

  const response = await fetch(url, { signal });
  if (!response.ok) throw new Error(`Search is unavailable (${String(response.status)}).`);

  const body: unknown = await response.json();
  const features =
    body && typeof body === "object" && "features" in body && Array.isArray(body.features)
      ? (body.features as PhotonFeature[])
      : [];

  return features
    .map(toPlace)
    .filter((place): place is Place => place !== null)
    .slice(0, 5);
}
