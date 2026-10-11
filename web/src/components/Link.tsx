import type { AnchorHTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/utils.ts";
import { isPlainClick, navigate } from "../lib/router.ts";

type Props = AnchorHTMLAttributes<HTMLAnchorElement> & {
  to: string;
  children: ReactNode;
};

/** An in-app link that is still a real anchor.
 *
 *  It renders `href`, so the status bar shows where it goes, the keyboard
 *  reaches it, "open in new tab" works, and a screen reader announces a link
 *  rather than a clickable div. Only a plain left click is intercepted.
 */
export default function Link({ to, children, onClick, ...rest }: Props) {
  return (
    <a
      href={to}
      onClick={(event) => {
        onClick?.(event);
        if (!isPlainClick(event)) return;
        event.preventDefault();
        navigate(to);
      }}
      {...rest}
    >
      {children}
    </a>
  );
}

/** How a link inside running text looks, in the one place it is decided.
 *
 *  Four pages previously carried their own copy of the same class string, and
 *  the fourth had already drifted. The underline is not negotiable and is not
 *  a hover affordance: WCAG 1.4.1 is failed by a link distinguished from its
 *  paragraph by colour alone, and `--color-link` against body copy is nowhere
 *  near the 3:1 that would let it stand on colour.
 */
const TEXT_LINK = "text-link underline decoration-from-font underline-offset-2 hover:no-underline";

export function TextLink({ to, className, children, ...rest }: Props) {
  return (
    <Link to={to} className={cn(TEXT_LINK, className)} {...rest}>
      {children}
    </Link>
  );
}

/** A link that leaves the site.
 *
 *  `noreferrer` rather than bare `noopener`: these go to regulators, Cornell's
 *  LII and the eCFR, and which hexagon a reader was looking at when they
 *  followed one is nobody else's business.
 */
export function ExternalLink({
  href,
  className,
  children,
  ...rest
}: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string; children: ReactNode }) {
  return (
    <a href={href} rel="noreferrer" className={cn(TEXT_LINK, className)} {...rest}>
      {children}
    </a>
  );
}
