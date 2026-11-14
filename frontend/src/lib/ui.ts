import { useSyncExternalStore } from "react";

// Page-level choreography shared between the 3D scene and the DOM overlay.
interface UiState {
  /** Every texture, the star catalog and all shaders are uploaded and compiled. */
  ready: boolean;
  /** The intro flight has landed on the day side — time to bring in the UI. */
  landed: boolean;
}

let state: UiState = { ready: false, landed: false };
const listeners = new Set<() => void>();

function set(patch: Partial<UiState>) {
  const next = { ...state, ...patch };
  if (next.ready === state.ready && next.landed === state.landed) return;
  state = next;
  listeners.forEach((l) => l());
}

export const ui = {
  get: () => state,
  subscribe(l: () => void) {
    listeners.add(l);
    return () => listeners.delete(l);
  },
  setReady: () => set({ ready: true }),
  setLanded: () => set({ landed: true }),
};

export function useUi() {
  return useSyncExternalStore(ui.subscribe, ui.get, ui.get);
}

// The star catalog is fetched outside Suspense, so it reports in separately.
let starsLoaded = false;
export const markStarsLoaded = () => (starsLoaded = true);
export const areStarsLoaded = () => starsLoaded;
