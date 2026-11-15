// Natural-language analog search — the contract between the UI and the search backend.
//
// The UI POSTs an AnalogQuery to /api/search and expects AnalogResult[] back. Until a
// route exists there, findCandidates() falls back to the bundled sample set and says
// so (source: "sample"), so the prototype UI can be exercised end to end.
import { SITES, sampleCandidates, type Candidate } from "./candidates";

export type AnalogTarget = "moon" | "mars";

export interface AnalogQuery {
  text: string;
  target: AnalogTarget;
}

export interface AnalogResult {
  id: string;
  name: string;
  lat: number;
  lon: number;
  /** 0..1 similarity to the query */
  score: number;
  summary: string;
}

export class SearchUnavailableError extends Error {
  constructor() {
    super("The analog search service isn't connected yet.");
    this.name = "SearchUnavailableError";
  }
}

export async function searchAnalogs(query: AnalogQuery, signal?: AbortSignal): Promise<AnalogResult[]> {
  let res: Response;
  try {
    res = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(query),
      signal,
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new SearchUnavailableError();
  }
  if (res.status === 404 || res.status === 405) throw new SearchUnavailableError();
  if (!res.ok) throw new Error(`Search failed (${res.status})`);
  return (await res.json()) as AnalogResult[];
}

/** Example prompts, written from the challenge's dimensions of analogy. */
export const EXAMPLE_PROMPTS: Record<AnalogTarget, string[]> = {
  moon: [
    "Permanently shadowed terrain cold enough to trap water ice, like Shackleton crater",
    "Young basaltic lava tubes that could shelter a habitat from radiation",
    "Fine, sharp-grained volcanic ash that behaves like lunar regolith",
    "High-latitude ridges with near-continuous sunlight for solar power",
  ],
  mars: [
    "Hyper-arid, perchlorate-rich soils with almost no organic carbon",
    "Impact craters in permafrost with exposed ground ice",
    "Ancient lakebeds with clay minerals, like Jezero's delta",
    "Wind-carved yardangs and dust devils on cold basaltic plains",
  ],
};

export const QUICK_FILTERS: { label: string; prompt: string }[] = [
  { label: "Lava tubes", prompt: "Lava tubes and skylights that could shelter a crew" },
  { label: "Ground ice", prompt: "Permafrost and buried ground ice accessible near the surface" },
  { label: "Hyper-arid", prompt: "Hyper-arid desert soils with extreme UV and almost no life" },
  { label: "Impact craters", prompt: "Well-preserved impact craters with shocked rock and breccia" },
  { label: "Dust & wind", prompt: "Regions dominated by dust storms, dunes and aeolian erosion" },
];

export interface SearchOutcome {
  candidates: Candidate[];
  source: "live" | "sample";
}

/** Long enough for the search state to read, short enough to feel instant. */
const SAMPLE_LATENCY_MS = 1100;

export async function findCandidates(query: AnalogQuery, signal?: AbortSignal): Promise<SearchOutcome> {
  try {
    const results = await searchAnalogs(query, signal);
    const byId = new Map(SITES.map((s) => [s.id, s]));
    const candidates = results.flatMap((r) => {
      const site = byId.get(r.id);
      return site ? [site] : [];
    });
    return { candidates, source: "live" };
  } catch (e) {
    if (!(e instanceof SearchUnavailableError)) throw e;
  }
  await new Promise((r) => setTimeout(r, SAMPLE_LATENCY_MS));
  if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
  return { candidates: sampleCandidates(), source: "sample" };
}
