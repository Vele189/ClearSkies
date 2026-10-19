import { ExternalLink as ExternalLinkIcon, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils.ts";
import {
  COMPONENT_LABELS,
  NO_SCORE_EXPLANATIONS,
  bandReading,
  confidenceTerms,
  droppedGroups,
  groupCoverage,
  indicatorValue,
  leadsWithCaveat,
  mergeFacilities,
  productOfComponents,
  rankSentence,
  rankShort,
  vintageFor,
  weakestTerm,
  weightedGroupMean,
  zeroInflationNote,
  type FacilityRow,
} from "../lib/score.ts";
import { placeName } from "../lib/place.ts";
import { LEGEND_CLASSES, blendOnWhite } from "../lib/ramp.ts";
import { BAND_LABELS, GROUP_LABELS } from "../lib/types.ts";
import { INDICATOR_WORDING, programWording } from "../lib/wording.ts";
import DraftPanel from "./DraftPanel.tsx";
import { TextLink } from "./Link.tsx";
import { Badge } from "./ui/badge.tsx";
import { Button } from "./ui/button.tsx";
import { Separator } from "./ui/separator.tsx";
import type {
  ComponentScore,
  ConfidenceBand,
  Facility,
  HexDetail,
  IndicatorValue,
} from "../lib/types.ts";

/** The small-caps rule that opens each block of the panel.
 *
 *  The level is passed rather than fixed, because the document outline is not
 *  a styling decision: "How this score was reached" is a section of the
 *  hexagon, and the groups inside it are subsections of that.
 */
function SectionLabel({
  as: Tag = "h4",
  className,
  children,
}: {
  as?: "h3" | "h4";
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <Tag
      className={cn(
        "text-[0.6875rem] font-semibold tracking-[0.06em] text-muted-foreground uppercase",
        className,
      )}
    >
      {children}
    </Tag>
  );
}

/** How the confidence band is badged. Never the only carrier: the band is
 *  printed in words inside the badge, and `bandReading` states it as a
 *  sentence besides. */
const BAND_VARIANT: Record<ConfidenceBand, "default" | "warn" | "bad"> = {
  high: "default",
  moderate: "default",
  low: "warn",
  insufficient: "bad",
};

/** How many facilities the panel lists before asking. The nearest few are the
 *  ones that drive the proximity indicators; a list of forty pushed the
 *  drafting assistant so far down the panel that nobody found it. */
const FACILITIES_SHOWN = 5;

/** The map's colour for a percentile, so the panel's headline carries the same
 *  swatch the reader clicked on. Blended as the legend blends it. */
function classColor(percentile: number): string {
  const cls =
    LEGEND_CLASSES.find((c) => percentile >= c.from && percentile < c.to) ??
    LEGEND_CLASSES[LEGEND_CLASSES.length - 1];
  return blendOnWhite(cls.color);
}

function Bar({ percentile, observed }: { percentile: number | null; observed: boolean }) {
  if (!observed || percentile === null) {
    return <span className="text-xs text-faint italic">no data here</span>;
  }
  // aria-hidden: the ordinal is printed in the same row, so announcing the bar
  // as well would read every indicator's rank twice.
  return (
    <div aria-hidden="true" className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-secondary">
      <div
        className="h-full rounded-full bg-body"
        style={{ width: `${String(Math.max(1, percentile))}%` }}
      />
    </div>
  );
}

function IndicatorRow({
  indicator,
  vintage,
}: {
  indicator: IndicatorValue;
  vintage: string | null;
}) {
  const value = indicatorValue(indicator);
  const zero = zeroInflationNote(indicator);
  const wording = INDICATOR_WORDING[indicator.id];
  return (
    <li className="grid grid-cols-[1fr_5.5rem] items-start gap-3 py-2.5">
      <div className="min-w-0">
        <div className="flex flex-wrap items-baseline justify-between gap-x-2 text-sm text-foreground">
          {/* The plain name, with the methodology's own name kept as a tooltip
              for a reader cross-checking against the methodology. */}
          <span title={`${indicator.id}: ${indicator.name}`}>{wording?.name ?? indicator.name}</span>
          {/* The measured value where its unit means something on its own.
              The rank says how this compares; the value says how much. */}
          {value && <span className="text-xs text-muted-foreground tabular-nums">{value}</span>}
        </div>
        <Bar percentile={indicator.percentile} observed={indicator.observed} />
        {wording && <p className="mt-1 text-xs leading-snug text-muted-foreground">{wording.about}</p>}
        <div className="mt-0.5 text-xs text-faint">
          Source: {indicator.source}
          {vintage && <span> &middot; {vintage}</span>}
        </div>
        {zero && (
          // Methodology section 9 requires this on the panel rather than
          // smoothed over. Without it the percentile reads as a ranking, when
          // for a hex at zero it is only the size of the zero block.
          <p className="mt-1.5 rounded border border-warn-border bg-warn-surface px-2 py-1.5 text-xs leading-relaxed text-warn-foreground">
            {zero}
          </p>
        )}
      </div>
      <div className="pt-0.5 text-right text-sm font-medium text-body">
        {indicator.observed && indicator.percentile !== null
          ? rankShort(indicator.percentile)
          : "—"}
      </div>
    </li>
  );
}

/** A group's weight in words. The methodology weights Environmental Effects
 *  at half of Exposures (section 10); "×0.5" was opaque to most readers. */
function weightWords(weight: number): string {
  if (weight === 1) return "full weight";
  if (weight === 0.5) return "half weight";
  return `weight ${weight.toFixed(1)}`;
}

/** Methodology section 10, steps 1 to 3, for one component. Each group's mean
 *  percentile, the weight it carries, and the weighted mean they produce. */
function ComponentWaterfall({ component }: { component: ComponentScore }) {
  const raw = weightedGroupMean(component.groups);
  const dropped = droppedGroups(component.groups);

  return (
    <section className="mt-4 first:mt-0">
      <h4 className="flex items-baseline justify-between gap-3 text-sm font-semibold">
        <span>{COMPONENT_LABELS[component.component]}</span>
        <span className="text-muted-foreground">{component.score.toFixed(1)} / 10</span>
      </h4>

      <ul className="mt-2">
        {component.groups.map((group) => (
          <li
            key={group.group}
            className="grid grid-cols-[1fr_4.5rem_5.5rem] items-start gap-2 py-1.5 text-sm"
          >
            <div className="min-w-0">
              <div className="text-foreground">{GROUP_LABELS[group.group]}</div>
              <div className="text-xs text-faint">
                {groupCoverage(group)}
                {!group.computable && " — not enough data, left out"}
              </div>
            </div>
            <div className="text-right text-xs text-faint">{weightWords(group.weight)}</div>
            <div className="text-right text-sm font-medium text-body">
              {/* An average of the group's ranks, which is not itself a rank,
                  so it is not written as "Top 7%". */}
              {group.computable && group.mean_percentile !== null
                ? `${String(Math.round(group.mean_percentile))}/100`
                : "—"}
            </div>
          </li>
        ))}
      </ul>

      <div className="mt-2 border-t border-border pt-2 text-xs leading-relaxed text-muted-foreground">
        {raw === null ? (
          <p>We didn't have enough data to work this part out.</p>
        ) : (
          <p>
            Weighing these together gives an average of{" "}
            <span className="font-medium text-foreground">{raw.toFixed(1)} out of 100</span>,
            which works out to{" "}
            <span className="font-medium text-foreground">
              {component.score.toFixed(1)} out of 10
            </span>
            .
          </p>
        )}
        {dropped.length > 0 && (
          <p className="mt-1.5">
            {dropped.map((g) => GROUP_LABELS[g.group]).join(" and ")}{" "}
            {dropped.length === 1 ? "was" : "were"} left out rather than counted as zero, because
            missing data isn't the same as no pollution.
          </p>
        )}
      </div>
    </section>
  );
}

/** A 0-1 confidence term as a score out of 100. */
function outOf100(value: number): string {
  return `${String(Math.round(value * 100))}/100`;
}

function ConfidenceBreakdown({ hex, restate }: { hex: HexDetail; restate: boolean }) {
  const terms = confidenceTerms(hex.confidence);
  const weakest = weakestTerm(hex.confidence);

  return (
    <section>
      <SectionLabel>How sure we are</SectionLabel>
      {/* For the low and insufficient bands the same sentence already opens the
          panel; saying it twice made the second one look like a new warning. */}
      {restate && (
        <p className="mt-2 text-sm leading-relaxed text-body">{bandReading(hex.confidence.band)}</p>
      )}

      <ul className="mt-2.5">
        {terms.map((term) => (
          <li
            key={term.id}
            className="grid grid-cols-[1fr_4.5rem_3.5rem] items-start gap-2 py-1.5 text-sm"
          >
            <div className="min-w-0">
              <div className="text-foreground">{term.label}</div>
              <div className="text-xs text-faint">{term.meaning}</div>
            </div>
            <div className="text-right text-xs text-faint">
              counts {Math.round(term.weight * 100)}%
            </div>
            <div className="text-right font-medium text-body">{outOf100(term.value)}</div>
          </li>
        ))}
      </ul>

      {/* Section 12's weighted geometric mean, said by what it does: one weak
          term drags the result down instead of being averaged away. */}
      <p className="mt-2.5 border-t border-border pt-2.5 text-xs leading-relaxed text-muted-foreground">
        We combine these so one weak spot pulls the whole rating down rather than being hidden
        by the others. The weakest here is{" "}
        <span className="font-medium text-foreground">{weakest.label.toLowerCase()}</span> (
        <span className="font-medium text-foreground">{outOf100(weakest.value)}</span>)
        {weakest.id === "monitor" && hex.confidence.nearest_monitor_km !== null && (
          <>
            : the nearest air monitor is{" "}
            <span className="font-medium text-foreground">
              {hex.confidence.nearest_monitor_km.toFixed(0)} km
            </span>{" "}
            away
          </>
        )}
        . This tells you how far to trust the result, not how bad the pollution is.
      </p>
    </section>
  );
}

/** The compliance record that matters to a reader, when there is one. Both
 *  figures are on the API response and were not shown anywhere before. */
function complianceNote(facility: FacilityRow): string | null {
  const parts: string[] = [];
  const quarters = facility.quarters_in_noncompliance ?? 0;
  const actions = facility.formal_actions_5yr ?? 0;
  if (quarters > 0) {
    parts.push(
      `Broke its permit rules in ${String(quarters)} of the last 12 quarters`,
    );
  }
  if (actions > 0) {
    parts.push(
      `${String(actions)} government enforcement ${actions === 1 ? "action" : "actions"} in 5 years`,
    );
  }
  return parts.length > 0 ? parts.join(" · ") : null;
}

function FacilityList({ facilities, total }: { facilities: Facility[]; total: number }) {
  const [expanded, setExpanded] = useState(false);
  const rows = mergeFacilities(facilities);
  const shown = expanded ? rows : rows.slice(0, FACILITIES_SHOWN);
  const hidden = rows.length - shown.length;

  return (
    <section className="mt-6">
      <SectionLabel>Industrial sites within 10 km (6 miles)</SectionLabel>
      <p className="mt-1 text-xs leading-relaxed text-faint">
        {rows.length === 1 ? "1 site" : `${String(rows.length)} sites`}, nearest first
        {/* The count is uncapped and the list is not. A reader told "50" by a
            list that stopped at 50 has been told something false. */}
        {total > facilities.length &&
          ` (the nearest ${String(facilities.length)} of ${String(total)} permits)`}
        . Being listed doesn&apos;t mean a site has done anything wrong.
      </p>
      <ul className="mt-2.5 space-y-2.5">
        {shown.map((f) => {
          const compliance = complianceNote(f);
          return (
            <li key={f.registry_id} className="text-sm">
              <a
                href={f.echo_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-baseline gap-1 font-medium text-link underline decoration-from-font underline-offset-2 hover:no-underline"
              >
                {f.name}
                <ExternalLinkIcon aria-hidden="true" className="size-3 shrink-0 self-center" />
              </a>
              <div className="text-xs text-faint">
                {f.programs.map(programWording).join(", ")} &middot; {f.distance_km.toFixed(1)} km
                away
                {f.in_hex && " · inside this area"}
              </div>
              {compliance && <div className="text-xs text-warn-foreground">{compliance}</div>}
            </li>
          );
        })}
      </ul>
      {(hidden > 0 || expanded) && rows.length > FACILITIES_SHOWN && (
        <Button
          variant="outline"
          size="sm"
          className="mt-3"
          aria-expanded={expanded}
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? "Show fewer" : `Show all ${String(rows.length)} sites`}
        </Button>
      )}
    </section>
  );
}

function PeopleHere({ hex }: { hex: HexDetail }) {
  return (
    <section className="mt-6">
      <SectionLabel>Who lives here</SectionLabel>
      <p className="mt-2 text-sm text-body">
        {Math.round(hex.demographics.population) === 0
          ? "No residents counted here"
          : `About ${Math.round(hex.demographics.population).toLocaleString("en-US")} ${
              Math.round(hex.demographics.population) === 1 ? "resident" : "residents"
            }`}
      </p>
      <p className="mt-1.5 text-xs leading-relaxed text-faint">
        Shown for context only. Who lives here, including race, is never used to work out the
        result, so any link we find between race and pollution is a real finding rather than
        something we built in.
      </p>
    </section>
  );
}

function pct(value: number | null | undefined): string {
  return value == null ? "not available" : `${value.toFixed(1)}%`;
}

/** CDC PLACES, shown for context the way race is: next to the result, never in
 *  it. The wording says "estimated" because these are model outputs, not
 *  counts of diagnosed people. */
function HealthHere({ hex }: { hex: HexDetail }) {
  const health = hex.health;
  if (!health) return null;
  return (
    <section className="mt-6" aria-labelledby="health-here">
      <SectionLabel>
        <span id="health-here">Estimated adult health</span>
      </SectionLabel>
      <dl className="mt-2 grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 text-sm text-body">
        <dt>Asthma</dt>
        <dd className="tabular-nums">{pct(health.asthma_pct)}</dd>
        <dt>COPD</dt>
        <dd className="tabular-nums">{pct(health.copd_pct)}</dd>
        <dt>Coronary heart disease</dt>
        <dd className="tabular-nums">{pct(health.chd_pct)}</dd>
      </dl>
      <p className="mt-1.5 text-xs leading-relaxed text-faint">
        {health.source} {health.release_year} estimates for adults living here. They come from a
        statistical model, not from counting diagnoses, and that model uses race, so they are
        shown for context only and are never used to work out the result.
      </p>
    </section>
  );
}

export default function HexPanel({
  hex,
  onClose,
  /** Offer a link to this hexagon's own page.
   *
   *  Set on the map, where the panel is a transient thing over a canvas and the
   *  reader has no address for what they are reading. Left off on the page
   *  itself, where a link to the page you are on is noise.
   */
  standalone = false,
  /** Show the place name as the panel's heading. Off on the hexagon's own
   *  page, whose h1 already names it. */
  titled = true,
}: {
  hex: HexDetail;
  onClose: () => void;
  standalone?: boolean;
  titled?: boolean;
}) {
  const groups = Object.keys(GROUP_LABELS) as (keyof typeof GROUP_LABELS)[];
  const dropped = hex.indicators.filter((i) => !i.observed).length;
  const product = productOfComponents(hex.components);
  const scored = hex.score !== null;
  const caveatLeads = scored && leadsWithCaveat(hex.confidence.band);
  const unscored = hex.no_score_reason ? NO_SCORE_EXPLANATIONS[hex.no_score_reason] : null;
  const stateName = hex.state_name ?? "the state";

  const panel = useRef<HTMLElement>(null);

  // Selecting a hex moves the reader here, so the keyboard goes with them.
  // Without this, tabbing after a click continues from the map and walks the
  // whole panel in reverse before reaching anything in it.
  useEffect(() => {
    panel.current?.focus();
  }, [hex.h3]);

  return (
    <aside
      ref={panel}
      tabIndex={-1}
      aria-label={`Details for ${placeName(hex)}`}
      onKeyDown={(event) => {
        if (event.key === "Escape") onClose();
      }}
      className="flex h-full w-full flex-col bg-card focus:outline-none"
    >
      <header className="sticky top-0 z-10 border-b border-border bg-card/95 px-5 py-4 backdrop-blur-sm">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className={cn("text-lg leading-snug font-semibold", !titled && "sr-only")}>
              {placeName(hex)}
            </h2>
            {standalone && (
              // A map click is not an address. This gives the reader one they
              // can send to somebody, return to, or open without a map --
              // which is also the non-map path CS-401 asks for. The H3 index
              // itself is on that page; here it was a string of hex digits
              // under the place name that meant nothing to a reader.
              <TextLink to={`/hex/${hex.h3}`} className="mt-0.5 inline-block text-xs">
                Open a link to this area
              </TextLink>
            )}
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            aria-label="Close panel"
            className="-mt-1 -mr-1 shrink-0"
          >
            <X aria-hidden="true" />
          </Button>
        </div>

        {/* Section 12: for the low and insufficient bands the caveat leads,
            rather than sitting under a number the reader has already taken in.
            Only for a scored hexagon: an unscored one has no score to hedge. */}
        {caveatLeads && (
          <p className="mt-3.5 rounded-md border border-warn-border bg-warn-surface px-3 py-2.5 text-sm leading-relaxed text-warn-foreground">
            {bandReading(hex.confidence.band)}
          </p>
        )}

        {!scored ? (
          <div className="mt-3.5">
            <p className="text-base font-semibold text-foreground">
              Not ranked{unscored ? `: ${unscored.title.toLowerCase()}` : ""}
            </p>
            <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
              {/* The reason is what makes this useful, and it is optional on the
                  response. Without it the panel says so plainly. */}
              {unscored ? unscored.detail : "No reason was recorded for this area."}
            </p>
          </div>
        ) : hex.percentile === null ? (
          <div className="mt-3.5 flex items-end gap-3.5">
            <span className="text-[2.75rem] leading-none font-semibold tracking-tight text-foreground">
              {hex.score?.toFixed(1)}
            </span>
            <span className="pb-1 text-sm leading-snug text-muted-foreground">
              overall score out of 100; how it ranks in {stateName} wasn&apos;t reported
            </span>
          </div>
        ) : (
          // The rank leads because it is what the map coloured: the reader
          // clicked a colour, and the headline is that colour's rank, with the
          // swatch beside it, in words ("Top 5%") rather than as a percentile
          // ordinal most readers do not use. The 0-100 score follows.
          <div className="mt-3.5">
            <div className="flex items-center gap-3">
              <span
                aria-hidden="true"
                className="size-9 shrink-0 rounded-md ring-1 ring-black/15"
                style={{ backgroundColor: classColor(hex.percentile) }}
              />
              <div>
                <span className="text-[2rem] leading-none font-semibold tracking-tight text-foreground">
                  {rankShort(hex.percentile)}
                </span>
                <span className="ml-2 text-sm leading-snug text-muted-foreground">
                  {hex.percentile >= 50 ? "most" : "least"} burdened in {stateName}
                </span>
              </div>
            </div>
            <p className="mt-2 text-sm text-body">{rankSentence(hex.percentile, stateName)}</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Overall score{" "}
              <span className="font-semibold text-foreground">{hex.score?.toFixed(1)}</span> out
              of 100
            </p>
          </div>
        )}

        {scored && (
          <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1.5">
            <Badge variant={BAND_VARIANT[hex.confidence.band]}>
              {BAND_LABELS[hex.confidence.band]}
            </Badge>
            {dropped > 0 && (
              <span className="text-xs text-faint">
                No data for {dropped} of {hex.indicators.length} measures
              </span>
            )}
          </div>
        )}
      </header>

      <div className="px-5 py-5">
        {scored && hex.components.length > 0 && (
          <section>
            <SectionLabel as="h3">How we worked this out</SectionLabel>
            <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
              The result has two halves: how much pollution there is, and how vulnerable the
              people living here are. Each half is built from groups of measures, and each
              group&apos;s number is its average rank out of 100 (higher means more burdened).
            </p>

            <div className="mt-3">
              {hex.components.map((component) => (
                <ComponentWaterfall key={component.component} component={component} />
              ))}
            </div>

            <p className="mt-3.5 text-xs leading-relaxed text-faint">
              Each half is scored out of 10 by comparing it with the most burdened place in{" "}
              {stateName}. We don&apos;t show that top value here, so this is the one step you
              can&apos;t check from this page.
            </p>

            {product !== null && hex.components.length === 2 && (
              <div className="mt-3.5 rounded-md border border-border bg-sunken px-3.5 py-3">
                <p className="text-sm text-body">
                  {hex.components.map((c) => c.score.toFixed(1)).join(" × ")} ={" "}
                  <span className="font-semibold text-foreground">{product.toFixed(1)}</span>{" "}
                  <span className="text-muted-foreground">out of 100</span>
                </p>
                <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
                  We multiply the two halves instead of adding them, because pollution does the
                  most harm where people are least able to cope with it. So a place with heavy
                  pollution but few vulnerable residents can score lower than one that is
                  middling on both: roughly 19 against 36. That is intended.
                </p>
              </div>
            )}
          </section>
        )}

        {scored && (
          <>
            {hex.components.length > 0 && <Separator className="my-6" />}

            <ConfidenceBreakdown hex={hex} restate={!caveatLeads} />

            <section className="mt-6">
              <SectionLabel as="h3">Measure by measure</SectionLabel>
              <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
                Each bar shows how this area compares with the rest of {stateName}. The longer
                the bar, the more burdened it is than other places on that measure.
              </p>
            </section>

            {groups.map((group) => {
              const rows = hex.indicators.filter((i) => i.group === group);
              if (rows.length === 0) return null;
              return (
                <section key={group} className="mt-6">
                  <SectionLabel>{GROUP_LABELS[group]}</SectionLabel>
                  <ul className="mt-1 divide-y divide-border">
                    {rows.map((i) => (
                      <IndicatorRow
                        key={i.id}
                        indicator={i}
                        vintage={vintageFor(i, hex.data_vintage)}
                      />
                    ))}
                  </ul>
                </section>
              );
            })}
          </>
        )}

        {hex.facilities.length > 0 && (
          <FacilityList facilities={hex.facilities} total={hex.facility_count} />
        )}

        <PeopleHere hex={hex} />

        <HealthHere hex={hex} />

        <footer className="mt-6 border-t border-border pt-3.5 text-xs leading-relaxed text-faint">
          A high result reflects estimated pollution, nearby industry and a vulnerable
          population. It is not a finding of wrongdoing by any company.{" "}
          {/* The state is named from the hexagon rather than written in, because
              a rank here is a rank within this cell's state and no other. Where
              the API did not say which state that is, the claim is narrowed
              rather than guessed at. */}
          {hex.state_name
            ? `Rankings compare places within ${hex.state_name} only.`
            : "Rankings compare places within one state only."}{" "}
          Method version {hex.methodology_version}.
        </footer>
      </div>

      {/* Below the evidence, not above it. The drafting assistant is the last
          thing in the panel because a document should be written after reading
          what it would be about, and a reader who has scrolled past the
          confidence breakdown has seen how much the score is trusted. */}
      <DraftPanel hex={hex} />
    </aside>
  );
}
