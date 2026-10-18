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
    expect(screen.getByText(/only compare places within Louisiana/i)).toBeInTheDocument();
  });

  it("says a low score is not a clean bill of health", () => {
    render(<MethodologyPage />);

    expect(
      screen.getByText(/data that would have shown pollution is missing/i),
    ).toBeInTheDocument();
  });

  it("says a score is not a finding of wrongdoing", () => {
    render(<MethodologyPage />);

    expect(screen.getByText(/follow their permits exactly still count toward it/i))
      .toBeInTheDocument();
  });

  it("explains that race is recorded and never scored, and what that costs", () => {
    render(<MethodologyPage />);

    expect(screen.getByText(/the answer would be built in/i)).toBeInTheDocument();
    // The cost is stated, not just the decision. A page that gave only the
    // reasoning would read as a defence rather than as a design note.
    expect(screen.getByText(/understate the burden\s+on a Black community/i)).toBeInTheDocument();
  });

  it("names the health-outcome gap as the largest one", () => {
    render(<MethodologyPage />);

    expect(screen.getByText(/biggest gap in the method/i)).toBeInTheDocument();
  });
});

describe("the model card", () => {
  it("does not present the fixture audit as production behaviour", () => {
    render(<ModelCardPage />);

    // CS-405 may report the audit; CS-308 forbids citing it as a statement
    // about production until it has been repeated on real scores.
    expect(
      screen.getByText(/used made-up areas, so it isn't yet a promise about the live site/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/rankings and population\s+figures were invented/i)).toBeInTheDocument();
  });

  it("names each guardrail and where it lives", () => {
    render(<ModelCardPage />);

    expect(screen.getByText(/can't be added to while the\s+site is running/i)).toBeInTheDocument();
    expect(screen.getByText(/whole draft is thrown away rather than shown with a warning/i)).toBeInTheDocument();
    expect(screen.getByText(/one rule that can't be\s+built into the format/i)).toBeInTheDocument();
  });

  it("states the refusal to draft from an untrusted hexagon", () => {
    render(<ModelCardPage />);

    expect(screen.getByText(/too little data about an area, the assistant refuses/i))
      .toBeInTheDocument();
  });

  it("says a Title VI claim is a complaint and not a lawsuit", () => {
    render(<ModelCardPage />);

    expect(screen.getByText(/not a case you can take to federal court/i))
      .toBeInTheDocument();
  });

  it("names the model and prompt version behind a draft", () => {
    render(<ModelCardPage />);

    expect(screen.getByText(/gpt-4o using version 3 of our instructions/i)).toBeInTheDocument();
  });
});

describe("the about page", () => {
  it("carries the disclaimer in its own words, not only in the footer", () => {
    render(<AboutPage />);

    expect(screen.getByText(/This is not legal advice/i)).toBeInTheDocument();
    expect(screen.getByText(/There is no send\s+button/i)).toBeInTheDocument();
  });

  it("states the scope the map does not cover", () => {
    render(<AboutPage />);

    expect(screen.getByText(/Louisiana only/i)).toBeInTheDocument();
  });
});
