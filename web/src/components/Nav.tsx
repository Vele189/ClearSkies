import { cn } from "@/lib/utils.ts";
import { PAGES } from "../lib/pages.ts";
import Link from "./Link.tsx";

export default function Nav({ path }: { path: string }) {
  return (
    <nav aria-label="Main" className="-mx-1.5 -mb-px flex items-center gap-x-0.5 overflow-x-auto sm:mx-0 sm:gap-x-1">
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
              // Tighter on a phone so all five fit across 390px rather than
              // the last one scrolling out of sight behind the edge.
              "border-b-2 px-1.5 py-3 text-[0.8125rem] whitespace-nowrap transition-colors sm:px-2.5 sm:text-sm",
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
