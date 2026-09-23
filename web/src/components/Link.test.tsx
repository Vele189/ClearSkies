import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import Link from "./Link.tsx";

describe("Link", () => {
  it("is a real anchor carrying its destination", async () => {
    render(<Link to="/provenance">Sources</Link>);

    // Not a clickable div: the status bar shows where it goes, the keyboard
    // reaches it, and a screen reader announces a link.
    expect(screen.getByRole("link", { name: "Sources" })).toHaveAttribute(
      "href",
      "/provenance",
    );
  });

  it("routes a plain click without reloading", async () => {
    render(<Link to="/provenance">Sources</Link>);

    await userEvent.click(screen.getByRole("link", { name: "Sources" }));

    expect(window.location.pathname).toBe("/provenance");
  });

  it("leaves a modified click to the browser", async () => {
    const onClick = vi.fn();
    render(
      <Link to="/provenance" onClick={onClick}>
        Sources
      </Link>,
    );

    // Ctrl-click is the reader asking for a new tab. Swallowing it is what
    // makes a hand-rolled router irritating to use. fireEvent rather than
    // userEvent, because the modifier has to be on the click event itself.
    fireEvent.click(screen.getByRole("link", { name: "Sources" }), { ctrlKey: true });

    expect(onClick).toHaveBeenCalled();
    expect(window.location.pathname).toBe("/");
  });
});
