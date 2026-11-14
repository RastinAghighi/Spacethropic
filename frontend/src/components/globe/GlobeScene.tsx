"use client";

import { Suspense, useLayoutEffect, useRef } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { advanceClock } from "@/lib/sim";
import { areStarsLoaded, ui } from "@/lib/ui";
import { Earth } from "./Earth";
import { Sky } from "./Sky";
import { Moon } from "./Moon";
import { Effects } from "./Effects";
import { Intro } from "./Intro";
import { AdaptiveResolution } from "./AdaptiveResolution";

function Clock() {
  useFrame(() => advanceClock(), -1);
  return null;
}

/**
 * Mounted once every Suspense asset has resolved. Compiles all shaders up front, then
 * lets a few frames render (texture uploads, post-processing) behind the loader before
 * declaring the scene ready — so the reveal never hitches.
 */
function Warmup() {
  const gl = useThree((s) => s.gl);
  const scene = useThree((s) => s.scene);
  const camera = useThree((s) => s.camera);
  const frames = useRef(0);
  useLayoutEffect(() => {
    gl.compile(scene, camera);
  }, [gl, scene, camera]);
  useFrame(() => {
    if (ui.get().ready || !areStarsLoaded()) return;
    frames.current += 1;
    if (frames.current >= 4) ui.setReady();
  });
  return null;
}

function Controls() {
  // Slow rotation near the surface so close-ups stay controllable.
  useFrame(({ camera, controls }) => {
    const c = controls as unknown as OrbitControlsImpl | null;
    if (!c) return;
    const alt = camera.position.length() - 1;
    c.rotateSpeed = THREE.MathUtils.clamp(alt / 2.4, 0.04, 0.5);
  });
  return (
    <OrbitControls
      makeDefault
      enablePan={false}
      enableDamping
      dampingFactor={0.06}
      zoomSpeed={0.6}
      minDistance={1.08}
      maxDistance={90}
    />
  );
}

export default function GlobeScene() {
  return (
    <Canvas
      dpr={[1, 2]}
      camera={{ position: [0, 0, 6], fov: 35, near: 0.002, far: 20000 }}
      gl={{
        antialias: false,
        logarithmicDepthBuffer: true,
        toneMapping: THREE.NoToneMapping,
        powerPreference: "high-performance",
      }}
      style={{ position: "fixed", inset: 0, background: "#000" }}
    >
      <Clock />
      <Suspense fallback={null}>
        <Sky />
        <Moon />
        <Earth />
        <Effects />
        <Intro />
        <Warmup />
        <AdaptiveResolution />
      </Suspense>
      <Controls />
    </Canvas>
  );
}
