import { cn } from "@/lib/utils.ts";
import { PAGES } from "../lib/pages.ts";
import Link from "./Link.tsx";

export default function Nav({ path }: { path: string }) {
  return (
    <nav aria-label="Main" className="-mb-px flex items-center gap-x-1 overflow-x-auto">
      {PAGES.map((page) => {
        const current = page.path === path;
        return (
          <Link
            key={page.path}
            to={page.path}
            // aria-current is what tells a screen reader which page this is.
            // Colour alone would not, and colour alone is also what a reader
            // with low vision does not get. The weight change and the rule
            // under the label are the two visual carriers alongside it.
            aria-current={current ? "page" : undefined}
            className={cn(
              "border-b-2 px-2.5 py-3 text-sm whitespace-nowrap transition-colors",
              current
                ? "border-primary font-semibold text-foreground"
                : "border-transparent text-muted-foreground hover:border-border-strong hover:text-foreground",
            )}
          >
            {page.label}
          </Link>
        );
      })}
    </nav>
  );
}
