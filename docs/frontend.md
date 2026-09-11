# Frontend

How the map draws a score, and how it draws how much we trust it.

This document covers the decisions in `web/` that are communication decisions
rather than styling ones. The colour ramp, the legend and the confidence
treatment are all in that category: they determine what a reader concludes from
a glance, which is most of what this project does. `docs/methodology.md` section
12 is the authority on the confidence bands themselves; nothing here may move a
cut point.

**Status: awaiting Lead sign-off.** CS-210 records the ramp, the legend and the
band treatment as needing the Lead's approval before they are final. What
follows is the proposal, implemented and testable, not a ratified decision.

---

## 1. What the map colours

The map colours by **statewide percentile**, not raw score. The raw distribution
is heavily right-skewed, so a linear ramp on it renders most of Louisiana
indistinguishable. This follows methodology section 10, step 5.

Percentiles are Louisiana percentiles throughout. A hex in the 90th percentile
here is in the top decile of Louisiana, which is not the top decile of the
United States.

## 2. The ramp

ColorBrewer **YlOrRd, 6-class**, stepped rather than interpolated.

| Class | Percentile | Colour |
|---|---|---|
| 1 | 0–20 | `#ffffb2` |
| 2 | 20–40 | `#fed976` |
| 3 | 40–60 | `#feb24c` |
| 4 | 60–80 | `#fd8d3c` |
| 5 | 80–90 | `#f03b20` |
| 6 | 90–100 | `#bd0026` |

**Why this ramp is colourblind-safe.** It is monotone in lightness across its
whole length, from roughly L\* 98 at the pale end to L\* 35 at the dark end.
That is the property that matters. Strip the hue entirely and the ramp degrades
to a legible greyscale sequence, so it survives not only deuteranopia and
protanopia but tritanopia and achromatopsia as well. Hue is carrying emphasis
here; lightness is carrying the information. `web/src/lib/ramp.test.ts` asserts
the monotonicity and a minimum step between adjacent classes, so the claim
cannot quietly stop being true.

**Why not viridis.** Viridis is perceptually uniform and equally safe, but it
puts bright yellow at the high end. A reader who has not consulted the legend
reads bright yellow as "fine". Burden maps have an established convention of
darker and hotter meaning worse, and fighting it costs more than it gains.

**Why stepped and not continuous.** Every colour that appears on the map
appears in the legend. A continuous ramp asks the reader to interpolate between
two swatches by eye, which they cannot do accurately and should not have to.

**Why the classes are uneven.** Even twenty-point classes to the 80th, then a
split at the 90th. The pre-registered validation criterion in methodology
section 13.2 is about the statewide top decile, so the top decile has to be
visible as its own class rather than inferred from the top fifth.

**Unscored hexes** are drawn in neutral grey `#d9d9d9`, off the ramp, with
their own legend entry. A hex with no score is not a low-burden hex, and
painting it at the pale end of the ramp would assert exactly that. Methodology
section 11 is explicit that zero and missing are different things, and the map
has to hold that line as much as the database does.

## 3. Confidence

Methodology section 12 gives four bands and their treatment. The implementation
follows it exactly:

| Band | Confidence | On the map |
|---|---|---|
| High | ≥ 0.80 | Solid fill |
| Moderate | 0.60–0.79 | Solid fill |
| Low | 0.40–0.59 | Hatched fill, 45°, dark lines over the class colour |
| Insufficient | < 0.40 | Hidden, behind a legend toggle |

**Why hatching and not opacity.** A faded fill reads as a lower score. It
lands on the reader as less burden, not as less certainty, and section 12 is
explicit that the two must never be conflated. Hatching adds a channel instead
of degrading the one already in use: the colour still says how burdened, and
the texture says how sure. The hatch is drawn as a separate layer over the fill
rather than replacing it, so a low-confidence hex keeps its class colour.

**A hex with no confidence attribute at all is hatched.** That is an archive
defect rather than a data-quality signal, but drawing it as confident is the
one failure section 12 exists to prevent, so it reads as uncertain until the
archive says otherwise.

**The insufficient toggle is off by default and says why.** Those hexes are
excluded from validation statistics and from the drafting assistant, and the
legend copy states that rather than silently withholding them.

**Band precedence.** The tile's `confidence_band` attribute wins over the band
derived from the raw `confidence` value. A band correction in the pipeline then
reaches the map without a frontend release. Both attributes come from CS-207.

## 4. The legend

Always on screen, bottom left. Collapsed behind a disclosure on viewports
narrower than the `sm` breakpoint, where a permanently open legend covers the
map it is explaining.

The legend and the map read the same module, `web/src/lib/ramp.ts`. A swatch is
the colour the tile is painted with by construction, not because two lists are
kept in step by hand. The hatch appears twice — as a canvas image for MapLibre
and as an SVG pattern for the legend swatch — from the same angle, spacing and
weight.

## 5. Search

`VITE_GEOCODER_URL`, defaulting to Photon.

Photon rather than Nominatim. Nominatim's usage policy requires a descriptive
`User-Agent` on every request, and a browser will not let the page set that
header, so calling it from the frontend is a policy violation that cannot be
fixed from the frontend. Photon is the same OpenStreetMap data, is CORS-open,
and asks for no key. The endpoint is configurable so a self-hosted instance can
replace it without a code change.

Queries are debounced at 300 ms and biased toward the pilot state, so
"Springfield" resolves nearer to Louisiana than to whichever Springfield indexed
first. The bias is not a filter: a coordinate outside Louisiana still takes the
reader there, and finding out that the map has nothing to show them is a
legitimate answer.

A typed or pasted coordinate pair is resolved locally without a network call.
Latitude first, as coordinates are written, except where only one of the two
values can be a latitude, in which case the pair is read in the order that
works.

The input is a combobox: arrow keys move through results, Enter picks, Escape
dismisses. A failed search says it failed rather than showing an empty list,
because "no results" and "the geocoder is down" mean different things.

## 6. Loading and failure

A tile fetch failure must not leave a blank screen. Three states:

- **Loading.** An overlay until the map fires `load`.
- **Basemap failed.** Takes the viewport, because nothing will render behind
  it, and offers a reload. Gated on `load` never arriving, so a survivable
  sprite or glyph 404 does not trigger it.
- **Hex tiles failed.** A corner notice only. The basemap is up and the map is
  still usable, and the notice says plainly that this is a loading failure and
  not an absence of burden.

The Phase 0 banner is separate from all three and stays until scores exist. It
explains that no hexagon is scored yet, which is the current and correct
behaviour of a pipeline that has not run.

## 7. Deployment

The Railway `web` service, described in `.railway/railway.ts`. Vite builds it,
`serve -s dist` serves it. `serve` is a devDependency, so the build must not
prune dev dependencies before the deploy stage.

**CDN.** Enabled on `web` only, under Settings > Edge or with `railway cdn
enable`. Never on `api`. The reasoning is in `.railway/railway.ts`.

**Build-time variables.** Vite inlines anything prefixed `VITE_` at build time,
so these are build inputs and not runtime configuration. Changing one requires a
rebuild, not a restart.

| Variable | Source |
|---|---|
| `VITE_API_BASE_URL` | `https://${{api.RAILWAY_PUBLIC_DOMAIN}}` |
| `VITE_BASEMAP_STYLE` | OpenFreeMap Positron |
| `VITE_TILES_URL` | The R2 archive, once CS-207 produces one |
| `VITE_GEOCODER_URL` | Optional; defaults to Photon |

`VITE_TILES_URL` is deliberately unset in `.railway/railway.ts`. Until CS-207
publishes an archive there is nothing to point it at, and an unset value is
handled: the map renders the basemap and the banner explains why there are no
hexes. A URL pointing at an archive that does not exist would instead produce
the tile-failure notice, which would be true but misleading.

**Preview environments.** Railway builds a per-pull-request environment when PR
Environments are enabled on the base environment, under Settings > Environments
in the dashboard. It is not expressible in the IaC schema, so it cannot be
turned on from `.railway/railway.ts` and has to be a dashboard action.

Two things to check when it is switched on, neither of which has been verified
against the live project yet, because the project's three services have not been
created:

1. Service reference variables resolve within the preview environment, so a
   preview `web` should pick up its own preview `api` rather than production.
   The `CORS_ORIGINS` reference on `api` should follow the same way round.
2. Each preview is a full set of services including a database, which is the
   part most likely to exceed the plan.

If either turns out not to hold on the current plan, previews are not available
and this section should be amended to say so plainly rather than left aspirational.
