import data from "@/data/candidates.json";
import type { AnalogTarget } from "./search";
import type { Geology } from "./profile";

// Sample candidate set for the UI prototype. Imagery is NASA HLS via GIBS and the
// climate block is NASA POWER climatology, both fetched ahead of time so switching
// is instant. A real search backend would return candidates in the same shape.

export interface Climate {
  elevationM: number;
  meanTempC: number;
  coldestMonthMinC: number;
  hottestMonthMaxC: number;
  precipMmYr: number;
  solarKwhM2Day: number;
  humidityPct: number;
  windMs: number;
  source: string;
  period: string;
}

export interface CandidateSite {
  id: string;
  name: string;
  region: string;
  lat: number;
  lon: number;
  targets: AnalogTarget[];
  tags: string;
  summary: string;
  why: string[];
  breaks: string[];
  imagery: { source: string; layer: string; date: string; bbox: number[]; metersPerPixel: number };
  avgColor: [number, number, number];
  climate: Climate;
  /** Results from a live search carry their own traits (sample sites use the table in profile.ts) */
  traits?: Traits;
  /** Terrain shape match against the target, from the shape search */
  shape?: ShapeMatch;
  /** Limits this site falls outside of: returned only when too few sites met them all */
  missed?: string[];
  /** Measured per-cell values from the search service, keyed like the filter fields */
  metrics?: Record<string, number>;
  /** The Moon/Mars target's measured values in the same fields (from the search service) */
  targetMetrics?: Record<string, number>;
  /** The point this site was matched against (search service) */
  targetName?: string;
  targetLat?: number;
  targetLon?: number;
  /** The whole area the search covers: its cell count and cells per surface material */
  area?: { cells: number; materials: Record<string, number> };
  /** Dominant WRB 2006 soil group over the cell, and what it offers as an analog */
  soil?: { group: string; share: number; material: Geology; note: string } | null;
}

export interface Traits {
  slope: number;
  roughness: number;
  geology: Geology[];
  roadKm: number;
  protectedArea: boolean;
  access: string;
}

/** The target's and this cell's terrain over the same Earth-sized res-7 disk, mean height removed. */
export interface ShapeMatch {
  /** RMS height difference after turning the target to fit, metres */
  rmseM: number;
  rotationDeg: number;
  /** 0..1, 1 − rmse / target relief */
  score: number;
  reliefM: number;
  targetReliefM: number;
  pxM: number;
  /** Rows north to south; null outside the disk */
  target: (number | null)[][];
  match: (number | null)[][];
  dem: string;
  cell: string;
}

/** A search result. Relevance and match explanations arrive with the real search logic. */
export type Candidate = CandidateSite;

export const SITES = data as unknown as CandidateSite[];

// Live search results ("cell-<h3>") get their imagery from the search service.
const live = (id: string) => (id.startsWith("cell-") ? `/api/imagery/${id.slice(5)}` : null);
export const imageUrl = (id: string) => (live(id) ?? `/candidates/${id}`) + ".jpg";
export const thumbUrl = (id: string) => (live(id) ?? `/candidates/${id}`) + "_thumb.jpg";

/** Initial great-circle bearing (radians, clockwise from north) from a to b. */
export function bearing(a: { lat: number; lon: number }, b: { lat: number; lon: number }) {
  const r = Math.PI / 180;
  const φ1 = a.lat * r;
  const φ2 = b.lat * r;
  const Δλ = (b.lon - a.lon) * r;
  return Math.atan2(Math.sin(Δλ) * Math.cos(φ2), Math.cos(φ1) * Math.sin(φ2) - Math.sin(φ1) * Math.cos(φ2) * Math.cos(Δλ));
}

export function formatCoord(lat: number, lon: number) {
  const f = (v: number, p: string, n: string) => `${Math.abs(v).toFixed(2)}° ${v >= 0 ? p : n}`;
  return `${f(lat, "N", "S")}  ${f(lon, "E", "W")}`;
}
