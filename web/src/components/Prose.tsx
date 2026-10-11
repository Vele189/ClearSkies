import type { ReactNode } from "react";

import { cn } from "@/lib/utils.ts";

/** The written pages' typography, in the one place its measure is decided.
 *
 *  Methodology, the model card and About are argument rather than interface.
 *  They are read for minutes, so they are set in the serif at a size and
 *  leading meant for that, and held to a measure: `docs/methodology.md` is
 *  long, and a 120-character line loses the reader's place on every return
 *  sweep. WCAG 1.4.8 puts the ceiling at 80 characters and `.measure` sits
 *  under it at roughly 68.
 *
 *  The interface itself stays in the sans. A reader should be able to tell the
 *  project's prose from its controls without reading either.
 */
export function Prose({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "measure space-y-4 font-serif text-[1.0625rem] leading-[1.7] text-body",
        className,
      )}
    >
      {children}
    </div>
  );
}

/** The page's h1, plus the one-sentence standfirst under it where a page has
 *  one. Keeping them together is what stops the gap between them being set
 *  three different ways on three pages. */
export function PageTitle({ children, lede }: { children: ReactNode; lede?: ReactNode }) {
  return (
    <header className="mb-8 border-b border-border pb-6">
      <h1 className="text-3xl leading-tight font-semibold text-balance sm:text-4xl">
        {children}
      </h1>
      {lede !== undefined && (
        <p className="measure mt-3 font-serif text-lg leading-relaxed text-muted-foreground">
          {lede}
        </p>
      )}
    </header>
  );
}

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-10">
      <h2 className="mb-3 text-xl font-semibold">{title}</h2>
      <Prose>{children}</Prose>
    </section>
  );
}

/** A labelled point: the label is the claim and the sentence after it is the
 *  support. Rendered as a run-in heading rather than a list item, because it
 *  is a paragraph with its first phrase emphasised and marking it up as a
 *  heading would put it in the document outline. */
export function Point({ label, children }: { label: string; children: ReactNode }) {
  return (
    <p>
      <strong className="font-semibold text-foreground">{label}</strong> {children}
    </p>
  );
}

/** An identifier a reader compares or copies: an H3 index, a SHA prefix, an
 *  indicator id. Monospace, and never below `--color-faint`. */
export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span className={cn("font-mono text-[0.9em] tracking-tight break-all", className)}>
      {children}
    </span>
  );
}
