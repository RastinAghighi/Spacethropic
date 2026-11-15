// Analog search: the contract between the UI and the search backend.
//
// The UI POSTs an AnalogQuery to /api/search and expects AnalogResult[] back. Until a
// route exists there, findCandidates() falls back to the bundled sample set and says
// so (source: "sample"), so the prototype UI can be exercised end to end.
import { SITES, type Candidate } from "./candidates";
import { rank, type Filters } from "./profile";

export type AnalogTarget = "moon" | "mars";

export interface AnalogQuery {
  /** Readable summary of the query, shown in the site view. */
  text: string;
  target: AnalogTarget;
  /** Mirror: the Moon/Mars site id, or "<body>:<lat>,<lon>" for a dropped pin */
  place?: string;
  /** Skip well-studied analog sites */
  discovery?: boolean;
  /** Researcher's limits and priorities from the refine drawers */
  filters?: Filters;
  /** Label for this step on the research trail */
  step?: string;
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
  // Demo ranking over the bundled sample sites (lib/profile).
  return { candidates: rank(query), source: "sample" };
}
