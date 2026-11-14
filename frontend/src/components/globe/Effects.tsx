"use client";

import { useMemo } from "react";
import { useFrame } from "@react-three/fiber";
import { Bloom, EffectComposer, ToneMapping } from "@react-three/postprocessing";
import { BlendFunction, Effect, ToneMappingMode } from "postprocessing";
import * as THREE from "three";
import { clock } from "@/lib/sim";
import { ui } from "@/lib/ui";

const lensFrag = /* glsl */ `
uniform vec2 uSun;
uniform float uVis;
uniform float uAspect;
uniform float uExposure;

vec3 ghost(vec2 uv, vec2 c, float r, vec3 tint) {
  vec2 d = uv - c; d.x *= uAspect;
  float l = length(d);
  float disc = smoothstep(r, r * 0.55, l);
  float rim = smoothstep(r * 0.86, r, l) * smoothstep(r * 1.04, r, l);
  return tint * (disc * 0.5 + rim * 0.7);
}

void mainImage(const in vec4 inputColor, const in vec2 uv, out vec4 outputColor) {
  vec3 c = inputColor.rgb * uExposure;
  if (uVis > 0.001) {
    vec2 axis = vec2(0.5) - uSun;
    vec3 f = vec3(0.0);
    f += ghost(uv, uSun + axis * 0.55, 0.022, vec3(0.35, 0.55, 1.0)) * 0.5;
    f += ghost(uv, uSun + axis * 1.25, 0.075, vec3(0.45, 1.0, 0.65)) * 0.12;
    f += ghost(uv, uSun + axis * 1.6, 0.035, vec3(1.0, 0.6, 0.3)) * 0.3;
    f += ghost(uv, uSun + axis * 2.1, 0.13, vec3(0.55, 0.4, 1.0)) * 0.07;
    f += ghost(uv, uSun + axis * 2.6, 0.018, vec3(1.0, 0.85, 0.5)) * 0.4;
    vec2 d = uv - uSun; d.x *= uAspect;
    float l = length(d);
    float streak = exp(-abs(d.y) * 700.0) * exp(-abs(d.x) * 2.2);
    float halo = smoothstep(0.26, 0.29, l) * smoothstep(0.33, 0.29, l);
    vec3 halCol = mix(vec3(0.4, 0.6, 1.0), vec3(1.0, 0.6, 0.3), smoothstep(0.26, 0.33, l));
    c += (f * 0.6 + vec3(0.55, 0.72, 1.0) * streak * 1.4 + halCol * halo * 0.05) * uVis;
  }
  outputColor = vec4(c, inputColor.a);
}
`;

const gradeFrag = /* glsl */ `
uniform float uTime;

float hash(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }

void mainImage(const in vec4 inputColor, const in vec2 uv, out vec4 outputColor) {
  vec3 g = pow(clamp(inputColor.rgb, 0.0, 1.0), vec3(1.0 / 2.2));
  // Gentle S-curve
  g = mix(g, g * g * (3.0 - 2.0 * g), 0.22);
  float l = dot(g, vec3(0.2126, 0.7152, 0.0722));
  // Split-tone: cool, deep shadows; warm, sunlit highlights
  g += vec3(-0.006, 0.002, 0.016) * (1.0 - smoothstep(0.0, 0.45, l));
  g += vec3(0.022, 0.008, -0.018) * smoothstep(0.5, 1.0, l);
  // Vibrance — lifts muted colours more than saturated ones
  float sat = max(max(g.r, g.g), g.b) - min(min(g.r, g.g), g.b);
  g = mix(vec3(l), g, 1.0 + 0.3 * (1.0 - sat));
  // Vignette
  vec2 q = uv - 0.5;
  g *= 1.0 - dot(q, q) * 0.55;
  // Film grain, luminance-weighted
  float n = hash(uv * 1024.0 + fract(uTime) * 91.7) - 0.5;
  g += n * 0.022 * (1.0 - l * 0.6);
  outputColor = vec4(pow(max(g, 0.0), vec3(2.2)), inputColor.a);
}
`;

class LensEffect extends Effect {
  constructor() {
    super("LensEffect", lensFrag, {
      blendFunction: BlendFunction.SRC,
      uniforms: new Map<string, THREE.Uniform>([
        ["uSun", new THREE.Uniform(new THREE.Vector2())],
        ["uVis", new THREE.Uniform(0)],
        ["uAspect", new THREE.Uniform(1)],
        ["uExposure", new THREE.Uniform(1)],
      ]),
    });
  }
}

class GradeEffect extends Effect {
  constructor() {
    super("GradeEffect", gradeFrag, {
      blendFunction: BlendFunction.SRC,
      uniforms: new Map<string, THREE.Uniform>([["uTime", new THREE.Uniform(0)]]),
    });
  }
  update(_r: THREE.WebGLRenderer, _i: THREE.WebGLRenderTarget, dt?: number) {
    this.uniforms.get("uTime")!.value += dt ?? 0.016;
  }
}

const sunPos = new THREE.Vector3();
const camNorm = new THREE.Vector3();
const GLOW_DAY = new THREE.Color(130 / 255, 176 / 255, 1);
const GLOW_SUN = new THREE.Color(1, 196 / 255, 140 / 255);
const glowColor = new THREE.Color();
let glowFrame = 0;
let lastGlow = "";

/**
 * Feeds the search bar's glow from the scene: brighter and bluer over the sunlit side,
 * warm when the Sun itself is in view, shifted toward the Sun's side of the screen.
 */
function writeGlow(sunX: number, dayFacing: number, sunVis: number) {
  if (glowFrame++ % 6 !== 0) return;
  const mode = ui.get().mode;
  if (mode !== "globe" && !(mode === "searching" && ui.get().searchFrom === "globe")) return;
  const strength = THREE.MathUtils.clamp(0.18 + 0.5 * dayFacing + 0.55 * sunVis, 0, 1);
  glowColor.copy(GLOW_DAY).lerp(GLOW_SUN, THREE.MathUtils.clamp(sunVis * 1.4, 0, 1));
  const x = THREE.MathUtils.clamp(sunX * 0.5 + 0.5, 0.08, 0.92);
  const key = `${glowColor.getHexString()}${strength.toFixed(2)}${x.toFixed(2)}`;
  if (key === lastGlow) return;
  lastGlow = key;
  const root = document.documentElement.style;
  root.setProperty("--glow-color", `#${glowColor.getHexString()}`);
  root.setProperty("--glow-strength", strength.toFixed(2));
  root.setProperty("--glow-x", `${(x * 100).toFixed(1)}%`);
}
const toSun = new THREE.Vector3();
const camDir = new THREE.Vector3();

/** How much of the Sun is visible: Earth (with a soft atmospheric edge) and Moon occlude. */
function sunVisibility(cam: THREE.Vector3, dir: THREE.Vector3, moon: THREE.Vector3, moonR: number) {
  const occl = (center: THREE.Vector3, r: number, soft: number) => {
    toSun.copy(center).sub(cam);
    const t = toSun.dot(dir);
    if (t < 0) return 1;
    const miss = Math.sqrt(Math.max(toSun.lengthSq() - t * t, 0));
    return THREE.MathUtils.smoothstep(miss, r, r + soft);
  };
  return occl(new THREE.Vector3(), 1.0, 0.03) * occl(moon, moonR, 0.004);
}

export function Effects({ exposure = 0.72 }: { exposure?: number }) {
  const lens = useMemo(() => new LensEffect(), []);
  const grade = useMemo(() => new GradeEffect(), []);

  useFrame(({ camera, size }) => {
    const eph = clock.ephemeris;
    const u = lens.uniforms;
    sunPos.copy(eph.sunDir).multiplyScalar(1e4).add(camera.position).project(camera);
    camera.getWorldDirection(camDir);
    const facing = camDir.dot(eph.sunDir);
    const onScreen = 1 - THREE.MathUtils.smoothstep(Math.max(Math.abs(sunPos.x), Math.abs(sunPos.y)), 0.9, 1.4);
    const vis = facing > 0 ? onScreen * sunVisibility(camera.position, eph.sunDir, eph.moonPos, 0.2727) : 0;
    u.get("uSun")!.value.set(sunPos.x * 0.5 + 0.5, sunPos.y * 0.5 + 0.5);
    u.get("uVis")!.value = vis;
    u.get("uAspect")!.value = size.width / size.height;
    u.get("uExposure")!.value = exposure;
    writeGlow(facing > 0 ? sunPos.x : -Math.sign(sunPos.x), Math.max(0, camNorm.copy(camera.position).normalize().dot(eph.sunDir)), vis);
  });

  return (
    <EffectComposer multisampling={4} frameBufferType={THREE.HalfFloatType}>
      <primitive object={lens} />
      <Bloom mipmapBlur intensity={0.6} luminanceThreshold={2.6} luminanceSmoothing={0.5} radius={0.7} />
      <ToneMapping mode={ToneMappingMode.AGX} />
      <primitive object={grade} />
    </EffectComposer>
  );
}
