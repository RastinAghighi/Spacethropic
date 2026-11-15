import { useSyncExternalStore } from "react";
import { bearing, type Candidate } from "./candidates";
import type { AnalogQuery } from "./search";
import { research } from "./research";

// Page-level choreography shared between the 3D scene and the DOM overlay.
//
//   globe ──search──▶ searching ──results──▶ diving ──▶ site
//   site  ──search──▶ searching ──results──▶ site (punch-slide to the new top result)
//   site  ──back────▶ surfacing ──▶ globe
//
// Each set of results is a step on the research trail: the first is the broad physical
// match, every refine from the site view appends one, and any step can be revisited.

export type Mode = "globe" | "searching" | "diving" | "site" | "surfacing";

export interface TrailStep {
  label: string;
  query: AnalogQuery;
  results: Candidate[];
}

/** Timelines, in seconds from the transition's start. The globe camera and the satellite renderer both read these. */
export const DIVE = { total: 2.4, panel: 1.55, tray: 1.7 } as const;
export const SURFACE = { total: 2.9, bar: 1.35 } as const;
export const SWITCH = { total: 1.85 } as const;

interface UiState {
  /** Every texture, the star catalog and all shaders are uploaded and compiled. */
  ready: boolean;
  /** The intro flight has landed on the day side — time to bring in the UI. */
  landed: boolean;
  mode: Mode;
  /** Mode the current search started from. */
  searchFrom: "globe" | "site";
  query: AnalogQuery | null;
  results: Candidate[];
  source: "live" | "sample";
  active: number;
  /** performance.now() when the current dive/surface/switch began. */
  transitionAt: number;
  /** Increments on every candidate switch; consumers key animations off it. */
  switchSeq: number;
  /** Screen direction of travel for a switch, from the great-circle bearing (x right, y down). */
  switchDir: [number, number];
  /** While surfacing: the search bar has started opening back up. */
  barOpen: boolean;
  trail: TrailStep[];
  /** Index of the step on screen */
  trailAt: number;
}

let state: UiState = {
  ready: false,
  landed: false,
  mode: "globe",
  searchFrom: "globe",
  query: null,
  results: [],
  source: "sample",
  active: 0,
  transitionAt: 0,
  switchSeq: 0,
  switchDir: [1, 0],
  barOpen: true,
  trail: [],
  trailAt: 0,
};
const listeners = new Set<() => void>();
let timer: ReturnType<typeof setTimeout> | undefined;
let barTimer: ReturnType<typeof setTimeout> | undefined;

function set(patch: Partial<UiState>) {
  state = { ...state, ...patch };
  listeners.forEach((l) => l());
}

function after(seconds: number, fn: () => void) {
  clearTimeout(timer);
  timer = setTimeout(fn, seconds * 1000);
}

function directionTo(from: Candidate | undefined, to: Candidate): [number, number] {
  if (!from) return [1, 0];
  const b = bearing(from, to);
  return [Math.sin(b), -Math.cos(b)];
}

export const ui = {
  get: () => state,
  subscribe(l: () => void) {
    listeners.add(l);
    return () => {
      listeners.delete(l);
    };
  },
  setReady: () => !state.ready && set({ ready: true }),
  setLanded: () => !state.landed && set({ landed: true }),

  startSearch(query: AnalogQuery) {
    clearTimeout(timer);
    const searchFrom = state.mode === "site" ? "site" : "globe";
    if (searchFrom === "globe") research.load(query.filters);
    set({ mode: "searching", query, searchFrom });
  },

  searchFailed() {
    set({ mode: state.searchFrom });
  },

  showResults(results: Candidate[], source: "live" | "sample") {
    if (!results.length) return set({ mode: state.searchFrom });
    const now = performance.now();
    const q = state.query!;
    const step: TrailStep = { label: q.step ?? q.text, query: q, results };
    research.load(q.filters);
    if (state.searchFrom === "site") {
      const from = state.results[state.active];
      const trail = [...state.trail.slice(0, state.trailAt + 1), step];
      set({
        trail,
        trailAt: trail.length - 1,
        mode: "site",
        results,
        source,
        active: 0,
        transitionAt: now,
        switchSeq: state.switchSeq + 1,
        switchDir: directionTo(from, results[0]),
      });
      return;
    }
    set({ mode: "diving", results, source, active: 0, transitionAt: now, trail: [step], trailAt: 0 });
    after(DIVE.total, () => set({ mode: "site" }));
  },

  select(index: number) {
    if (state.mode !== "site" || index === state.active || !state.results[index]) return;
    set({
      active: index,
      transitionAt: performance.now(),
      switchSeq: state.switchSeq + 1,
      switchDir: directionTo(state.results[state.active], state.results[index]),
    });
  },

  /** Revisit an earlier (or later) step of the research trail. */
  restore(i: number) {
    const step = state.trail[i];
    if (state.mode !== "site" || i === state.trailAt || !step) return;
    research.load(step.query.filters);
    set({
      query: step.query,
      results: step.results,
      active: 0,
      trailAt: i,
      transitionAt: performance.now(),
      switchSeq: state.switchSeq + 1,
      switchDir: directionTo(state.results[state.active], step.results[0]),
    });
  },

  surface() {
    if (state.mode !== "site") return;
    research.open(null);
    set({ mode: "surfacing", transitionAt: performance.now(), barOpen: false });
    clearTimeout(barTimer);
    barTimer = setTimeout(() => set({ barOpen: true }), SURFACE.bar * 1000);
    after(SURFACE.total, () => set({ mode: "globe", barOpen: true }));
  },
};

export function useUi() {
  return useSyncExternalStore(ui.subscribe, ui.get, ui.get);
}

export const activeCandidate = () => state.results[state.active];

// The star catalog is fetched outside Suspense, so it reports in separately.
let starsLoaded = false;
export const markStarsLoaded = () => (starsLoaded = true);
export const areStarsLoaded = () => starsLoaded;
