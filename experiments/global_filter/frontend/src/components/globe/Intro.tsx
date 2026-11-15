"use client";

import { useEffect, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { clock } from "@/lib/sim";
import { DEG, equatorialDir } from "@/lib/astro";
import { ui } from "@/lib/ui";
import { SPIN_RATE } from "@/lib/flight";

const DURATION = 7.5;
/** Skip the slow wind-up: the reveal cuts straight into the move this far in (s). */
const START_AT = 2.0;
/** Azimuth before the eclipse at the start of the intro (radians). */
const LEAD_IN = 1.4;
const START_RADIUS = 1.35;
/** Pulled right back at the eclipse so the Moon, flare and Milky Way are all in frame. */
const ECLIPSE_RADIUS = 6.5;
const END_RADIUS = 4.8;
/** Fraction of the intro after which the overlay UI starts coming in. */
const LANDED_AT = 0.72;
/** Time constants (s) for the cruise spin easing out when grabbed and back in on release. */
const GRAB_TAU = 0.22;
const RELEASE_TAU = 0.9;
/** Pointer travel (px) before a press counts as a drag rather than a click. */
const DRAG_SLOP = 4;

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

function enableControls(controls: OrbitControlsImpl) {
  controls.target.set(0, 0, 0);
  controls.autoRotate = false;
  controls.enabled = true;
}

/** Page-load intro: zoom out while spinning, through an eclipse on the Milky Way, into daylight and a slow orbit. */
export function Intro() {
  const t0 = useRef<number | null>(null);
  const sweep = useRef<number | null>(null);
  const phase = useRef<"intro" | "cruise">("intro");
  const dragging = useRef(false);
  /** Cruise spin speed as a fraction of SPIN_RATE, eased rather than switched. */
  const spin = useRef(1);
  const dom = useThree((s) => s.gl.domElement);

  // A click shouldn't stop the spin: only a press that actually moves counts as a grab.
  useEffect(() => {
    let down: { x: number; y: number } | null = null;
    const onDown = (e: PointerEvent) => (down = { x: e.clientX, y: e.clientY });
    const onMove = (e: PointerEvent) => {
      if (down && Math.hypot(e.clientX - down.x, e.clientY - down.y) > DRAG_SLOP) dragging.current = true;
    };
    const onUp = () => {
      down = null;
      dragging.current = false;
    };
    dom.addEventListener("pointerdown", onDown);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
    return () => {
      dom.removeEventListener("pointerdown", onDown);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };
  }, [dom]);

  useFrame(({ camera, controls }, delta) => {
    // Own wall clock: R3F's clock is reset by setFrameloop(), which would rewind the intro.
    const now = performance.now() / 1000;
    const c = controls as unknown as OrbitControlsImpl | null;
    if (!c) return;
    if (sweep.current === null) {
      sweep.current = sweepPastEclipse();
      c.enabled = false;
    }
    // Hold the opening frame behind the loader until everything is ready.
    if (!ui.get().ready) {
      applyPose(camera, START_AT, sweep.current);
      return;
    }
    if (t0.current === null) t0.current = now - START_AT;
    const elapsed = now - t0.current;

    // The dive, site view and surface fly the camera (CameraDirector). The surface hands
    // back already turning at the cruise rate, so the spin carries on at full speed.
    const { mode } = ui.get();
    if (mode === "diving" || mode === "site" || mode === "surfacing" || (mode === "searching" && ui.get().searchFrom === "site")) {
      if (phase.current === "intro") {
        ui.setLanded();
        phase.current = "cruise";
      }
      spin.current = 1;
      return;
    }

    if (phase.current === "intro") {
      applyPose(camera, elapsed, sweep.current);
      if (elapsed >= DURATION * LANDED_AT) ui.setLanded();
      if (elapsed >= DURATION) {
        enableControls(c);
        phase.current = "cruise";
      }
      return;
    }

    // Cruise: our own spin (not autoRotate, whose damping makes it ramp up from near zero),
    // easing out under the user's hand and back in when they let go.
    const dt = Math.min(delta, 0.1);
    const goal = dragging.current ? 0 : 1;
    spin.current += (goal - spin.current) * (1 - Math.exp(-dt / (dragging.current ? GRAB_TAU : RELEASE_TAU)));
    camera.position.applyAxisAngle(Y, -SPIN_RATE * spin.current * dt);
  });

  return null;
}
