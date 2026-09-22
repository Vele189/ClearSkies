import { PAGES } from "../lib/pages.ts";
import Link from "./Link.tsx";

export default function Nav({ path }: { path: string }) {
  return (
    <nav aria-label="Main" className="flex items-center gap-1">
      {PAGES.map((page) => {
        const current = page.path === path;
        return (
          <Link
            key={page.path}
            to={page.path}
            // aria-current is what tells a screen reader which page this is.
            // Colour alone would not, and colour alone is also what a reader
            // with low vision does not get.
            aria-current={current ? "page" : undefined}
            className={
              "rounded px-2 py-1 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 " +
              "focus-visible:outline-sky-700 " +
              (current
                ? "font-semibold text-slate-900 underline decoration-2 underline-offset-4"
                : "text-slate-600 hover:text-slate-900 hover:underline")
            }
          >
            {page.label}
          </Link>
        );
      })}
    </nav>
  );
}
