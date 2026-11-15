import data from "@/data/candidates.json";
import type { AnalogTarget } from "./search";

// Sample candidate set for the UI prototype. Imagery is NASA HLS via GIBS and the
// climate block is NASA POWER climatology, both fetched ahead of time so switching
// is instant. A real search backend would return candidates in the same shape.

export interface Climate {
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
}

/** A search result. Relevance and match explanations arrive with the real search logic. */
export type Candidate = CandidateSite;

export const SITES = data as unknown as CandidateSite[];

export const imageUrl = (id: string) => `/candidates/${id}.jpg`;
export const thumbUrl = (id: string) => `/candidates/${id}_thumb.jpg`;

/**
 * UI prototype: no query matching yet. Every search returns the same sample set in a
 * fixed order, chosen to show a spread of terrains, climates and both target bodies.
 */
const SAMPLE_ORDER = ["haughton", "dallol", "lut", "bockfjord", "craters-of-the-moon", "yungay", "dalangtan"];

export function sampleCandidates(order = SAMPLE_ORDER): Candidate[] {
  return order.flatMap((id) => SITES.filter((s) => s.id === id));
}

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
