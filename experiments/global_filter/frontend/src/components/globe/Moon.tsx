"use client";

import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { useTexture } from "@react-three/drei";
import * as THREE from "three";
import { clock } from "@/lib/sim";
import { MOON_RADIUS } from "@/lib/astro";
import { VERT } from "./shaders/common";
import { moonFrag } from "./shaders/earth";
import { SUN_E } from "./Earth";

const qInv = new THREE.Quaternion();
const basis = new THREE.Matrix4();
const ex = new THREE.Vector3();
const ey = new THREE.Vector3();
const ez = new THREE.Vector3();

export function Moon() {
  const ref = useRef<THREE.Mesh>(null!);
  const [color, elev] = useTexture(["/textures/moon_4k.jpg", "/textures/moon_elev_1k.jpg"], (ts) => {
    const [c, e] = ts as THREE.Texture[];
    c.colorSpace = THREE.SRGBColorSpace;
    e.format = THREE.RedFormat;
    for (const t of [c, e]) {
      t.wrapS = THREE.RepeatWrapping;
      t.anisotropy = 8;
    }
  });

  const mat = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: VERT,
        fragmentShader: moonFrag,
        uniforms: {
          uColor: { value: color },
          uElev: { value: elev },
          uSun: { value: new THREE.Vector3() },
          uCam: { value: new THREE.Vector3() },
          uEarth: { value: new THREE.Vector3() },
          uSunE: { value: SUN_E },
          uTexel: { value: new THREE.Vector2(1 / 1024, 1 / 512) },
        },
      }),
    [color, elev],
  );

  useFrame(({ camera }) => {
    const m = ref.current;
    const eph = clock.ephemeris;
    m.position.copy(eph.moonPos);
    // Tidally locked: lunar longitude 0 (texture centre) faces Earth.
    ex.copy(eph.moonPos).negate().normalize();
    ey.set(0, 1, 0).addScaledVector(ex, -ex.y).normalize();
    ez.crossVectors(ex, ey);
    basis.makeBasis(ex, ey, ez);
    m.quaternion.setFromRotationMatrix(basis);

    qInv.copy(m.quaternion).invert();
    const u = mat.uniforms;
    u.uSun.value.copy(eph.sunDir).applyQuaternion(qInv);
    u.uCam.value.copy(camera.position).sub(m.position).divideScalar(MOON_RADIUS).applyQuaternion(qInv);
    u.uEarth.value.copy(ex).applyQuaternion(qInv);
  });

  return (
    <mesh ref={ref} material={mat} scale={MOON_RADIUS} renderOrder={1}>
      <sphereGeometry args={[1, 128, 64]} />
    </mesh>
  );
}
