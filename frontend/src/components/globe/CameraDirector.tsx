"use client";

import { useEffect, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { clock, daylight } from "@/lib/sim";
import { DEG, geoDir } from "@/lib/astro";
import { DIVE, SURFACE, activeCandidate, ui } from "@/lib/ui";
import { ease, lerp, span } from "@/lib/motion";
import {
  BASE_FOV,
  CRUISE_RADIUS,
  SITE_FOV,
  SPIN_RATE,
  altitudeAt,
  anchor,
  diveLogH,
  diveTurn,
  flight,
  groundFrame,
  radiusAt,
  surfaceLogH,
} from "@/lib/flight";

const Y = new THREE.Vector3(0, 1, 0);
const sph = new THREE.Spherical();
const q = new THREE.Quaternion();
const spun = new THREE.Vector3();
/** Staged Sun over the site: mid-morning, from the south-east (the light HLS images are taken in). */
const SUN_ELEVATION = 42 * DEG;
const SUN_AZIMUTH = 135 * DEG;
const north = new THREE.Vector3();
const east = new THREE.Vector3();

function stageSun(site: THREE.Vector3, weight: number) {
  east.crossVectors(Y, site).normalize();
  north.crossVectors(site, east).normalize();
  daylight.dir
    .copy(site)
    .multiplyScalar(Math.sin(SUN_ELEVATION))
    .addScaledVector(north, Math.cos(SUN_ELEVATION) * Math.cos(SUN_AZIMUTH))
    .addScaledVector(east, Math.cos(SUN_ELEVATION) * Math.sin(SUN_AZIMUTH))
    .normalize();
  daylight.weight = weight;
}

/** Latitude the camera drifts toward on the way back out (radians). */
const CRUISE_LAT = 22 * DEG;

/** World-space direction of a lat/lon right now (Earth is rotating). */
function siteDirection(lat: number, lon: number, out: THREE.Vector3) {
  return geoDir(lat * DEG, lon * DEG, out).applyAxisAngle(Y, clock.ephemeris.earthRotation);
}

function setFov(camera: THREE.Camera, fov: number) {
  const cam = camera as THREE.PerspectiveCamera;
  if (Math.abs(cam.fov - fov) < 1e-4) return;
  cam.fov = fov;
  cam.updateProjectionMatrix();
}

/** Shift the projection so the camera's aim point sits at the site anchor instead of mid-screen. */
function setAnchor(camera: THREE.Camera, width: number, height: number, amount: number) {
  const cam = camera as THREE.PerspectiveCamera;
  if (amount < 1e-4) {
    if (cam.view?.enabled) cam.clearViewOffset();
    return;
  }
  const a = anchor(width, height);
  cam.setViewOffset(width, height, (0.5 - a.x) * width * amount, (0.5 - a.y) * height * amount, width, height);
}

function setControls(controls: unknown, enabled: boolean) {
  const c = controls as OrbitControlsImpl | null;
  if (c) c.enabled = enabled;
}

/** Azimuth swept during the surface (radians): angular speed swells, then settles on the cruise rate. */
function surfaceSweep(u: number) {
  const smootherInt = u ** 6 - 3 * u ** 5 + 2.5 * u ** 4; // ∫ smootherstep
  const swellInt = u / 2 - Math.sin(2 * Math.PI * u) / (4 * Math.PI); // ∫ sin²(πu)
  return SPIN_RATE * SURFACE.total * (smootherInt + 1.6 * swellInt);
}

/**
 * Flies the globe camera for the dive and the surface, in lockstep with the satellite
 * renderer (both evaluate the same altitude curve), and pauses the globe render while
 * the satellite view covers it.
 */
export function CameraDirector() {
  const setFrameloop = useThree((s) => s.setFrameloop);
  const start = useRef({ at: -1, dir: new THREE.Vector3(), fov: BASE_FOV });
  const target = useRef(new THREE.Vector3());

  // Only touch the frameloop when it actually changes: R3F's setFrameloop() also resets its clock.
  useEffect(() => {
    let current: "always" | "never" = "always";
    return ui.subscribe(() => {
      const { mode, searchFrom } = ui.get();
      const next = mode === "site" || (mode === "searching" && searchFrom === "site") ? "never" : "always";
      if (next === current) return;
      current = next;
      setFrameloop(next);
    });
  }, [setFrameloop]);

  useFrame(({ camera, controls, size }) => {
    const { mode, transitionAt } = ui.get();
    const c = activeCandidate();
    if ((mode !== "diving" && mode !== "surfacing") || !c) {
      // Landed back in orbit: settle exactly on the cruise lens and hand back the controls.
      if (mode === "globe" && start.current.at >= 0) {
        start.current.at = -1;
        setFov(camera, BASE_FOV);
        setAnchor(camera, size.width, size.height, 0);
        setControls(controls, true);
      }
      if (mode === "globe") daylight.weight = 0;
      return;
    }
    const t = (performance.now() - transitionAt) / 1000;
    const frame = groundFrame(size.width, size.height, c.imagery.metersPerPixel);
    siteDirection(c.lat, c.lon, target.current);

    if (mode === "diving") {
      if (start.current.at !== transitionAt) {
        const fov = (camera as THREE.PerspectiveCamera).fov;
        start.current = { at: transitionAt, dir: camera.position.clone().normalize(), fov };
        flight.diveFrom = altitudeAt(camera.position.length(), fov, frame.kmPerUnit);
        setControls(controls, false);
      }
      // Bring the day round to the site while the camera is still turning, well before the clouds.
      stageSun(target.current, ease.smoother(span(t, 0, DIVE.total * 0.4)));
      // Keep the cruise spin going while turning onto the site, so nothing stops dead.
      const turn = diveTurn(t);
      spun.copy(start.current.dir).applyAxisAngle(Y, -SPIN_RATE * Math.min(t, DIVE.total));
      q.setFromUnitVectors(spun, target.current);
      const dir = spun.applyQuaternion(new THREE.Quaternion().slerp(q, turn));
      const fov = lerp(start.current.fov, SITE_FOV, ease.smoother(span(t, 0, DIVE.total * 0.55)));
      const r = radiusAt(Math.exp(diveLogH(t)), fov, frame.kmPerUnit);
      setFov(camera, fov);
      setAnchor(camera, size.width, size.height, turn);
      camera.position.copy(dir).multiplyScalar(r);
      camera.lookAt(0, 0, 0);
      return;
    }

    // Surface: lift straight off the site, then curve away into the orbit, the spin
    // swelling and settling exactly onto the cruise rate as the camera arrives.
    if (start.current.at !== transitionAt) {
      start.current = { at: transitionAt, dir: target.current.clone(), fov: SITE_FOV };
      flight.surfaceTo = altitudeAt(CRUISE_RADIUS, BASE_FOV, frame.kmPerUnit);
    }
    const u = span(t, 0, SURFACE.total);
    // Hand the sky back to real time once the camera is well clear of the surface.
    stageSun(target.current, 1 - ease.smoother(span(u, 0.45, 1)));
    const fov = lerp(SITE_FOV, BASE_FOV, ease.smoother(span(t, SURFACE.total * 0.3, SURFACE.total)));
    const r = radiusAt(Math.exp(surfaceLogH(t)), fov, frame.kmPerUnit);
    sph.setFromVector3(target.current);
    const lean = ease.smoother(span(u, 0.25, 1));
    sph.phi = lerp(sph.phi, Math.PI / 2 - lerp(c.lat * DEG, CRUISE_LAT, 0.55), lean);
    sph.theta -= surfaceSweep(u);
    sph.radius = r;
    setFov(camera, fov);
    setAnchor(camera, size.width, size.height, 1 - ease.smoother(span(u, 0.25, 0.85)));
    camera.position.setFromSpherical(sph);
    camera.lookAt(0, 0, 0);
    if (t >= SURFACE.total) setControls(controls, true);
  });

  return null;
}
