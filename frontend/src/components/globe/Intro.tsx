"use client";

import { useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { clock } from "@/lib/sim";
import { DEG, equatorialDir } from "@/lib/astro";

const DURATION = 7.5;
/** Azimuth before the eclipse at the start of the intro (radians). */
const LEAD_IN = 1.4;
const START_RADIUS = 1.35;
/** Pulled right back at the eclipse so the Moon, flare and Milky Way are all in frame. */
const ECLIPSE_RADIUS = 6.5;
const END_RADIUS = 4.8;
/** Cruising spin after the intro (rad/s); the intro starts and ends at this speed. */
const SPIN_RATE = 0.06;
/** Seconds to ease the cruise spin back in after the user lets go. */
const RESUME_TIME = 1.5;

/** Eclipse view: facing the galactic centre, Earth backlit on the Milky Way's bright core. */
const ECLIPSE = new THREE.Spherical().setFromVector3(equatorialDir(266.405 * DEG, -28.936 * DEG).negate());
const sph = new THREE.Spherical();
const dir = new THREE.Vector3();
const Y = new THREE.Vector3(0, 1, 0);

const smootherstep = (x: number) => THREE.MathUtils.smootherstep(x, 0, 1);

/** How far past the eclipse to keep spinning until the camera looks onto the day side. */
function sweepPastEclipse() {
  const sun = clock.ephemeris.sunDir;
  let best = Math.PI;
  let bestAngle = Infinity;
  for (let d = 0.6; d < 2 * Math.PI; d += 0.02) {
    dir.setFromSphericalCoords(1, ECLIPSE.phi, ECLIPSE.theta - d);
    const angle = Math.acos(THREE.MathUtils.clamp(dir.dot(sun), -1, 1)) / DEG;
    if (angle < 65) return d;
    if (angle < bestAngle) {
      bestAngle = angle;
      best = d;
    }
  }
  return best;
}

/**
 * Angular speed is the cruise rate plus one smooth swell, u(1-u)², that builds from
 * near rest, peaks a third of the way in and glides back to exactly the cruise rate —
 * a heavy camera, no sudden starts and a seamless hand-off. Azimuth decreases over time.
 */
function applyPose(camera: THREE.Camera, elapsed: number, sweep: number) {
  const total = LEAD_IN + sweep;
  const u = Math.min(elapsed / DURATION, 1);
  const swell = (12 * (total - SPIN_RATE * DURATION)) / DURATION;
  const bump = (u * u) / 2 - (2 * u * u * u) / 3 + (u * u * u * u) / 4; // ∫ u(1-u)² du
  const travelled = SPIN_RATE * u * DURATION + swell * DURATION * bump;

  // Zoom follows angular progress: out to the eclipse, then settle in.
  let logR: number;
  let phi: number;
  if (travelled <= LEAD_IN) {
    const e = smootherstep(travelled / LEAD_IN);
    logR = THREE.MathUtils.lerp(Math.log(START_RADIUS), Math.log(ECLIPSE_RADIUS), e);
    phi = THREE.MathUtils.lerp(ECLIPSE.phi - 0.25, ECLIPSE.phi, e);
  } else {
    const e = smootherstep((travelled - LEAD_IN) / sweep);
    logR = THREE.MathUtils.lerp(Math.log(ECLIPSE_RADIUS), Math.log(END_RADIUS), e);
    phi = ECLIPSE.phi;
  }
  sph.radius = Math.exp(logR);
  sph.phi = phi;
  sph.theta = ECLIPSE.theta + LEAD_IN - travelled;
  camera.position.setFromSpherical(sph);
  camera.lookAt(0, 0, 0);
}

function enableControls(controls: OrbitControlsImpl, onStart: () => void, onEnd: () => void) {
  controls.target.set(0, 0, 0);
  controls.autoRotate = false;
  controls.enabled = true;
  controls.addEventListener("start", onStart);
  controls.addEventListener("end", onEnd);
}

/** Page-load intro: zoom out while spinning, through an eclipse on the Milky Way, into daylight and a slow orbit. */
export function Intro() {
  const t0 = useRef<number | null>(null);
  const sweep = useRef(Math.PI);
  const phase = useRef<"intro" | "cruise">("intro");
  const dragging = useRef(false);
  const releasedAt = useRef(-Infinity);

  useFrame(({ camera, controls, clock: rc }, delta) => {
    const c = controls as unknown as OrbitControlsImpl | null;
    if (!c) return;
    if (t0.current === null) {
      t0.current = rc.elapsedTime;
      sweep.current = sweepPastEclipse();
      c.enabled = false;
    }
    const elapsed = rc.elapsedTime - t0.current;

    if (phase.current === "intro") {
      applyPose(camera, elapsed, sweep.current);
      if (elapsed >= DURATION) {
        enableControls(
          c,
          () => (dragging.current = true),
          () => {
            dragging.current = false;
            releasedAt.current = rc.elapsedTime;
          },
        );
        phase.current = "cruise";
      }
      return;
    }

    // Cruise: our own spin (not autoRotate, whose damping makes it ramp up from near zero).
    if (dragging.current) return;
    const resume = smootherstep(Math.min((rc.elapsedTime - releasedAt.current) / RESUME_TIME, 1));
    camera.position.applyAxisAngle(Y, -SPIN_RATE * resume * Math.min(delta, 0.1));
  });

  return null;
}
