import type { ReactNode } from "react";

/** A readable column of text, in the one place its measure is decided.
 *
 *  The written pages share a shape, and repeating the classes on each of them
 *  is how three pages end up with three line heights.
 */
export function Prose({ children }: { children: ReactNode }) {
  return <div className="space-y-4 text-sm leading-6 text-slate-700">{children}</div>;
}

export function PageTitle({ children }: { children: ReactNode }) {
  return <h1 className="mb-4 text-xl font-semibold text-slate-900">{children}</h1>;
}

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-8">
      <h2 className="mb-2 text-base font-semibold text-slate-900">{title}</h2>
      <Prose>{children}</Prose>
    </section>
  );
}

export function Point({ label, children }: { label: string; children: ReactNode }) {
  return (
    <p>
      <strong className="font-semibold text-slate-900">{label}</strong> {children}
    </p>
  );
}
