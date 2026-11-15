import { useSyncExternalStore } from "react";
import { DEFAULT_FILTERS, type Dim, type Filters, type Geology, type NumKey, type Tab, type Weight } from "./profile";

// The refine side of the research loop: which drawer is out, and the limits being drafted
// against the ones the current results were searched with. Kept apart from the ui store so
// dragging a slider doesn't re-render the 3D scene.

interface ResearchState {
  drawer: Tab | null;
  /** Limits the current results were searched with */
  applied: Filters;
  /** Limits being edited in the drawers */
  draft: Filters;
}

let state: ResearchState = { drawer: null, applied: DEFAULT_FILTERS, draft: DEFAULT_FILTERS };
const listeners = new Set<() => void>();

function set(patch: Partial<ResearchState>) {
  state = { ...state, ...patch };
  listeners.forEach((l) => l());
}
const draft = (patch: Partial<Filters>) => set({ draft: { ...state.draft, ...patch } });

export const research = {
  get: () => state,
  subscribe(l: () => void) {
    listeners.add(l);
    return () => {
      listeners.delete(l);
    };
  },
  /** New results arrived (or a past step was restored): they become the baseline. */
  load(f: Filters = DEFAULT_FILTERS) {
    set({ applied: f, draft: f });
  },
  open: (drawer: Tab | null) => set({ drawer }),
  toggle: (tab: Tab) => set({ drawer: state.drawer === tab ? null : tab }),
  setRange(key: NumKey, r: [number, number] | null) {
    const ranges = { ...state.draft.ranges };
    if (r) ranges[key] = r;
    else delete ranges[key];
    draft({ ranges });
  },
  toggleGeology(g: Geology) {
    const has = state.draft.geology.includes(g);
    draft({ geology: has ? state.draft.geology.filter((x) => x !== g) : [...state.draft.geology, g] });
  },
  setWeight: (d: Dim, w: Weight) => draft({ weights: { ...state.draft.weights, [d]: w } }),
  setProtected: (excludeProtected: boolean) => draft({ excludeProtected }),
  revert: () => set({ draft: state.applied }),
};

export function useResearch() {
  return useSyncExternalStore(research.subscribe, research.get, research.get);
}
