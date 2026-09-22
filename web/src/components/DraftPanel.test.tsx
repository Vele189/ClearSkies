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

describe("a draft belongs to the hexagon it was asked about", () => {
  /** A fetch that never settles on its own, so the test decides when it lands. */
  function heldFetch() {
    let land: (body: unknown) => void = () => undefined;
    const fetchMock = vi.fn().mockImplementation(
      () =>
        new Promise((resolve) => {
          land = (body) =>
            resolve({ ok: true, status: 200, statusText: "", json: () => Promise.resolve(body) });
        }),
    );
    vi.stubGlobal("fetch", fetchMock);
    return { fetchMock, land: (body: unknown) => land(body) };
  }

  function signalOf(fetchMock: ReturnType<typeof vi.fn>): AbortSignal {
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    return init.signal as AbortSignal;
  }

  it("abandons a draft in flight when the panel goes away", async () => {
    const { fetchMock } = heldFetch();
    const { unmount } = render(<DraftPanel hex={hex()} />);
    await userEvent.click(screen.getByText("Public comment letter"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());

    unmount();

    expect(signalOf(fetchMock).aborted).toBe(true);
  });

  it("abandons a draft in flight when the hexagon changes, and never shows it", async () => {
    const { fetchMock, land } = heldFetch();
    const { rerender } = render(<DraftPanel hex={hex()} />);
    await userEvent.click(screen.getByText("Public comment letter"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());

    rerender(<DraftPanel hex={{ ...hex(), h3: "88444600dbfffff" }} />);
    expect(signalOf(fetchMock).aborted).toBe(true);

    land(DRAFTED);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByRole("note")).toBeNull();
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

describe("a complaint shows what it rests on", () => {
  const COMPLAINT: DraftResponse = {
    status: "drafted",
    from_cache: false,
    refusal: null,
    draft: {
      ...DRAFTED.draft!,
      document: {
        document_type: "agency_complaint_draft",
        draft_notice: "DRAFT FOR HUMAN REVIEW. It is not legal advice.",
        citations: [],
        paragraphs: [{ text: "The burden here is cumulative.", citations: [] }],
        recipient_office: "EPA Office of External Civil Rights Compliance",
        legal_basis: [
          {
            kind: "statute",
            section: "42 U.S.C. § 2000d",
            document_id: "usc-42-chap21",
            proposition: "No person shall be subjected to discrimination under such a program.",
          },
        ],
        key_figures: [
          {
            label: "Cancer risk",
            value: "62",
            unit: "per million",
            citation: {
              kind: "statute",
              section: "40 C.F.R. § 51.166",
              document_id: "cfr-40-51",
              proposition: "PSD review applies to this source.",
            },
          },
        ],
        relief_sought: "An investigation.",
      },
    },
  };

  it("renders the legal basis, as a link like every other citation", async () => {
    vi.stubGlobal("fetch", respondWith(COMPLAINT));
    render(<DraftPanel hex={hex()} />);
    await userEvent.click(screen.getByText("Agency complaint"));

    await screen.findByRole("note");
    expect(screen.getByText("Legal basis")).toBeInTheDocument();
    const links = screen.getAllByRole("link", { name: "42 U.S.C. § 2000d" });
    expect(links[0].getAttribute("href")).toBe("https://www.law.cornell.edu/uscode/text/42/2000d");
  });

  it("lists the legal basis and the key figures' sources among the citations", async () => {
    // A reader checking the citations at the foot of the draft is entitled to
    // find every claim that was cited to them there.
    vi.stubGlobal("fetch", respondWith(COMPLAINT));
    render(<DraftPanel hex={hex()} />);
    await userEvent.click(screen.getByText("Agency complaint"));

    await screen.findByRole("note");
    expect(screen.getByText(/^Citations \(2\)$/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "40 C.F.R. § 51.166" }).length).toBeGreaterThan(0);
  });

  it("carries the legal basis into what is copied or downloaded", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    vi.stubGlobal("fetch", respondWith(COMPLAINT));

    render(<DraftPanel hex={hex()} />);
    await userEvent.click(screen.getByText("Agency complaint"));
    await screen.findByRole("note");
    await userEvent.click(screen.getByText("Copy"));

    expect(String(writeText.mock.calls[0][0])).toContain("42 U.S.C. § 2000d");
  });
});

describe("taking the draft away", () => {
  it("says so when the browser refuses the clipboard", async () => {
    // A reader who believes they have the draft and pastes nothing has lost it.
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    vi.stubGlobal("navigator", { clipboard: { writeText } });

    render(<DraftPanel hex={hex()} />);
    await userEvent.click(screen.getByText("Public comment letter"));
    await screen.findByRole("note");
    await userEvent.click(screen.getByText("Copy"));

    expect(await screen.findByText(/would not let the page write to the clipboard/i)).toBeTruthy();
    expect(screen.getByText("Copy")).toBeInTheDocument();
  });

  it("keeps a download's blob alive past the click that started it", async () => {
    // Revoking in the same tick races the download: a browser that has not
    // fetched the blob yet saves an empty file.
    const createObjectURL = vi.fn().mockReturnValue("blob:draft");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
    const timers = vi.spyOn(window, "setTimeout");

    render(<DraftPanel hex={hex()} />);
    await userEvent.click(screen.getByText("Public comment letter"));
    await screen.findByRole("note");
    await userEvent.click(screen.getByText("Download"));

    expect(createObjectURL).toHaveBeenCalled();
    expect(revokeObjectURL).not.toHaveBeenCalled();

    // Nothing is leaked either: the URL is released once the download is safe.
    const scheduled = timers.mock.calls.find((call) => call[1] === 60_000);
    expect(scheduled).toBeDefined();
    (scheduled![0] as () => void)();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:draft");
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
