import type { AnchorHTMLAttributes, ReactNode } from "react";

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
