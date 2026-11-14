"use client";

import { Suspense, useMemo } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { advanceClock, clock } from "@/lib/sim";
import { Earth } from "./Earth";
import { Sky } from "./Sky";
import { Moon } from "./Moon";
import { Effects } from "./Effects";

function Clock() {
  useFrame(() => advanceClock(), -1);
  return null;
}

/** Start on a three-quarter view of the terminator so day, dusk and night are all in frame. */
function initialCameraPosition() {
  const s = clock.ephemeris.sunDir.clone();
  const dir = s.applyAxisAngle(new THREE.Vector3(0, 1, 0), (-58 * Math.PI) / 180);
  dir.y += 0.28;
  return dir.normalize().multiplyScalar(3.4).toArray();
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
  const camPos = useMemo(() => initialCameraPosition(), []);
  return (
    <Canvas
      dpr={[1, 2]}
      camera={{ position: camPos as [number, number, number], fov: 35, near: 0.002, far: 20000 }}
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
      </Suspense>
      <Controls />
    </Canvas>
  );
}
