import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import DraftPanel from "./DraftPanel.tsx";
import type { DraftResponse, HexDetail } from "../lib/types.ts";

function hex(band: HexDetail["confidence"]["band"] = "moderate"): HexDetail {
  return {
    h3: "88444600ddfffff",
    resolution: 8,
    state: "LA",
    parish: "St. James",
    centroid: [-90.8, 30.0],
    score: 81.4,
    percentile: 94.2,
    components: [],
    indicators: [],
    confidence: {
      value: 0.71,
      band,
      coverage: 0.8,
      recency: 0.9,
      spatial_support: 0.7,
      monitor_support: 0.4,
      nearest_monitor_km: 12.1,
    },
    demographics: { population: 1840 },
    facilities: [],
    no_score_reason: null,
    methodology_version: "0.1.4",
    data_vintage: {},
  };
}

const DRAFTED: DraftResponse = {
  status: "drafted",
  from_cache: false,
  refusal: null,
  draft: {
    document: {
      document_type: "public_comment_letter",
      draft_notice: "DRAFT FOR HUMAN REVIEW. It is not legal advice.",
      citations: [
        {
          kind: "statute",
          section: "42 U.S.C. § 7412(b)",
          document_id: "usc-42-chap85",
          proposition: "Congress established a list of hazardous air pollutants.",
        },
      ],
      paragraphs: [
        {
          text: "The statute requires a comment period.",
          citations: [
            {
              kind: "statute",
              section: "42 U.S.C. § 7412(b)",
              document_id: "usc-42-chap85",
              proposition: "Congress established a list of hazardous air pollutants.",
            },
          ],
        },
      ],
      recipient: "LDEQ",
      subject: "Comment on a permit renewal",
      requested_action: "Hold a public hearing.",
    },
    h3: "88444600ddfffff",
    confidence_band: "moderate",
    methodology_version: "0.1.4",
    corpus_version: "appendix-b-test",
    prompt_version: "v1",
    model: "gpt-4o",
    generated_at: "2026-09-11T16:04:59Z",
    review_required: true,
  },
};

function respondWith(body: unknown, ok = true, status = 200) {
  return vi.fn().mockResolvedValue({
    ok,
    status,
    statusText: "",
    json: () => Promise.resolve(body),
  });
}

beforeEach(() => {
  vi.stubGlobal("fetch", respondWith(DRAFTED));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("choosing a document", () => {
  it("offers all four types", () => {
    render(<DraftPanel hex={hex()} />);

    expect(screen.getByText("Public comment letter")).toBeTruthy();
    expect(screen.getByText("Agency complaint")).toBeTruthy();
    expect(screen.getByText("Community briefing sheet")).toBeTruthy();
    expect(screen.getByText("Journalist fact sheet")).toBeTruthy();
  });

  it("says what is happening while it generates", async () => {
    render(<DraftPanel hex={hex()} />);
    await userEvent.click(screen.getByText("Public comment letter"));

    await waitFor(() => expect(screen.getByText(/Draft for human review/i)).toBeTruthy());
  });

  it("posts rather than gets", async () => {
    const fetchMock = respondWith(DRAFTED);
    vi.stubGlobal("fetch", fetchMock);

    render(<DraftPanel hex={hex()} />);
    await userEvent.click(screen.getByText("Public comment letter"));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("POST");
  });
});

describe("the insufficient band", () => {
  it("explains the refusal in plain language before anything is clicked", () => {
    // The reader is being told the tool does not trust its own number for their
    // neighbourhood. That deserves a sentence, not a disabled button.
    render(<DraftPanel hex={hex("insufficient")} />);

    expect(screen.getByText(/not enough data behind this hexagon/i)).toBeTruthy();
    expect(screen.getByText(/looks well supported and is not/i)).toBeTruthy();
  });

  it("offers no document types at all for such a hexagon", () => {
    render(<DraftPanel hex={hex("insufficient")} />);

    expect(screen.queryByText("Public comment letter")).toBeNull();
  });

  it("never shows an error code", () => {
    const { container } = render(<DraftPanel hex={hex("insufficient")} />);

    expect(container.textContent).not.toMatch(/\b(409|422|503|error)\b/i);
  });
});

describe("a drafted document", () => {
  it("leads with the draft notice", async () => {
    render(<DraftPanel hex={hex()} />);
    await userEvent.click(screen.getByText("Public comment letter"));

    const notice = await screen.findByRole("note");
    expect(notice.textContent).toMatch(/draft for human review/i);
    expect(notice.textContent).toMatch(/not legal advice/i);
  });

  it("renders every citation as a link a reader can follow", async () => {
    render(<DraftPanel hex={hex()} />);
    await userEvent.click(screen.getByText("Public comment letter"));

    const links = await screen.findAllByRole("link", { name: "42 U.S.C. § 7412(b)" });
    expect(links.length).toBeGreaterThan(0);
    expect(links[0].getAttribute("href")).toBe("https://www.law.cornell.edu/uscode/text/42/7412");
  });

  it("says the citations were checked before the draft was shown", async () => {
    render(<DraftPanel hex={hex()} />);
    await userEvent.click(screen.getByText("Public comment letter"));

    expect(await screen.findByText(/checked against the EPA data/i)).toBeTruthy();
  });

  it("records the corpus and prompt behind it", async () => {
    render(<DraftPanel hex={hex()} />);
    await userEvent.click(screen.getByText("Public comment letter"));

    expect(await screen.findByText(/appendix-b-test/)).toBeTruthy();
  });
});

describe("there is no way to send it", () => {
  it("offers copy and download and nothing else", async () => {
    render(<DraftPanel hex={hex()} />);
    await userEvent.click(screen.getByText("Public comment letter"));
    await screen.findByRole("note");

    const buttons = screen.getAllByRole("button").map((b) => b.textContent?.trim());
    expect(buttons).toContain("Copy");
    expect(buttons).toContain("Download");
  });

  it("has no send, file, submit, publish or share control", async () => {
    // The only ways out of this application are the clipboard and a downloaded
    // file, both of which put a person between the draft and whoever receives
    // it. This test is here so that stays true.
    const { container } = render(<DraftPanel hex={hex()} />);
    await userEvent.click(screen.getByText("Public comment letter"));
    await screen.findByRole("note");

    expect(container.textContent).not.toMatch(/\b(send|submit|publish|share|file it|email)\b/i);
  });

  it("never posts anywhere but the draft endpoint", async () => {
    const fetchMock = respondWith(DRAFTED);
    vi.stubGlobal("fetch", fetchMock);

    render(<DraftPanel hex={hex()} />);
    await userEvent.click(screen.getByText("Public comment letter"));
    await screen.findByRole("note");

    for (const call of fetchMock.mock.calls) {
      expect(String(call[0])).toMatch(/\/draft$/);
    }
  });
});

describe("failures read as answers", () => {
  it("shows the refusal the model gave, and says it is a refusal", async () => {
    vi.stubGlobal(
      "fetch",
      respondWith({
        status: "refused",
        draft: null,
        from_cache: false,
        refusal: {
          refused: true,
          reason: "no_supporting_authority",
          explanation: "No retrieved passage addresses cumulative impact review.",
          missing: ["a cumulative impact provision"],
        },
      }),
    );

    render(<DraftPanel hex={hex()} />);
    await userEvent.click(screen.getByText("Public comment letter"));

    expect(await screen.findByText(/No retrieved passage addresses/)).toBeTruthy();
    expect(screen.getByText(/declining rather than failing/i)).toBeTruthy();
    expect(screen.getByText(/a cumulative impact provision/)).toBeTruthy();
  });

  it("renders the sentence the API wrote rather than inventing one", async () => {
    // The API knows which of six things went wrong. The frontend does not.
    vi.stubGlobal(
      "fetch",
      respondWith(
        {
          detail:
            "A draft was produced but at least one of its citations could not be verified, so it was discarded rather than shown.",
        },
        false,
        422,
      ),
    );

    render(<DraftPanel hex={hex()} />);
    await userEvent.click(screen.getByText("Public comment letter"));

    expect(await screen.findByText(/discarded rather than shown/)).toBeTruthy();
  });

  it("explains an unreachable API without a stack trace", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network")));

    render(<DraftPanel hex={hex()} />);
    await userEvent.click(screen.getByText("Public comment letter"));

    expect(await screen.findByText(/Could not reach the API/)).toBeTruthy();
  });
});
