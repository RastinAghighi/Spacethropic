"use client";

import { useMemo, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { useTexture } from "@react-three/drei";
import * as THREE from "three";
import { clock } from "@/lib/sim";
import { VERT } from "./shaders/common";
import { atmosphereFrag, cloudFrag, earthFrag } from "./shaders/earth";

export const SUN_E = 9.5;
const CLOUD_RADIUS = 1.0045;
const LIGHTS_GAIN = 0.9;

const TEX = {
  day: "/textures/earth_day_8k.jpg",
  lights: "/textures/earth_lights_8k.jpg",
  elev: "/textures/earth_elev_8k.jpg",
  water: "/textures/earth_water_4k.png",
  clouds: "/textures/earth_clouds_2k.jpg",
};

const tmpQ = new THREE.Quaternion();

// Uniform writes go through a helper: the React Compiler lint treats memoised
// objects as immutable, but per-frame uniform updates are the normal R3F pattern.
function setU(m: THREE.ShaderMaterial, name: string, v: number) {
  m.uniforms[name].value = v;
}

export function Earth() {
  const gl = useThree((s) => s.gl);
  const tex = useTexture(TEX, (loaded) => {
    // drei hands the onLoad callback an array in TEX's key order, not the keyed object.
    const keys = Object.keys(TEX) as (keyof typeof TEX)[];
    const aniso = gl.capabilities.getMaxAnisotropy();
    (loaded as unknown as THREE.Texture[]).forEach((x, i) => {
      // The day map is deliberately sampled without sRGB decoding: the shading and grade
      // were tuned on its lighter, softer response, and that is the intended look.
      x.colorSpace = THREE.NoColorSpace;
      // Data maps are single-channel: store as R8 rather than RGBA8 (¼ the VRAM, same values).
      if (keys[i] !== "day") x.format = THREE.RedFormat;
      x.wrapS = THREE.RepeatWrapping;
      x.anisotropy = aniso;
      x.needsUpdate = true;
    });
  });

  const surface = useRef<THREE.Mesh>(null!);
  const clouds = useRef<THREE.Mesh>(null!);
  const geo = useMemo(() => new THREE.SphereGeometry(1, 384, 192), []);

  const mats = useMemo(() => {
    const earth = new THREE.ShaderMaterial({
      vertexShader: VERT,
      fragmentShader: earthFrag,
      uniforms: {
        uDay: { value: tex.day },
        uLights: { value: tex.lights },
        uElev: { value: tex.elev },
        uWater: { value: tex.water },
        uClouds: { value: tex.clouds },
        uSun: { value: new THREE.Vector3() },
        uCam: { value: new THREE.Vector3() },
        uSunE: { value: SUN_E },
        uCloudDrift: { value: 0 },
        uTexel: { value: new THREE.Vector2(1 / 8192, 1 / 4096) },
        uRelief: { value: 0.055 },
        uLightsGain: { value: LIGHTS_GAIN },
      },
    });
    const cloud = new THREE.ShaderMaterial({
      vertexShader: VERT,
      fragmentShader: cloudFrag,
      transparent: true,
      depthWrite: false,
      uniforms: {
        uClouds: { value: tex.clouds },
        uLights: { value: tex.lights },
        uSun: { value: new THREE.Vector3() },
        uCam: { value: new THREE.Vector3() },
        uSunE: { value: SUN_E },
        uTime: { value: 0 },
        uCloudDrift: { value: 0 },
        uLightsGain: { value: LIGHTS_GAIN },
      },
    });
    const atmosphere = new THREE.ShaderMaterial({
      vertexShader: VERT,
      fragmentShader: atmosphereFrag,
      transparent: true,
      depthWrite: false,
      blending: THREE.CustomBlending,
      blendEquation: THREE.AddEquation,
      blendSrc: THREE.OneFactor,
      blendDst: THREE.OneMinusSrcAlphaFactor,
      uniforms: {
        uSunW: { value: new THREE.Vector3() },
        uCamW: { value: new THREE.Vector3() },
        uSunE: { value: SUN_E },
        uFrame: { value: 0 },
      },
    });
    return { earth, cloud, atmosphere };
  }, [tex]);

  useFrame(({ camera, clock: rclock }) => {
    const eph = clock.ephemeris;
    const t = rclock.elapsedTime;
    const drift = t * 0.0035;

    surface.current.rotation.y = eph.earthRotation;
    clouds.current.rotation.y = eph.earthRotation + drift;

    // Sun & camera into each body frame
    tmpQ.copy(surface.current.quaternion).invert();
    const eu = mats.earth.uniforms;
    eu.uSun.value.copy(eph.sunDir).applyQuaternion(tmpQ);
    eu.uCam.value.copy(camera.position).applyQuaternion(tmpQ);
    setU(mats.earth, "uCloudDrift", drift);

    tmpQ.copy(clouds.current.quaternion).invert();
    const cu = mats.cloud.uniforms;
    cu.uSun.value.copy(eph.sunDir).applyQuaternion(tmpQ);
    cu.uCam.value.copy(camera.position).applyQuaternion(tmpQ);
    setU(mats.cloud, "uTime", t);
    setU(mats.cloud, "uCloudDrift", drift);

    const au = mats.atmosphere.uniforms;
    au.uSunW.value.copy(eph.sunDir);
    au.uCamW.value.copy(camera.position);
    setU(mats.atmosphere, "uFrame", au.uFrame.value + 1);

    // Keep the camera outside the cloud deck regardless of controls.
    if (camera.position.length() < 1.03) camera.position.setLength(1.03);
  });

  return (
    <group>
      <mesh ref={surface} geometry={geo} material={mats.earth} renderOrder={2} />
      <mesh ref={clouds} geometry={geo} material={mats.cloud} scale={CLOUD_RADIUS} renderOrder={3} />
      <mesh material={mats.atmosphere} renderOrder={4}>
        <sphereGeometry args={[1.025, 192, 96]} />
      </mesh>
    </group>
  );
}
