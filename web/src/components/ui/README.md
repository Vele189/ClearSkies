# ui/

shadcn/ui components, generated with the "new-york" style and then adapted in
two ways that matter:

1. **They use this project's semantic tokens** (`foreground`, `body`,
   `muted-foreground`, `faint`, `border`, `link`, `ok-*`, `warn-*`, `bad-*`)
   rather than shadcn's stock `--primary`/`--muted` set alone. Every one of
   those resolves to a Tailwind palette entry in `src/index.css`, which is what
   lets `src/contrast.test.ts` hold them to WCAG AA.

2. **They carry no `focus-visible:` classes.** `src/index.css` declares one
   focus indicator for the whole document, so a control cannot ship without
   one. Re-adding per-component rings would double the outline.

`components.json` is configured, so `npx shadcn@latest add <name>` works for
anything not here yet. Expect to apply the two changes above to whatever it
writes.
