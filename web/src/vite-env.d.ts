/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
  readonly VITE_TILES_URL?: string;
  readonly VITE_BASEMAP_STYLE?: string;
  /** A Nominatim-compatible geocoder. Place search is off when unset, so a
   *  deployment does not send what people type to a third party by default. */
  readonly VITE_GEOCODER_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
