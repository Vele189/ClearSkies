import "@testing-library/jest-dom/vitest";

import { beforeEach } from "vitest";

// jsdom has no layout, so scrolling is unimplemented and every route change
// logs about it. The app only ever asks for the top of the page, so a stub
// loses nothing and keeps a real failure visible in the output. Defined on the
// window rather than through `vi.stubGlobal`, which `vi.unstubAllGlobals` in a
// suite's own teardown would undo halfway through the run.
window.scrollTo = () => {};

// Each test starts at the map. Tests share one jsdom window, so a test that
// navigates would otherwise decide where the next one begins.
beforeEach(() => {
  window.history.replaceState(null, "", "/");
});
