import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173 },
  build: { outDir: "dist", sourcemap: true },
  optimizeDeps: {
    // maplibre-gl starts its worker with `new Worker(url, { type: "module" })`,
    // where the url resolves next to the module that asked for it. Vite's
    // dependency pre-bundling rewrites `maplibre-gl.mjs` into
    // `.vite/deps/maplibre-gl.js` and does not bring the sibling
    // `maplibre-gl-worker.mjs` with it, so the worker request 404s. A 404
    // carries no Content-Type, which the browser reports as a blocked "" MIME
    // type rather than as the missing file it is.
    //
    // Excluding it from pre-bundling serves the package from its own directory,
    // where the worker sits where its url expects. The cost is that maplibre is
    // not pre-bundled, which is a first-load cost in dev only.
    exclude: ["maplibre-gl"],
  },
});
