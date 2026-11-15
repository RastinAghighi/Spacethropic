import { DIVE, SURFACE } from "./ui";
import { cubicBezier, ease, span } from "./motion";

// One continuous flight shared by the globe camera and the satellite renderer.
//
// Everything is measured in "view units": the satellite image, cover-fitted at the
// resting altitude h = 1, spans exactly one viewport height per unit. The globe camera
// converts h to an orbital radius with the same scale, so the sharp HLS image lands
// precisely on top of the globe's own terrain while the camera is still falling toward
// it, and the cloud decks (planes at fixed altitudes) are flown through physically.

export const SPIN_RATE = 0.06;
export const BASE_FOV = 35;
export const SITE_FOV = 22;
export const CRUISE_RADIUS = 4.8;
export const EARTH_KM = 6371;

const IMG_ASPECT = 2400 / 1350;
const IMG_H = 1350;

/** Cloud decks: altitude (h), coverage, opacity, seed. Sorted low to high. */
export const CLOUD_DECKS: [number, number, number, number][] = [
  [1.24, 0.34, 0.8, 0.0],
  [1.52, 0.42, 0.85, 1.0],
  [1.92, 0.5, 0.9, 2.0],
  [2.5, 0.56, 0.92, 3.0],
  [3.3, 0.62, 0.95, 4.0],
  [4.6, 0.5, 0.85, 5.0],
  [6.6, 0.4, 0.7, 6.0],
];

/** Written by the globe camera when a flight starts, read by both sides. */
export const flight = { diveFrom: 400, surfaceTo: 400 };

/** Width the evidence panel takes on the right (matches --panel-space). */
const panelSpace = (width: number) => (width >= 768 ? Math.min(420, width * 0.33) + 20 : 0);

/**
 * Where on screen the site sits (fractions of the viewport): centred in the space left
 * of the evidence panel, and a touch above middle to clear the tray and search bar.
 */
export const anchor = (width: number, height: number) => ({
  x: (width - panelSpace(width)) / 2 / width,
  y: height > 500 ? 0.45 : 0.5,
});

/** Image half-extents in view units, and the ground distance one view unit covers (km). */
export function groundFrame(width: number, height: number, metersPerPixel = 30) {
  const a = anchor(width, height);
  const coverW = (2 * Math.max(a.x, 1 - a.x) * width) / height;
  const coverH = 2 * Math.max(a.y, 1 - a.y);
  const k = Math.max(coverW / IMG_ASPECT, coverH);
  return { anchorX: a.x, anchorY: a.y, halfW: (IMG_ASPECT * k) / 2, halfH: k / 2, kmPerUnit: (IMG_H * metersPerPixel) / k / 1000 };
}

/** Orbital radius (Earth radii) at which the globe camera matches altitude h. */
export const radiusAt = (h: number, fovDeg: number, kmPerUnit: number) =>
  1 + (h * kmPerUnit) / 2 / (Math.tan((fovDeg * Math.PI) / 360) * EARTH_KM);

export const altitudeAt = (r: number, fovDeg: number, kmPerUnit: number) =>
  ((r - 1) * EARTH_KM * Math.tan((fovDeg * Math.PI) / 360) * 2) / kmPerUnit;

// Dive: barely moving at first (the cruise carries on while the camera turns), a hard
// punch through the upper atmosphere, then a long deceleration through the cloud decks.
const diveEase = cubicBezier(0.62, 0, 0.1, 1);
export const diveLogH = (t: number) => Math.log(flight.diveFrom) * (1 - diveEase(span(t, 0, DIVE.total)));
/** Turn toward the site finishes while the camera is still high. */
export const diveTurn = (t: number) => ease.inOutCubic(span(t, 0, DIVE.total * 0.4));

// Surface: lift off gently, accelerate up through the decks, glide into orbit.
const surfaceEase = cubicBezier(0.5, 0, 0.14, 1);
export const surfaceLogH = (t: number, fromLogH = 0) =>
  fromLogH + (Math.log(flight.surfaceTo) - fromLogH) * surfaceEase(span(t, 0, SURFACE.total));

/** Sharp imagery takes over from the globe texture between these altitudes. */
export const imageMix = (h: number) => 1 - ease.smoother(span(Math.log(h), Math.log(3.6), Math.log(9)));
/** The globe stays visible around the image until the decks close over it. */
export const globeMix = (h: number) => ease.smoother(span(h, 1.12, 2.3));
