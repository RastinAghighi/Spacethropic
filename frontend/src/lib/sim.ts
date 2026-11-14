import { computeEphemeris } from "./astro";

// Simulation clock lives outside React so the render loop can advance it
// every frame without triggering re-renders. Runs at real time (live UTC).
export const clock = {
  ms: Date.now(),
  ephemeris: computeEphemeris(Date.now()),
};

export function advanceClock() {
  clock.ms = Date.now();
  computeEphemeris(clock.ms, clock.ephemeris);
}
