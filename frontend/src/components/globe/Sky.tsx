"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { useTexture } from "@react-three/drei";
import * as THREE from "three";
import { clock } from "@/lib/sim";
import { DEG, equatorialDir } from "@/lib/astro";

const SKY_R = 4000;

const skyVert = /* glsl */ `
#include <common>
#include <logdepthbuf_pars_vertex>
varying vec3 vDir;
void main() {
  vDir = position;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  #include <logdepthbuf_vertex>
}
`;

// NASA SVS Deep Star Maps 2020 are equatorial, RA 0h at the centre, RA increasing leftward.
const milkyWayFrag = /* glsl */ `
#include <common>
#include <logdepthbuf_pars_fragment>
uniform sampler2D uMap;
uniform float uGain;
varying vec3 vDir;
void main() {
  #include <logdepthbuf_fragment>
  vec3 d = normalize(vDir);
  float ra = atan(-d.z, d.x);
  vec2 uv = vec2(fract(0.5 - ra / 6.28318530718), 0.5 + asin(clamp(d.y, -1.0, 1.0)) / 3.14159265);
  vec3 c = textureLod(uMap, uv, 0.0).rgb;
  c = max(c - 0.0035, 0.0) * uGain;
  gl_FragColor = vec4(c, 1.0);
}
`;

const starVert = /* glsl */ `
#include <common>
#include <logdepthbuf_pars_vertex>
attribute float aBright;
attribute vec3 aColor;
uniform float uPx;
varying vec3 vColor;
void main() {
  float b = aBright;
  vColor = aColor * pow(b, 0.42);
  gl_PointSize = (1.15 + 3.6 * pow(b, 0.28)) * uPx;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  #include <logdepthbuf_vertex>
}
`;

const starFrag = /* glsl */ `
#include <common>
#include <logdepthbuf_pars_fragment>
uniform float uGain;
varying vec3 vColor;
void main() {
  #include <logdepthbuf_fragment>
  vec2 q = gl_PointCoord - 0.5;
  float a = exp(-dot(q, q) * 18.0);
  gl_FragColor = vec4(vColor * a * uGain, 1.0);
}
`;

/** B−V colour index → linear RGB via Ballesteros' temperature formula + blackbody fit. */
function bvToRgb(bv: number): [number, number, number] {
  bv = THREE.MathUtils.clamp(bv, -0.4, 2.0);
  const t = 4600 * (1 / (0.92 * bv + 1.7) + 1 / (0.92 * bv + 0.62)) / 100;
  let r: number, g: number, b: number;
  if (t <= 66) {
    r = 255;
    g = 99.4708025861 * Math.log(t) - 161.1195681661;
    b = t <= 19 ? 0 : 138.5177312231 * Math.log(t - 10) - 305.0447927307;
  } else {
    r = 329.698727446 * Math.pow(t - 60, -0.1332047592);
    g = 288.1221695283 * Math.pow(t - 60, -0.0755148492);
    b = 255;
  }
  const lin = (v: number) => Math.pow(THREE.MathUtils.clamp(v, 0, 255) / 255, 2.2);
  // Desaturate slightly — real star colours are subtle to the eye.
  const c = [lin(r), lin(g), lin(b)];
  const l = 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  return c.map((v) => (l + (v - l) * 0.75) / Math.max(l, 1e-3)) as [number, number, number];
}

function Stars() {
  const [geo, setGeo] = useState<THREE.BufferGeometry | null>(null);
  const dpr = useThree((s) => s.viewport.dpr);

  useEffect(() => {
    let alive = true;
    fetch("/textures/stars.bin")
      .then((r) => r.arrayBuffer())
      .then((buf) => {
        if (!alive) return;
        // Hipparcos/Tycho to mag 7.8: [ra°, dec°, mag, B−V] float32
        const f = new Float32Array(buf);
        const n = f.length / 4;
        const pos = new Float32Array(n * 3);
        const bright = new Float32Array(n);
        const color = new Float32Array(n * 3);
        const v = new THREE.Vector3();
        for (let i = 0; i < n; i++) {
          equatorialDir(f[i * 4] * DEG, f[i * 4 + 1] * DEG, v).multiplyScalar(SKY_R * 0.9);
          pos.set([v.x, v.y, v.z], i * 3);
          bright[i] = Math.pow(10, -0.4 * (f[i * 4 + 2] + 1.46));
          color.set(bvToRgb(f[i * 4 + 3]), i * 3);
        }
        const g = new THREE.BufferGeometry();
        g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
        g.setAttribute("aBright", new THREE.BufferAttribute(bright, 1));
        g.setAttribute("aColor", new THREE.BufferAttribute(color, 3));
        setGeo(g);
      });
    return () => {
      alive = false;
    };
  }, []);

  const mat = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: starVert,
        fragmentShader: starFrag,
        uniforms: { uGain: { value: 3.2 }, uPx: { value: dpr } },
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      }),
    [dpr],
  );

  if (!geo) return null;
  return <points geometry={geo} material={mat} frustumCulled={false} renderOrder={0} />;
}

function MilkyWay() {
  const map = useTexture("/textures/milkyway_4k.jpg", (t) => {
    t.colorSpace = THREE.SRGBColorSpace;
  });
  const mat = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: skyVert,
        fragmentShader: milkyWayFrag,
        uniforms: { uMap: { value: map }, uGain: { value: 0.55 } },
        side: THREE.BackSide,
        depthWrite: false,
      }),
    [map],
  );
  return (
    <mesh material={mat} renderOrder={-1} frustumCulled={false}>
      <sphereGeometry args={[SKY_R, 64, 32]} />
    </mesh>
  );
}

const sunVert = /* glsl */ `
#include <common>
#include <logdepthbuf_pars_vertex>
varying vec2 vUv;
void main() {
  vUv = uv * 2.0 - 1.0;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  #include <logdepthbuf_vertex>
}
`;

const sunFrag = /* glsl */ `
#include <common>
#include <logdepthbuf_pars_fragment>
uniform float uDisk;
varying vec2 vUv;
void main() {
  #include <logdepthbuf_fragment>
  float r = length(vUv);
  float x = clamp(r / uDisk, 0.0, 1.0);
  // Limb darkening (Eddington approximation)
  float mu = sqrt(1.0 - x * x);
  float disk = (1.0 - smoothstep(0.96, 1.0, r / uDisk)) * (0.4 + 0.6 * mu);
  vec3 col = vec3(1.0, 0.97, 0.92) * disk * 400.0;
  col += vec3(1.0, 0.86, 0.68) * (exp(-r * 22.0) * 3.5 + exp(-r * 6.0) * 0.18);
  gl_FragColor = vec4(col, 1.0);
}
`;

const SUN_DIST = 3000;
const SUN_QUAD = 260;

function Sun() {
  const ref = useRef<THREE.Mesh>(null!);
  const mat = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: sunVert,
        fragmentShader: sunFrag,
        uniforms: { uDisk: { value: (SUN_DIST * Math.tan(0.267 * DEG)) / SUN_QUAD } },
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      }),
    [],
  );
  useFrame(({ camera }) => {
    ref.current.position.copy(clock.ephemeris.sunDir).multiplyScalar(SUN_DIST).add(camera.position);
    ref.current.quaternion.copy(camera.quaternion);
  });
  return (
    <mesh ref={ref} material={mat} renderOrder={1} frustumCulled={false}>
      <planeGeometry args={[SUN_QUAD * 2, SUN_QUAD * 2]} />
    </mesh>
  );
}

export function Sky() {
  const group = useRef<THREE.Group>(null!);
  // The sky is at infinity: follow the camera so it never shows parallax.
  useFrame(({ camera }) => group.current.position.copy(camera.position));
  return (
    <>
      <group ref={group}>
        <MilkyWay />
        <Stars />
      </group>
      <Sun />
    </>
  );
}
