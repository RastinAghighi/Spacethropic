"use client";

import { useState, type CSSProperties } from "react";
import { useUi } from "@/lib/ui";

const BG = "#050608";
const GREY = "#62666e";
const PLANET = 38;
const MOON = 11;
/** Orbit ellipse: long axis on the diagonal, short axis is the foreshortened depth. */
const ORBIT_A = 44;
const ORBIT_B = 11;
const PERIOD = 2.6;
/** Open just before the moon swings round in front (orbit phase, 0..1). */
const START_PHASE = 0.88;

const SINE = "cubic-bezier(0.37, 0, 0.63, 1)";
const delay = (phase: number) => `${(-phase * PERIOD).toFixed(3)}s`;
const anim = (name: string, phase: number, timing = SINE) =>
  `${name} ${PERIOD}s ${timing} ${delay(phase)} infinite`;

/**
 * One copy of the moon's orbit. Two are drawn — one under the planet, one over it —
 * and they swap via opacity, so the moon passes behind and in front with no z-index
 * changes. Everything is transform/opacity, which the compositor animates even while
 * the main thread is blocked uploading textures and compiling shaders.
 */
function MoonOrbit({ near }: { near: boolean }) {
  const x = START_PHASE;
  const y = START_PHASE + 0.75; // depth lags the diagonal by a quarter turn
  return (
    <div className="absolute left-1/2 top-1/2" style={{ transform: "rotate(45deg)" }}>
      <div style={{ animation: anim("loader-x", x) }}>
        <div style={{ animation: anim("loader-y", y) }}>
          <div
            className="rounded-full"
            style={{
              width: MOON,
              height: MOON,
              margin: -MOON / 2,
              background: GREY,
              // Hairline of background colour separates the moon as it crosses the planet.
              boxShadow: near ? `0 0 0 2px ${BG}` : undefined,
              animation: `${anim("loader-depth", y)}, ${anim(near ? "loader-near" : "loader-far", x, "steps(1, end)")}`,
            }}
          />
        </div>
      </div>
    </div>
  );
}

/** Near-black curtain with a grey moon orbiting a grey planet, up until the scene is fully ready. */
export function Loader() {
  const { ready } = useUi();
  const [gone, setGone] = useState(false);
  if (gone) return null;

  return (
    <div
      aria-hidden={ready}
      role="status"
      aria-label="Loading Earth"
      onTransitionEnd={(e) => e.target === e.currentTarget && ready && setGone(true)}
      className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-6 transition-opacity duration-[1400ms] ease-[var(--ease-out-expo)]"
      style={{ background: BG, opacity: ready ? 0 : 1, pointerEvents: ready ? "none" : "auto" }}
    >
      <div
        className="relative h-[140px] w-[140px]"
        style={{ "--orbit-a": `${ORBIT_A}px`, "--orbit-b": `${ORBIT_B}px` } as CSSProperties}
      >
        <MoonOrbit near={false} />
        <div
          className="absolute left-1/2 top-1/2 rounded-full"
          style={{ width: PLANET, height: PLANET, margin: -PLANET / 2, background: GREY }}
        />
        <MoonOrbit near />
      </div>
      <p className="font-mono text-[10.5px] uppercase tracking-[0.32em] text-white/30">Preparing Earth</p>
    </div>
  );
}
