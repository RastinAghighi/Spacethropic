import * as THREE from "three";

// Low-precision ephemerides (Meeus / USNO approximations), good to ~0.01° for the
// Sun and ~0.3° for the Moon — far below what is visible on screen.
//
// Scene frame: equatorial, Earth-centred, 1 unit = 1 Earth radius.
//   +Y = north celestial pole, +X = vernal equinox (RA 0h), RA increases toward −Z.

export const DEG = Math.PI / 180;
export const EARTH_RADIUS_KM = 6371;
export const MOON_RADIUS = 1737.4 / EARTH_RADIUS_KM;

export function daysSinceJ2000(ms: number) {
  return ms / 86400000 + 2440587.5 - 2451545.0;
}

/** Unit vector for a right ascension / declination (radians). */
export function equatorialDir(ra: number, dec: number, out = new THREE.Vector3()) {
  const c = Math.cos(dec);
  return out.set(c * Math.cos(ra), Math.sin(dec), -c * Math.sin(ra));
}

/** Unit vector for a geographic lat/lon (radians) in Earth's body frame. */
export function geoDir(lat: number, lon: number, out = new THREE.Vector3()) {
  return equatorialDir(lon, lat, out);
}

function obliquity(d: number) {
  return (23.439 - 0.00000036 * d) * DEG;
}

export function sunRaDec(d: number) {
  const g = (357.529 + 0.98560028 * d) * DEG;
  const q = 280.459 + 0.98564736 * d;
  const L = (q + 1.915 * Math.sin(g) + 0.02 * Math.sin(2 * g)) * DEG;
  const e = obliquity(d);
  return {
    ra: Math.atan2(Math.cos(e) * Math.sin(L), Math.cos(L)),
    dec: Math.asin(Math.sin(e) * Math.sin(L)),
  };
}

/** Greenwich mean sidereal time — Earth's rotation angle (radians). */
export function gmst(d: number) {
  return (((280.46061837 + 360.98564736629 * d) % 360) + 360) % 360 * DEG;
}

export function moonEquatorial(d: number) {
  const L = (218.316 + 13.176396 * d) * DEG;
  const M = (134.963 + 13.064993 * d) * DEG;
  const F = (93.272 + 13.22935 * d) * DEG;
  const lambda = L + 6.289 * DEG * Math.sin(M);
  const beta = 5.128 * DEG * Math.sin(F);
  const distKm = 385001 - 20905 * Math.cos(M);
  const e = obliquity(d);
  const x = Math.cos(beta) * Math.cos(lambda);
  const y = Math.cos(beta) * Math.sin(lambda);
  const z = Math.sin(beta);
  const ye = y * Math.cos(e) - z * Math.sin(e);
  const ze = y * Math.sin(e) + z * Math.cos(e);
  return {
    ra: Math.atan2(ye, x),
    dec: Math.asin(ze),
    dist: distKm / EARTH_RADIUS_KM,
  };
}

function wrapPi(a: number) {
  return Math.atan2(Math.sin(a), Math.cos(a));
}

export interface Ephemeris {
  sunDir: THREE.Vector3;
  moonPos: THREE.Vector3;
  earthRotation: number;
  subsolarLat: number;
  subsolarLon: number;
  /** Fraction of the Moon's disc lit, 0..1 */
  moonIllumination: number;
}

export function computeEphemeris(ms: number, out?: Ephemeris): Ephemeris {
  const d = daysSinceJ2000(ms);
  const sun = sunRaDec(d);
  const moon = moonEquatorial(d);
  const rot = gmst(d);
  const e = out ?? {
    sunDir: new THREE.Vector3(),
    moonPos: new THREE.Vector3(),
    earthRotation: 0,
    subsolarLat: 0,
    subsolarLon: 0,
    moonIllumination: 0,
  };
  equatorialDir(sun.ra, sun.dec, e.sunDir);
  equatorialDir(moon.ra, moon.dec, e.moonPos).multiplyScalar(moon.dist);
  e.earthRotation = rot;
  e.subsolarLat = sun.dec;
  e.subsolarLon = wrapPi(sun.ra - rot);
  const elong = Math.acos(THREE.MathUtils.clamp(e.sunDir.dot(e.moonPos) / moon.dist, -1, 1));
  e.moonIllumination = (1 - Math.cos(elong)) / 2;
  return e;
}
