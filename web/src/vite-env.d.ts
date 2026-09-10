/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
  readonly VITE_TILES_URL?: string;
  readonly VITE_BASEMAP_STYLE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
