import { ATMOSPHERE, FRAG_HEAD, GEO, NOISE } from "./common";

// All lighting is done in the body frame of each mesh; sun and camera vectors
// are rotated into it on the CPU every frame.

export const earthFrag = /* glsl */ `
${FRAG_HEAD}
${ATMOSPHERE}
${GEO}
${NOISE}
uniform sampler2D uDay;
uniform sampler2D uLights;
uniform sampler2D uElev;
uniform sampler2D uWater;
uniform sampler2D uClouds;
uniform vec3 uSun;
uniform vec3 uCam;
uniform float uSunE;
uniform float uCloudDrift;
uniform vec2 uTexel;
uniform float uRelief;
uniform float uLightsGain;

vec3 gradeAlbedo(vec3 c, float water) {
  // Blue Marble is captured through a hazy nadir view; restore some depth.
  float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
  // Saturation boost extrapolates — clamp before pow() or saturated coastal texels go NaN.
  c = max(mix(vec3(l), c, mix(1.18, 1.05, water)), 0.0);
  c = pow(c, vec3(mix(1.06, 1.12, water)));
  return c;
}

float cloudAt(vec3 d, float lod) {
  vec2 uv = dirToUv(d);
  uv.x = fract(uv.x - uCloudDrift / (2.0 * PI_));
  return textureLod(uClouds, uv, lod).r;
}

void main() {
  #include <logdepthbuf_fragment>
  vec3 p = normalize(vPos);
  vec3 east = normalize(vec3(p.z, 0.0, -p.x) + vec3(1e-6, 0.0, 0.0));
  vec3 north = cross(p, east);
  float coslat = max(sqrt(1.0 - p.y * p.y), 0.04);

  float water = texture2D(uWater, vUv).r;

  // Relief shading from GEBCO elevation (finite differences, exaggerated).
  float hL = texture2D(uElev, vUv - vec2(uTexel.x, 0.0)).r;
  float hR = texture2D(uElev, vUv + vec2(uTexel.x, 0.0)).r;
  float hD = texture2D(uElev, vUv - vec2(0.0, uTexel.y)).r;
  float hU = texture2D(uElev, vUv + vec2(0.0, uTexel.y)).r;
  float su = (hR - hL) / (2.0 * uTexel.x) / (2.0 * PI_ * coslat) * uRelief;
  float sv = (hU - hD) / (2.0 * uTexel.y) / PI_ * uRelief;
  vec3 n = normalize(p - su * east - sv * north);

  vec3 L = uSun;
  vec3 V = normalize(uCam - vPos);
  float NLg = dot(p, L);
  float NL = max(dot(n, L), 0.0);
  float NV = max(dot(p, V), 1e-3);

  vec3 albedo = gradeAlbedo(texture2D(uDay, vUv).rgb, water);

  // Sunlight reaching the ground, reddened through the atmosphere.
  vec3 sun = uSunE * transmittance(RP, NLg);

  // Cloud shadows: march toward the sun to the cloud deck.
  float tShadow = 0.006 / max(NLg, 0.12);
  float cs = cloudAt(normalize(p + L * tShadow), 2.5);
  float shadow = 1.0 - smoothstep(0.1, 0.9, cs) * 0.6;

  vec3 col = albedo / PI_ * sun * NL * shadow;

  // Skylight fill
  col += albedo * vec3(0.05, 0.09, 0.18) * uSunE * 0.025 * smoothstep(-0.15, 0.4, NLg);

  // Ocean: GGX glint with wave-scale roughness variation.
  if (water > 0.01) {
    vec3 nw = normalize(p + 0.012 * vec3(snoise(p * 180.0), snoise(p * 180.0 + 31.0), snoise(p * 180.0 + 67.0)));
    float rough = 0.36 + 0.07 * snoise(p * 9.0);
    float a2 = pow(rough, 4.0);
    vec3 H = normalize(L + V);
    float NH = max(dot(nw, H), 0.0);
    float NLw = max(dot(nw, L), 0.0);
    float NVw = max(dot(nw, V), 1e-3);
    float dd = NH * NH * (a2 - 1.0) + 1.0;
    float D = a2 / (PI_ * dd * dd);
    float F = 0.02 + 0.98 * pow(1.0 - max(dot(H, V), 0.0), 5.0);
    // Height-correlated Smith visibility folded with the 1/(4 NL NV) term — stays bounded at the limb.
    float k = rough * rough * 0.5;
    float vis = (NLw / (NLw * (1.0 - k) + k)) / (4.0 * (NVw * (1.0 - k) + k));
    vec3 spec = sun * D * F * vis * shadow;
    // Diffuse sky reflection on water, strongest at grazing angles.
    vec3 skyRefl = vec3(0.04, 0.09, 0.2) * uSunE * 0.03 * F * smoothstep(-0.1, 0.3, NLg);
    col += (spec + skyRefl) * water;
  }

  // Night: VIIRS Black Marble city lights, sodium-to-LED colour ramp, dimmed under cloud.
  float night = smoothstep(0.06, -0.14, NLg);
  float li = texture2D(uLights, vUv).r;
  vec3 city = mix(vec3(1.0, 0.48, 0.16), vec3(1.0, 0.82, 0.55), smoothstep(0.25, 0.9, li));
  float cover = cloudAt(p, 1.0);
  col += city * pow(li, 1.6) * uLightsGain * night * (1.0 - smoothstep(0.2, 0.9, cover) * 0.8);

  gl_FragColor = vec4(min(col, vec3(2000.0)), 1.0);
}
`;

export const cloudFrag = /* glsl */ `
${FRAG_HEAD}
${ATMOSPHERE}
${GEO}
${NOISE}
uniform sampler2D uClouds;
uniform sampler2D uLights;
uniform vec3 uSun;
uniform vec3 uCam;
uniform float uSunE;
uniform float uTime;
uniform float uCloudDrift;
uniform float uLightsGain;

float coverage(vec2 uv, vec3 p) {
  float base = pow(texture2D(uClouds, uv).r, 0.7);
  vec3 q = p + vec3(0.0, 0.0, uTime * 0.0015);
  float warp = fbm(q * 3.0, 3);
  float lo = fbm(q * 7.0 + warp * 1.6, 4);
  float hi = fbm(p * 52.0 + lo * 2.0, 3);
  float c = base * 1.12 + (lo - 0.5) * 0.42 + (hi - 0.5) * 0.32 * (1.0 - base * 0.6);
  return smoothstep(0.08, 0.82, c);
}

void main() {
  #include <logdepthbuf_fragment>
  vec3 p = normalize(vPos);
  float d = coverage(vUv, p);
  if (d < 0.003) discard;

  vec3 L = uSun;
  vec3 V = normalize(uCam - vPos);
  float NL = dot(p, L);
  float r = length(vPos);

  // Self-shadow: how much cloud lies toward the sun.
  float ds = textureLod(uClouds, dirToUv(normalize(p + L * 0.01)), 2.0).r;
  float selfShadow = mix(1.0, 0.55, smoothstep(0.2, 0.9, ds) * d);

  vec3 sun = uSunE * transmittance(r, NL);
  float wrap = clamp((NL + 0.08) / 1.08, 0.0, 1.0);
  // Forward scattering — silver lining when looking toward the sun across the limb.
  float fwd = pow(max(dot(-V, L), 0.0), 8.0) * (1.0 - d) * 2.5;
  vec3 col = vec3(0.92) / PI_ * sun * (wrap * selfShadow + fwd);
  col += vec3(0.08, 0.12, 0.22) * uSunE * 0.03 * smoothstep(-0.2, 0.3, NL);

  // City glow diffusing through clouds at night.
  vec2 luv = vec2(fract(vUv.x + uCloudDrift / (2.0 * PI_)), vUv.y);
  float glow = textureLod(uLights, luv, 4.5).r;
  float night = smoothstep(0.05, -0.15, NL);
  col += vec3(1.0, 0.55, 0.25) * glow * uLightsGain * 0.35 * night * d;

  gl_FragColor = vec4(min(col, vec3(2000.0)), d * 0.97);
}
`;

export const atmosphereFrag = /* glsl */ `
${FRAG_HEAD}
${ATMOSPHERE}
uniform vec3 uSunW;
uniform vec3 uCamW;
uniform float uSunE;
uniform float uFrame;

void main() {
  #include <logdepthbuf_fragment>
  vec3 ro = uCamW;
  vec3 rd = normalize(vWorld - uCamW);
  vec2 ta = raySphere(ro, rd, RA);
  if (ta.x > ta.y || ta.y < 0.0) discard;
  vec2 tp = raySphere(ro, rd, RP);
  float t0 = max(ta.x, 0.0);
  float t1 = ta.y;
  if (tp.x < tp.y && tp.x > 0.0) t1 = min(t1, tp.x);

  const int N = 24;
  float dt = (t1 - t0) / float(N);
  float jitter = ign(gl_FragCoord.xy + mod(uFrame, 64.0) * 5.588238);
  vec3 sumR = vec3(0.0), sumM = vec3(0.0);
  float odR = 0.0, odM = 0.0;
  for (int i = 0; i < N; i++) {
    vec3 pos = ro + rd * (t0 + (float(i) + jitter) * dt);
    float r = length(pos);
    float h = r - RP;
    float dR = exp(-h / HR) * dt;
    float dM = exp(-h / HM) * dt;
    odR += dR * 0.5; odM += dM * 0.5;
    vec3 tv = exp(-(BETA_R * odR + BETA_ME * odM + BETA_OZ * odR));
    vec3 att = transmittance(r, dot(pos / r, uSunW)) * tv;
    sumR += dR * att;
    sumM += dM * att;
    odR += dR * 0.5; odM += dM * 0.5;
  }
  // Artistic: thin the haze over the disc (Blue Marble is already haze-corrected),
  // keep the full physical glow along the limb.
  float impact = length(cross(ro, rd));
  float haze = mix(0.42, 1.0, smoothstep(0.96, 1.004, impact));
  float c = dot(rd, uSunW);
  vec3 L = haze * uSunE * (sumR * BETA_R * phaseRayleigh(c) + sumM * BETA_MS * phaseMie(c));
  vec3 T = exp(-(BETA_R * odR + BETA_ME * odM + BETA_OZ * odR));
  gl_FragColor = vec4(min(L, vec3(2000.0)), 1.0 - dot(T, vec3(0.3333)));
}
`;

export const moonFrag = /* glsl */ `
${FRAG_HEAD}
uniform sampler2D uColor;
uniform sampler2D uElev;
uniform vec3 uSun;
uniform vec3 uCam;
uniform vec3 uEarth;
uniform float uSunE;
uniform vec2 uTexel;
const float PI_ = 3.14159265359;

void main() {
  #include <logdepthbuf_fragment>
  vec3 p = normalize(vPos);
  vec3 east = normalize(vec3(p.z, 0.0, -p.x) + vec3(1e-6, 0.0, 0.0));
  vec3 north = cross(p, east);
  float coslat = max(sqrt(1.0 - p.y * p.y), 0.04);
  float hL = texture2D(uElev, vUv - vec2(uTexel.x, 0.0)).r;
  float hR = texture2D(uElev, vUv + vec2(uTexel.x, 0.0)).r;
  float hD = texture2D(uElev, vUv - vec2(0.0, uTexel.y)).r;
  float hU = texture2D(uElev, vUv + vec2(0.0, uTexel.y)).r;
  float su = (hR - hL) / (2.0 * uTexel.x) / (2.0 * PI_ * coslat) * 0.012;
  float sv = (hU - hD) / (2.0 * uTexel.y) / PI_ * 0.012;
  vec3 n = normalize(p - su * east - sv * north);

  vec3 V = normalize(uCam - vPos);
  float NL = max(dot(n, uSun), 0.0);
  float NV = max(dot(n, V), 0.0);
  // Lommel-Seeliger: the Moon's flat, limb-bright regolith response.
  float ls = 2.0 * NL / (NL + NV + 1e-4);
  vec3 albedo = texture2D(uColor, vUv).rgb * 1.15;
  vec3 col = albedo / PI_ * uSunE * ls * 0.9;
  // Earthshine
  col += albedo * vec3(0.4, 0.55, 0.85) * 0.0025 * uSunE * max(dot(n, uEarth), 0.0);
  gl_FragColor = vec4(min(col, vec3(2000.0)), 1.0);
}
`;
