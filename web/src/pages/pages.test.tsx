import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AboutPage from "./AboutPage.tsx";
import MethodologyPage from "./MethodologyPage.tsx";
import ModelCardPage from "./ModelCardPage.tsx";

describe("the methodology page", () => {
  it("carries the two caveats a reader needs to read the map at all", () => {
    render(<MethodologyPage />);

    // The multiplicative surprise, which section 10 requires be stated.
    expect(screen.getByText(/scores about 19/)).toBeInTheDocument();
    expect(screen.getByText(/Louisiana percentiles/)).toBeInTheDocument();
  });

  it("says a low score is not a clean bill of health", () => {
    render(<MethodologyPage />);

    expect(
      screen.getByText(/indicators that would have caught the burden are missing/i),
    ).toBeInTheDocument();
  });

  it("says a score is not a finding of wrongdoing", () => {
    render(<MethodologyPage />);

    expect(screen.getByText(/within their permits contribute to burden scores/i))
      .toBeInTheDocument();
  });

  it("explains that race is recorded and never scored, and what that costs", () => {
    render(<MethodologyPage />);

    expect(screen.getByText(/would be circular/i)).toBeInTheDocument();
    // The cost is stated, not just the decision. A page that gave only the
    // reasoning would read as a defence rather than as a design note.
    expect(screen.getByText(/understates burden in a Black community/i)).toBeInTheDocument();
  });

  it("names the health-outcome gap as the largest one", () => {
    render(<MethodologyPage />);

    expect(screen.getByText(/single largest gap/i)).toBeInTheDocument();
  });
});

describe("the model card", () => {
  it("does not present the fixture audit as production behaviour", () => {
    render(<ModelCardPage />);

    // CS-405 may report the audit; CS-308 forbids citing it as a statement
    // about production until it has been repeated on real scores.
    expect(
      screen.getByText(/ran on fixture hexagons, and is not yet a statement about production/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/scores and demographics were invented/i)).toBeInTheDocument();
  });

  it("names each guardrail and where it lives", () => {
    render(<ModelCardPage />);

    expect(screen.getByText(/sealed version refuses writes at the database/i)).toBeInTheDocument();
    expect(screen.getByText(/discarded whole, not shown with a warning/i)).toBeInTheDocument();
    expect(screen.getByText(/cannot be made structural/i)).toBeInTheDocument();
  });

  it("states the refusal to draft from an untrusted hexagon", () => {
    render(<ModelCardPage />);

    expect(screen.getByText(/insufficient confidence band cannot be drafted from/i))
      .toBeInTheDocument();
  });

  it("says a Title VI claim is a complaint and not a lawsuit", () => {
    render(<ModelCardPage />);

    expect(screen.getByText(/not a case that can be filed in federal court/i))
      .toBeInTheDocument();
  });

  it("names the model and prompt version behind a draft", () => {
    render(<ModelCardPage />);

    expect(screen.getByText(/gpt-4o under prompt version v3/i)).toBeInTheDocument();
  });
});

describe("the about page", () => {
  it("carries the disclaimer in its own words, not only in the footer", () => {
    render(<AboutPage />);

    expect(screen.getByText(/This is not legal advice/i)).toBeInTheDocument();
    expect(screen.getByText(/no send button and no publish path/i)).toBeInTheDocument();
  });

  it("states the scope the map does not cover", () => {
    render(<AboutPage />);

    expect(screen.getByText(/Louisiana only/i)).toBeInTheDocument();
  });
});
