// Analog search: the contract between the UI and the search backend.
//
// The UI POSTs the target point (and the researcher's limits) to /api/search and gets
// candidate sites back, ranked by terrain shape. If the service isn't reachable,
// findCandidates() falls back to the bundled sample set and says so (source: "sample").
import type { Candidate } from "./candidates";
import { targetById } from "./catalog";
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

export class SearchUnavailableError extends Error {
  constructor() {
    super("The analog search service isn't connected yet.");
    this.name = "SearchUnavailableError";
  }
}

/** The Moon or Mars point a query is about: a catalog place or a dropped pin ("moon:-89.6,129.8"). */
export function targetPoint(q: AnalogQuery): { lat: number; lon: number } | null {
  const t = q.place ? targetById(q.place) : undefined;
  if (t) return { lat: t.lat, lon: t.lon };
  const m = q.place?.match(/^\w+:(-?[\d.]+),(-?[\d.]+)$/);
  return m ? { lat: Number(m[1]), lon: Number(m[2]) } : null;
}

export async function searchAnalogs(query: AnalogQuery, signal?: AbortSignal): Promise<Candidate[]> {
  const at = targetPoint(query);
  if (!at) throw new SearchUnavailableError();
  let res: Response;
  try {
    res = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body: query.target, lat: at.lat, lon: at.lon, name: query.place && targetById(query.place)?.name, filters: query.filters }),
      signal,
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new SearchUnavailableError();
  }
  // 404/405: no route; 500/502/504: the dev proxy couldn't reach the service
  if ([404, 405, 500, 502, 503, 504].includes(res.status)) throw new SearchUnavailableError();
  if (!res.ok) throw new Error(`Search failed (${res.status})`);
  const data = (await res.json()) as { sites: Candidate[]; target?: { metrics?: Record<string, number> } };
  return data.sites.map((s) => ({ ...s, targetMetrics: data.target?.metrics }));
}

/** Where the analogy holds and breaks, written by the language model from the measured values. */
export interface Analysis {
  verdict: string;
  holds: string[];
  breaks: string[];
  test: string;
  model: string;
}

const analyses = new Map<string, Promise<Analysis>>();

export function analyse(c: Candidate, body: AnalogTarget): Promise<Analysis> {
  const key = `${body}:${c.targetLat}:${c.targetLon}:${c.id}`;
  let p = analyses.get(key);
  if (!p) {
    // The elevation grids aren't needed for the reasoning, just the measured numbers
    const site = { ...c, shape: c.shape && { ...c.shape, target: [], match: [] } };
    p = fetch("/api/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body, targetName: c.targetName ?? "the target", targetMetrics: c.targetMetrics ?? {}, site }),
    }).then((r) => (r.ok ? (r.json() as Promise<Analysis>) : Promise.reject(new Error(String(r.status)))));
    p.catch(() => analyses.delete(key));
    analyses.set(key, p);
  }
  return p;
}

export type Source = "live" | "sample";

export interface SearchOutcome {
  candidates: Candidate[];
  source: Source;
}

/** Long enough for the search state to read, short enough to feel instant. */
const SAMPLE_LATENCY_MS = 1100;

export async function findCandidates(query: AnalogQuery, signal?: AbortSignal): Promise<SearchOutcome> {
  try {
    return { candidates: await searchAnalogs(query, signal), source: "live" };
  } catch (e) {
    if (!(e instanceof SearchUnavailableError)) throw e;
  }
  await new Promise((r) => setTimeout(r, SAMPLE_LATENCY_MS));
  if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
  // Demo ranking over the bundled sample sites (lib/profile).
  return { candidates: rank(query), source: "sample" };
}
