// Shared GLSL. Units are Earth radii throughout.

/**
 * Single-scattering atmosphere model (Rayleigh + Mie) with sea-level
 * coefficients from Bruneton & Neyret. Scale heights are inflated ~2x over
 * reality so the limb reads at presentation distances; the scattering
 * coefficients are scaled down by the same factor so vertical optical depth —
 * and therefore the colour of the sky, sunsets and the terminator — stays physical.
 */
export const ATMOSPHERE = /* glsl */ `
const float RP = 1.0;
const float RA = 1.025;
const float HR = 0.0025;
const float HM = 0.00045;
const vec3  BETA_R  = vec3(18.57, 43.40, 105.95);
const float BETA_MS = 10.64;
const float BETA_ME = 11.70;
const vec3  BETA_OZ = vec3(4.4, 12.8, 0.6); // ozone absorption on the Rayleigh column — gives the violet limb
const float MIE_G = 0.78;

// Chapman grazing-incidence integral approximation (Schuler, GPU Pro 3).
// X: planet radius in scale heights, h: altitude in scale heights.
float chapman(float X, float h, float mu) {
  float c = sqrt(X + h);
  if (mu >= 0.0) return c / (c * mu + 1.0) * exp(-h);
  float x0 = sqrt(1.0 - mu * mu) * (X + h);
  float c0 = sqrt(x0);
  return max(2.0 * c0 * exp(min(X - x0, 0.0)) - c / (1.0 - c * mu) * exp(-h), 0.0);
}

// Transmittance from radius r toward a direction at cosine-zenith mu, to space.
vec3 transmittance(float r, float mu) {
  float muH = -sqrt(max(0.0, 1.0 - (RP * RP) / (r * r)));
  float shadow = smoothstep(muH - 0.012, muH + 0.006, mu);
  mu = max(mu, muH + 0.006);
  float h = max(r - RP, 0.0);
  float odR = HR * chapman(RP / HR, h / HR, mu);
  float odM = HM * chapman(RP / HM, h / HM, mu);
  return min(exp(-(BETA_R * odR + BETA_ME * odM + BETA_OZ * odR)), vec3(1.0)) * shadow;
}

float phaseRayleigh(float c) { return 0.0596831 * (1.0 + c * c); }
float phaseMie(float c) {
  float g = MIE_G, g2 = g * g;
  return 0.1193662 * (1.0 - g2) * (1.0 + c * c) / ((2.0 + g2) * pow(1.0 + g2 - 2.0 * g * c, 1.5));
}

vec2 raySphere(vec3 ro, vec3 rd, float R) {
  float b = dot(ro, rd);
  float c = dot(ro, ro) - R * R;
  float d = b * b - c;
  if (d < 0.0) return vec2(1e9, -1e9);
  d = sqrt(d);
  return vec2(-b - d, -b + d);
}

float ign(vec2 p) { return fract(52.9829189 * fract(dot(p, vec2(0.06711056, 0.00583715)))); }
`;

export const NOISE = /* glsl */ `
// Ashima / Stefan Gustavson simplex noise (MIT)
vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 mod289(vec4 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 permute(vec4 x) { return mod289(((x * 34.0) + 10.0) * x); }
vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }
float snoise(vec3 v) {
  const vec2 C = vec2(1.0 / 6.0, 1.0 / 3.0);
  const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
  vec3 i = floor(v + dot(v, C.yyy));
  vec3 x0 = v - i + dot(i, C.xxx);
  vec3 g = step(x0.yzx, x0.xyz);
  vec3 l = 1.0 - g;
  vec3 i1 = min(g.xyz, l.zxy);
  vec3 i2 = max(g.xyz, l.zxy);
  vec3 x1 = x0 - i1 + C.xxx;
  vec3 x2 = x0 - i2 + C.yyy;
  vec3 x3 = x0 - D.yyy;
  i = mod289(i);
  vec4 p = permute(permute(permute(i.z + vec4(0.0, i1.z, i2.z, 1.0)) + i.y + vec4(0.0, i1.y, i2.y, 1.0)) + i.x + vec4(0.0, i1.x, i2.x, 1.0));
  float n_ = 0.142857142857;
  vec3 ns = n_ * D.wyz - D.xzx;
  vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
  vec4 x_ = floor(j * ns.z);
  vec4 y_ = floor(j - 7.0 * x_);
  vec4 x = x_ * ns.x + ns.yyyy;
  vec4 y = y_ * ns.x + ns.yyyy;
  vec4 h = 1.0 - abs(x) - abs(y);
  vec4 b0 = vec4(x.xy, y.xy);
  vec4 b1 = vec4(x.zw, y.zw);
  vec4 s0 = floor(b0) * 2.0 + 1.0;
  vec4 s1 = floor(b1) * 2.0 + 1.0;
  vec4 sh = -step(h, vec4(0.0));
  vec4 a0 = b0.xzyw + s0.xzyw * sh.xxyy;
  vec4 a1 = b1.xzyw + s1.xzyw * sh.zzww;
  vec3 p0 = vec3(a0.xy, h.x);
  vec3 p1 = vec3(a0.zw, h.y);
  vec3 p2 = vec3(a1.xy, h.z);
  vec3 p3 = vec3(a1.zw, h.w);
  vec4 norm = taylorInvSqrt(vec4(dot(p0, p0), dot(p1, p1), dot(p2, p2), dot(p3, p3)));
  p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;
  vec4 m = max(0.5 - vec4(dot(x0, x0), dot(x1, x1), dot(x2, x2), dot(x3, x3)), 0.0);
  m = m * m;
  return 105.0 * dot(m * m, vec4(dot(p0, x0), dot(p1, x1), dot(p2, x2), dot(p3, x3)));
}
float fbm(vec3 p, int oct) {
  float a = 0.5, s = 0.0, n = 0.0;
  for (int i = 0; i < 6; i++) {
    if (i >= oct) break;
    s += a * snoise(p);
    n += a;
    p = p * 2.03 + vec3(1.7, 9.2, 4.1);
    a *= 0.5;
  }
  return 0.5 + 0.5 * s / n;
}
`;

/** Object-space position -> equirectangular UV (lon 0 at u = 0.5, matching SphereGeometry). */
export const GEO = /* glsl */ `
const float PI_ = 3.14159265359;
vec2 dirToUv(vec3 d) {
  return vec2(0.5 + atan(-d.z, d.x) / (2.0 * PI_), 0.5 + asin(clamp(d.y, -1.0, 1.0)) / PI_);
}
`;

export const VERT = /* glsl */ `
#include <common>
#include <logdepthbuf_pars_vertex>
varying vec2 vUv;
varying vec3 vPos;
varying vec3 vWorld;
void main() {
  vUv = uv;
  vPos = position;
  vec4 w = modelMatrix * vec4(position, 1.0);
  vWorld = w.xyz;
  gl_Position = projectionMatrix * viewMatrix * w;
  #include <logdepthbuf_vertex>
}
`;

export const FRAG_HEAD = /* glsl */ `
#include <common>
#include <logdepthbuf_pars_fragment>
varying vec2 vUv;
varying vec3 vPos;
varying vec3 vWorld;
`;
