"use client";

import { useEffect, useRef } from "react";
import { DIVE, SWITCH, ui } from "@/lib/ui";
import { bearing, imageUrl, type Candidate } from "@/lib/candidates";
import { ease, lerp, span } from "@/lib/motion";
import { CLOUD_DECKS, diveLogH, globeMix, groundFrame, imageMix, surfaceLogH } from "@/lib/flight";

// The satellite view as a tiny flight renderer. A virtual camera hangs at altitude h
// over a ground plane holding the HLS images; cloud decks are planes at fixed
// altitudes between them. Projection does the rest: the ground grows as the camera
// falls, near decks race outward faster than far ones, and a sideways move parallaxes
// every layer by its own depth. Motion blur follows each pixel's true screen velocity.

/** Travel decks (3) first, then the fixed decks: all sorted low to high. */
const DECK_COUNT = 3 + CLOUD_DECKS.length;

const NOISE = /* glsl */ `
float hash(vec2 p) {
  vec3 p3 = fract(vec3(p.xyx) * 0.1031);
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.x + p3.y) * p3.z);
}
float noise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1, 0)), u.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), u.x), u.y);
}
const mat2 ROT = mat2(0.8, -0.6, 0.6, 0.8);
float fbm(vec2 p, int oct) {
  float s = 0.0, a = 0.5;
  for (int i = 0; i < 6; i++) {
    if (i >= oct) break;
    s += a * noise(p);
    p = ROT * p * 2.03 + vec2(1.7, 9.2);
    a *= 0.5;
  }
  return s;
}
`;

const VERT = /* glsl */ `#version 300 es
in vec2 p;
void main() { gl_Position = vec4(p, 0.0, 1.0); }
`;

const CLOUD_FRAG = /* glsl */ `#version 300 es
precision highp float;
uniform vec2 uRes;
uniform vec2 uAnchor;
uniform vec3 uCam;
uniform vec4 uDecks[${DECK_COUNT}];
uniform float uTime;
out vec4 outColor;
${NOISE}
void main() {
  vec2 q = (gl_FragCoord.xy - uAnchor) / uRes.y;
  q.y = -q.y;
  vec3 C = vec3(0.0);
  float A = 0.0;
  // Far (low) decks first, nearest last.
  for (int i = 0; i < ${DECK_COUNT}; i++) {
    vec4 L = uDecks[i];
    float d = uCam.z - L.x;
    if (d <= 0.0) break;
    // Fade in as the deck slips under the camera, out with distance below.
    float vis = smoothstep(0.0, 0.2, d) * (1.0 - smoothstep(2.6, 6.0, d)) * L.z;
    if (vis < 0.003) continue;
    vec2 p = (uCam.xy + q * d) * 1.6 + vec2(17.3, 9.1) * L.w + uTime * vec2(0.010, 0.004);
    p += (vec2(fbm(p * 0.55, 3), fbm(p * 0.55 + 4.7, 3)) - 0.5) * 1.1;
    float n = fbm(p, 5);
    float lo = 0.66 - L.y * 0.36;
    float dens = smoothstep(lo, lo + 0.2, n);
    if (dens < 0.002) continue;
    // Sun from the upper left: brighter where density falls off toward it.
    float n2 = fbm(p + vec2(-0.09, -0.07), 5);
    float lit = clamp(0.7 + (n - n2) * 4.0, 0.0, 1.0);
    // Soft, sunlit decks: shade stays a pale blue-grey, never a dark shadow.
    vec3 col = mix(vec3(0.76, 0.8, 0.87), vec3(1.0, 0.99, 0.97), lit);
    col = mix(col, vec3(0.92, 0.95, 1.0), smoothstep(0.6, 0.0, d) * 0.5);
    float a = dens * vis;
    C = col * a + C * (1.0 - a);
    A = a + A * (1.0 - a);
  }
  outColor = vec4(C, A);
}
`;

const COMPOSITE_FRAG = /* glsl */ `#version 300 es
precision highp float;
uniform sampler2D uImgA;
uniform sampler2D uImgB;
uniform sampler2D uClouds;
uniform vec2 uRes;
uniform vec2 uAnchor;
uniform vec3 uCam;
uniform vec3 uVel;
uniform vec2 uHalf;
uniform vec2 uPosB;
uniform float uHasA;
uniform float uHasB;
uniform float uImgMix;
uniform float uGlobeMix;
uniform float uClouded;
uniform float uNearD;
uniform float uTime;
out vec4 outColor;

const float SHUTTER = 0.022;

// One image on the ground plane. Beyond its border it smears out into its own blurred
// colour (high mip levels), so neighbours blend into each other with no seam.
void img(sampler2D tex, vec2 P, inout vec3 sum, inout float wsum, inout float inside) {
  vec2 uv = P / (2.0 * uHalf) + 0.5;
  vec2 out2 = max(abs(uv - 0.5) - 0.5, 0.0) * 2.0 * uHalf;
  float od = length(out2);
  vec2 in2 = (0.5 - abs(uv - 0.5)) * 2.0 * uHalf;
  // Wide, soft feather: the sharp image dissolves into the globe rather than sitting on it.
  vec2 e = smoothstep(vec2(0.0), vec2(0.42), in2);
  inside = max(inside, e.x * e.y);
  float w = exp(-od * 5.0) + 1e-3;
  // Blur ramps up approaching the border and keeps growing beyond it: no edge, no stretched pixels.
  float edge = 1.0 - smoothstep(0.0, 0.14, min(in2.x, in2.y));
  sum += texture(tex, clamp(uv, 0.0, 1.0), 5.0 * edge + od * 30.0).rgb * w;
  wsum += w;
}

void ground(vec2 q, inout vec3 col, inout float inside) {
  vec2 P = uCam.xy + q * uCam.z;
  vec3 sum = vec3(0.0);
  float wsum = 0.0;
  if (uHasA > 0.5) img(uImgA, P, sum, wsum, inside);
  if (uHasB > 0.5) img(uImgB, P - uPosB, sum, wsum, inside);
  col += wsum > 0.0 ? sum / wsum : vec3(0.08);
}

void main() {
  vec2 q = (gl_FragCoord.xy - uAnchor) / uRes.y;
  q.y = -q.y;
  // Screen velocity of the ground under this pixel: dq/dt = -(v_xy + q v_h) / h.
  vec2 vel = -(uVel.xy + q * uVel.z) / uCam.z;
  vec2 streak = vel * SHUTTER;
  float sl = length(streak);
  if (sl > 0.07) streak *= 0.07 / sl;
  float px = length(streak) * uRes.y;
  int taps = int(clamp(px / 1.6, 1.0, 16.0));
  vec3 col = vec3(0.0);
  float inside = 0.0;
  for (int i = 0; i < 16; i++) {
    if (i >= taps) break;
    float f = taps == 1 ? 0.0 : float(i) / float(taps - 1) - 0.5;
    ground(q + streak * f, col, inside);
  }
  col /= float(taps);
  inside = min(inside, 1.0);
  // Aerial perspective: higher up, more atmosphere between camera and ground.
  col = mix(col, vec3(0.58, 0.66, 0.78), 0.32 * smoothstep(1.05, 6.0, uCam.z));
  float gA = mix(1.0, inside * uImgMix, uGlobeMix);

  vec4 cl = vec4(0.0);
  if (uClouded > 0.5) {
    // Clouds streak with the nearest deck's motion.
    vec2 cv = -(uVel.xy + q * uVel.z) / max(uNearD, 0.12) * SHUTTER;
    vec2 cuv = gl_FragCoord.xy / uRes;
    vec2 step2 = vec2(cv.x * uRes.y / uRes.x, -cv.y);
    float l = length(step2);
    if (l > 0.035) step2 *= 0.035 / l;
    for (int i = 0; i < 6; i++) cl += texture(uClouds, cuv + step2 * (float(i) / 5.0 - 0.5));
    cl /= 6.0;
  }
  vec3 rgb = cl.rgb + col * gA * (1.0 - cl.a);
  float a = cl.a + gA * (1.0 - cl.a);
  // Film grain to match the globe's grade.
  float g = fract(sin(dot(gl_FragCoord.xy + fract(uTime) * 91.7, vec2(12.9898, 78.233))) * 43758.5453) - 0.5;
  rgb += g * 0.024 * a;
  outColor = vec4(max(rgb, 0.0), a);
}
`;

interface Pose {
  x: number;
  y: number;
  h: number;
  /** Density of the low travel clouds skimmed during a switch (0..1). */
  cloud?: number;
  /** Normalised flight speed (0..1) during a switch. */
  intensity?: number;
}

/** Sideways distance between neighbouring candidates on the virtual ground plane. */
const SWITCH_DISTANCE = 3.2;
/** Altitude multiplier at top speed: a drone pops up a little, it doesn't climb away. */
const SWITCH_LIFT = 1.4;
/**
 * Speed profile shape, v(s) = s^A (1 - s)^B: a slow push-off (A), a hard build to one
 * sharp peak at A / (A + B) ≈ 38% of the way, then a long, soft glide in (B).
 */
const SURGE_A = 2.0;
const SURGE_B = 3.3;
/**
 * Low cloud layers skimmed during a switch, below the resting camera so they only show
 * when the travel envelope brings them in: altitude, coverage, opacity, seed.
 */
const TRAVEL_DECKS: [number, number, number, number][] = [
  [0.56, 0.55, 0.85, 7.0],
  [0.7, 0.6, 0.9, 8.0],
  [0.83, 0.62, 0.9, 9.0],
];

/**
 * Drone flight profile. Distance is the integral of the speed curve; everything else
 * hangs off the speed: the drone rides higher, the clouds close in and the blur
 * stretches the faster it goes, so climb, travel and cover always move as one.
 */
const PEAK_S = SURGE_A / (SURGE_A + SURGE_B);
const rawSpeed = (s: number) => Math.pow(Math.max(s, 0), SURGE_A) * Math.pow(Math.max(1 - s, 0), SURGE_B);
const PEAK_V = rawSpeed(PEAK_S);
/** Normalised speed, 0..1 with 1 at the peak. */
const speedAt = (s: number) => rawSpeed(Math.min(Math.max(s, 0), 1)) / PEAK_V;
const TRAVEL = (() => {
  const n = 512;
  const table = new Float32Array(n + 1);
  for (let i = 1; i <= n; i++) table[i] = table[i - 1] + speedAt((i - 0.5) / n) / n;
  return table.map((v) => v / table[n]);
})();
function travelled(s: number) {
  const x = Math.min(Math.max(s, 0), 1) * (TRAVEL.length - 1);
  const i = Math.min(Math.floor(x), TRAVEL.length - 2);
  return lerp(TRAVEL[i], TRAVEL[i + 1], x - i);
}

/** Slow breathing over the still image: starts from rest so it never jolts. */
function drift(t: number): Pose {
  // A slow push in and out about the site itself, so it never wanders off the marker.
  const w = (1 - Math.cos(t * 0.13)) / 2;
  return { x: 0, y: 0, h: 1 - 0.045 * w };
}

/** Point on the rising side of the speed curve where normalised speed equals v. */
function surgeAt(v: number) {
  if (v <= 0) return 0;
  let lo = 0, hi = PEAK_S;
  for (let i = 0; i < 24; i++) {
    const mid = (lo + hi) / 2;
    if (speedAt(mid) < v) lo = mid;
    else hi = mid;
  }
  return (lo + hi) / 2;
}

/**
 * A flight to `to`. When it interrupts another flight it never restarts: it joins the
 * speed curve at the speed the drone already has (and is shortened to match), and the
 * current velocity is carried forward and bled off smoothly, so the camera banks
 * round from its old heading onto the new one.
 */
function makeSwitch(at: number, from: Pose, v0: [number, number], to: [number, number]) {
  const i0 = Math.min(from.intensity ?? 0, 1);
  const s0 = surgeAt(i0);
  const T = Math.max(SWITCH.total * (1 - s0), 1.0);
  const p0 = travelled(s0);
  const pAt = (s: number) => (travelled(s) - p0) / (1 - p0);
  // Velocity the new run already has at its start, so the carry only adds the difference.
  const e = 1e-3;
  const dp = (pAt(s0 + ((1 - s0) * e) / T) - pAt(s0)) / e;
  const carry: [number, number] = [v0[0] - (to[0] - from.x) * dp, v0[1] - (to[1] - from.y) * dp];
  const baseH0 = from.h / (1 + (SWITCH_LIFT - 1) * i0);

  const pose = (n: number): Pose => {
    const t = Math.min(Math.max((n - at) / 1000, 0), T);
    const s = s0 + (t / T) * (1 - s0);
    const p = pAt(s);
    const v = speedAt(s);
    // f(0) = 0, f'(0) = 1, f(T) = f'(T) = 0: inherits the old velocity, lands exactly.
    const f = t * (1 - t / T) ** 2;
    const h = Math.exp(lerp(Math.log(baseH0), 0, p)) * (1 + (SWITCH_LIFT - 1) * v);
    // Cloud cover leads the speed a little: it's whited out right through the fastest stretch.
    const c = Math.min(v * 1.35, 1);
    return {
      x: lerp(from.x, to[0], p) + carry[0] * f,
      y: lerp(from.y, to[1], p) + carry[1] * f,
      h,
      cloud: c * c * (3 - 2 * c),
      intensity: v,
    };
  };
  return { pose, end: at + T * 1000 };
}

function setGlowFrom(c: Candidate | undefined) {
  if (!c) return;
  const [r, g, b] = c.avgColor;
  const lift = (v: number) => Math.round(v + (255 - v) * 0.35);
  const root = document.documentElement.style;
  root.setProperty("--glow-color", `rgb(${lift(r)} ${lift(g)} ${lift(b)})`);
  root.setProperty("--glow-strength", "0.5");
  root.setProperty("--glow-x", "50%");
}

export function SiteRenderer() {
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const el = canvas.current!;
    const gl = el.getContext("webgl2", { premultipliedAlpha: true, alpha: true, antialias: false, depth: false, stencil: false });
    if (!gl) return;

    const compile = (type: number, src: string) => {
      const s = gl.createShader(type)!;
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS) && !gl.isContextLost()) console.error(gl.getShaderInfoLog(s));
      return s;
    };
    const program = (frag: string) => {
      const p = gl.createProgram()!;
      gl.attachShader(p, compile(gl.VERTEX_SHADER, VERT));
      gl.attachShader(p, compile(gl.FRAGMENT_SHADER, frag));
      gl.bindAttribLocation(p, 0, "p");
      gl.linkProgram(p);
      const cache = new Map<string, WebGLUniformLocation | null>();
      const loc = (n: string) => {
        if (!cache.has(n)) cache.set(n, gl.getUniformLocation(p, n));
        return cache.get(n)!;
      };
      return { p, loc };
    };
    const cloudProg = program(CLOUD_FRAG);
    const compProg = program(COMPOSITE_FRAG);

    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);

    // Half-resolution cloud target: the decks are soft, the ground stays full resolution.
    const cloudTex = gl.createTexture();
    const fbo = gl.createFramebuffer();
    let cloudW = 1, cloudH = 1;
    const allocClouds = () => {
      gl.bindTexture(gl.TEXTURE_2D, cloudTex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, cloudW, cloudH, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, cloudTex, 0);
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    };

    const resize = () => {
      const s = Math.min(window.devicePixelRatio || 1, 1.5);
      el.width = Math.max(1, Math.round(el.clientWidth * s));
      el.height = Math.max(1, Math.round(el.clientHeight * s));
      cloudW = Math.max(1, Math.ceil(el.width / 2));
      cloudH = Math.max(1, Math.ceil(el.height / 2));
      allocClouds();
    };
    resize();
    window.addEventListener("resize", resize);

    // Imagery: decoded off the main thread, uploaded with mipmaps (they make the smear
    // beyond each image's edge). Placeholder until ready.
    const blank = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, blank);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([20, 20, 22, 255]));
    const textures = new Map<string, WebGLTexture | null>();
    const pending: { id: string; bitmap: ImageBitmap }[] = [];
    let disposed = false;
    const request = (id: string) => {
      if (textures.has(id)) return;
      textures.set(id, null);
      fetch(imageUrl(id))
        .then((r) => r.blob())
        .then((b) => createImageBitmap(b))
        .then((bitmap) => (disposed ? bitmap.close() : pending.push({ id, bitmap })))
        .catch(() => textures.delete(id));
    };
    const uploadOne = () => {
      const next = pending.shift();
      if (!next) return;
      const tex = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, gl.RGBA, gl.UNSIGNED_BYTE, next.bitmap);
      gl.generateMipmap(gl.TEXTURE_2D);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      next.bitmap.close();
      textures.set(next.id, tex);
    };

    // ---- Flight state -------------------------------------------------------------
    // Images live on the ground plane: `a` at the origin, `b` (mid-switch) at bPos.
    type Path = (now: number) => Pose;
    let scene: { a: Candidate | null; b: Candidate | null; bPos: [number, number] } = { a: null, b: null, bPos: [0, 0] };
    let path: Path | null = null;
    let pathEnd = Infinity;
    let seenSeq = -1;
    let seenTransition = -1;
    let glowFor: string | null = null;

    const steady = (from: number): Path => (now) => drift((now - from) / 1000);

    const sync = (now: number) => {
      const s = ui.get();
      const current = s.results[s.active];
      s.results.forEach((c) => request(c.id));

      if (s.mode === "diving" && s.transitionAt !== seenTransition && current) {
        seenTransition = s.transitionAt;
        seenSeq = s.switchSeq;
        scene = { a: current, b: null, bPos: [0, 0] };
        const at = s.transitionAt;
        path = (n) => ({ x: 0, y: 0, h: Math.exp(diveLogH((n - at) / 1000)) });
        pathEnd = at + DIVE.total * 1000;
      } else if (s.mode === "surfacing" && s.transitionAt !== seenTransition) {
        seenTransition = s.transitionAt;
        if (scene.b) scene = { a: scene.b, b: null, bPos: [0, 0] };
        const at = s.transitionAt;
        const from = path ? path(now) : { x: 0, y: 0, h: 1 };
        const fromLogH = Math.log(from.h);
        path = (n) => {
          const t = (n - at) / 1000;
          const settle = 1 - ease.smoother(span(t, 0, 0.8));
          return { x: from.x * settle, y: from.y * settle, h: Math.exp(surfaceLogH(t, fromLogH)) };
        };
        pathEnd = Infinity;
      } else if ((s.mode === "site" || s.mode === "searching") && s.switchSeq !== seenSeq && current && path) {
        seenSeq = s.switchSeq;
        // Leave from wherever the camera is right now, at the speed it's moving, keeping
        // whichever image it's nearer to (mid-flight that may still be the one it left).
        let pose = path(now);
        const prev = path(now - 16);
        const v0: [number, number] = [(pose.x - prev.x) / 0.016, (pose.y - prev.y) / 0.016];
        let from = scene.a;
        if (scene.b && Math.hypot(pose.x - scene.bPos[0], pose.y - scene.bPos[1]) <= Math.hypot(pose.x, pose.y)) {
          pose = { ...pose, x: pose.x - scene.bPos[0], y: pose.y - scene.bPos[1] };
          from = scene.b;
        }
        // Head along the true bearing from that image to the new one.
        let [dx, dy] = s.switchDir;
        if (from && from.id !== current.id) {
          const b = bearing(from, current);
          [dx, dy] = [Math.sin(b), -Math.cos(b)];
        }
        // Turning back to the image it's still nearest: just glide back onto it.
        const back = from?.id === current.id;
        const to: [number, number] = back ? [0, 0] : [dx * SWITCH_DISTANCE, dy * SWITCH_DISTANCE];
        scene = back ? { a: from, b: null, bPos: [0, 0] } : { a: from, b: current, bPos: to };
        const flightPath = makeSwitch(s.transitionAt, pose, v0, to);
        path = flightPath.pose;
        pathEnd = flightPath.end;
      }

      // A finished move settles into the drift, rebased onto the image it arrived at.
      if (path && now >= pathEnd) {
        if (scene.b) scene = { a: scene.b, b: null, bPos: [0, 0] };
        path = steady(pathEnd);
        pathEnd = Infinity;
      }
    };

    const decks = new Float32Array(DECK_COUNT * 4);
    decks.set(CLOUD_DECKS.flat(), 12);
    const start = performance.now();
    let raf = 0;
    let shown = false;

    const frame = () => {
      raf = requestAnimationFrame(frame);
      // Same clock as ui.transitionAt and the globe camera, so both sides stay in lockstep.
      const now = performance.now();
      const s = ui.get();
      const active =
        s.mode === "diving" || s.mode === "site" || s.mode === "surfacing" || (s.mode === "searching" && s.searchFrom === "site");
      if (!active) {
        if (shown) {
          el.style.visibility = "hidden";
          shown = false;
        }
        path = null;
        return;
      }
      sync(now);
      uploadOne();
      if (!path || !scene.a) return;

      const pose = path(now);
      const prev = path(now - 8);
      const vel = [(pose.x - prev.x) / 0.008, (pose.y - prev.y) / 0.008, (pose.h - prev.h) / 0.008];
      const flying = s.mode === "diving" || s.mode === "surfacing";
      const iMix = flying ? imageMix(pose.h) : 1;
      const gMix = flying ? globeMix(pose.h) : 0;

      // Search bar glow takes on whichever image the camera is over.
      const over = scene.b && Math.hypot(pose.x - scene.bPos[0], pose.y - scene.bPos[1]) < Math.hypot(pose.x, pose.y) ? scene.b : scene.a;
      if (iMix > 0.5 && over.id !== glowFor) {
        glowFor = over.id;
        setGlowFrom(over);
      }
      if (s.mode === "surfacing" && iMix < 0.5) glowFor = null;

      if (!shown) {
        el.style.visibility = "visible";
        shown = true;
      }
      const W = el.width, H = el.height;
      const f = groundFrame(el.clientWidth, el.clientHeight, over.imagery.metersPerPixel);
      const time = (now - start) / 1000;

      // Nearest deck below the camera, for cloud streaks; skip the pass entirely when none are.
      // Travel decks fade in and out with the switch envelope.
      const cloud = pose.cloud ?? 0;
      TRAVEL_DECKS.forEach(([alt, cov, op, seed], i) => decks.set([alt, cov * (0.55 + 0.45 * cloud), op * cloud, seed], i * 4));
      let nearD = Infinity;
      for (let i = 0; i < DECK_COUNT; i++) {
        const d = pose.h - decks[i * 4];
        if (d > 0 && decks[i * 4 + 2] > 0.01) nearD = Math.min(nearD, d);
      }
      const clouded = nearD < 6;

      if (clouded) {
        gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
        gl.viewport(0, 0, cloudW, cloudH);
        gl.useProgram(cloudProg.p);
        gl.uniform2f(cloudProg.loc("uRes"), cloudW, cloudH);
        gl.uniform2f(cloudProg.loc("uAnchor"), f.anchorX * cloudW, (1 - f.anchorY) * cloudH);
        gl.uniform3f(cloudProg.loc("uCam"), pose.x, pose.y, pose.h);
        gl.uniform4fv(cloudProg.loc("uDecks"), decks);
        gl.uniform1f(cloudProg.loc("uTime"), time);
        gl.drawArrays(gl.TRIANGLES, 0, 3);
        gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      }

      gl.viewport(0, 0, W, H);
      gl.useProgram(compProg.p);
      const L = compProg.loc;
      const bind = (unit: number, tex: WebGLTexture | null | undefined, name: string) => {
        gl.activeTexture(gl.TEXTURE0 + unit);
        gl.bindTexture(gl.TEXTURE_2D, tex ?? blank);
        gl.uniform1i(L(name), unit);
      };
      const texA = textures.get(scene.a.id);
      const texB = scene.b ? textures.get(scene.b.id) : null;
      bind(0, texA, "uImgA");
      bind(1, texB, "uImgB");
      bind(2, cloudTex, "uClouds");
      gl.uniform2f(L("uRes"), W, H);
      gl.uniform2f(L("uAnchor"), f.anchorX * W, (1 - f.anchorY) * H);
      gl.uniform3f(L("uCam"), pose.x, pose.y, pose.h);
      gl.uniform3f(L("uVel"), vel[0], vel[1], vel[2]);
      gl.uniform2f(L("uHalf"), f.halfW, f.halfH);
      gl.uniform2f(L("uPosB"), scene.bPos[0], scene.bPos[1]);
      gl.uniform1f(L("uHasA"), texA ? 1 : 0);
      gl.uniform1f(L("uHasB"), texB ? 1 : 0);
      gl.uniform1f(L("uImgMix"), texA ? iMix : 0);
      gl.uniform1f(L("uGlobeMix"), gMix);
      gl.uniform1f(L("uClouded"), clouded ? 1 : 0);
      gl.uniform1f(L("uNearD"), Math.min(nearD, 10));
      gl.uniform1f(L("uTime"), time);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    };
    raf = requestAnimationFrame(frame);

    return () => {
      disposed = true;
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      pending.forEach((p) => p.bitmap.close());
      // Free GPU objects but keep the context: React may remount on the same canvas.
      textures.forEach((t) => t && gl.deleteTexture(t));
      gl.deleteTexture(cloudTex);
      gl.deleteTexture(blank);
      gl.deleteFramebuffer(fbo);
      gl.deleteBuffer(buf);
      gl.deleteProgram(cloudProg.p);
      gl.deleteProgram(compProg.p);
    };
  }, []);

  return <canvas ref={canvas} aria-hidden className="pointer-events-none fixed inset-0 z-[9] h-full w-full" style={{ visibility: "hidden" }} />;
}
