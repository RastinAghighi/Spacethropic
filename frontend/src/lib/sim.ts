import * as THREE from "three";
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
  applyDaylight();
}

/**
 * Staged daylight for the dive: blends the real Sun toward a mid-morning Sun over the
 * site, so the descent through the clouds never lands on a night-side globe under a
 * daylight satellite image. weight 0 = real sky.
 */
export const daylight = { weight: 0, dir: new THREE.Vector3(0, 0, 1) };
const realSun = new THREE.Vector3();
const swing = new THREE.Quaternion();

function applyDaylight() {
  if (daylight.weight <= 0) return;
  const sun = clock.ephemeris.sunDir;
  realSun.copy(sun);
  swing.setFromUnitVectors(realSun, daylight.dir);
  sun.copy(realSun).applyQuaternion(new THREE.Quaternion().slerp(swing, Math.min(daylight.weight, 1)));
}
