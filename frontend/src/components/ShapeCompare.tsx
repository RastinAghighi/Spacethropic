"use client";

import { useEffect, useRef } from "react";
import type { ShapeMatch } from "@/lib/candidates";

type Grid = (number | null)[][];

// Elevation ramp for a dark UI: deep low ground through sage to pale high ground.
const STOPS: [number, [number, number, number]][] = [
  [0, [16, 42, 61]],
  [0.25, [31, 92, 102]],
  [0.5, [111, 143, 106]],
  [0.75, [200, 169, 106]],
  [1, [244, 237, 224]],
];

function ramp(t: number): [number, number, number] {
  const x = Math.min(1, Math.max(0, t));
  for (let i = 1; i < STOPS.length; i++) {
    const [b, cb] = STOPS[i];
    const [a, ca] = STOPS[i - 1];
    if (x <= b) {
      const f = (x - a) / (b - a);
      return [0, 1, 2].map((k) => ca[k] + (cb[k] - ca[k]) * f) as [number, number, number];
    }
  }
  return STOPS[STOPS.length - 1][1];
}

/** Heights as a pixel-true shaded relief disk (one square per 200 m sample), on a scale shared with its pair. */
function ReliefDisk({ grid, lim, pxM, size }: { grid: Grid; lim: number; pxM: number; size: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const n = grid.length;
    canvas.width = canvas.height = n;
    const ctx = canvas.getContext("2d")!;
    const img = ctx.createImageData(n, n);
    const at = (i: number, j: number, v: number) => grid[i]?.[j] ?? v;
    const [lx, ly, lz] = [-0.6, 0.6, 0.53]; // toward the light: west, north, up (~32°)
    for (let i = 0; i < n; i++) {
      for (let j = 0; j < n; j++) {
        const v = grid[i][j];
        if (v === null) continue;
        // Relief exaggerated 3x for the shading so gentle ground still reads; rows run south
        const gx = ((at(i, j + 1, v) - at(i, j - 1, v)) / (2 * pxM)) * 3;
        const gy = ((at(i + 1, j, v) - at(i - 1, j, v)) / (2 * pxM)) * 3;
        const nz = 1 / Math.hypot(gx, gy, 1);
        const shade = 0.55 + 0.6 * Math.max(0, nz * (-gx * lx + gy * ly + lz));
        const [r, g, b] = ramp(0.5 + v / (2 * lim));
        const o = (i * n + j) * 4;
        img.data[o] = Math.min(255, r * shade);
        img.data[o + 1] = Math.min(255, g * shade);
        img.data[o + 2] = Math.min(255, b * shade);
        img.data[o + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
  }, [grid, lim, pxM]);
  return <canvas ref={ref} style={{ width: size, height: size, imageRendering: "pixelated" }} className="block" aria-hidden />;
}

/** The target's terrain beside this site's, turned to fit: the shape match, shown. */
export function ShapeCompare({ shape, targetName, tint }: { shape: ShapeMatch; targetName: string; tint: string }) {
  // Colour scale from the 98th percentile of |height|, so one spike doesn't wash out the rest
  const abs = [...shape.target.flat(), ...shape.match.flat()].flatMap((v) => (v === null ? [] : [Math.abs(v)])).sort((a, b) => a - b);
  const lim = Math.max(1, abs[Math.floor(abs.length * 0.98)] ?? 1);
  const size = 150;
  const fmt = (v: number) => `${v >= 0 ? "+" : "−"}${Math.abs(v) < 10 ? Math.abs(v).toFixed(1) : Math.round(Math.abs(v))}`;
  return (
    <section style={{ animation: "rise-in .6s var(--ease-out-expo) .08s both" }}>
      <div className="mb-3 flex items-baseline justify-between">
        <p className="text-[10px] font-medium uppercase tracking-[0.12em] text-white/35">Terrain shape</p>
        <p className="font-mono text-[11px] tabular-nums text-white/55" title="RMS height difference over the disk, after turning the target to fit">
          ±{shape.rmseM.toFixed(1)} m
        </p>
      </div>
      <div className="flex items-start justify-between">
        {[
          { grid: shape.target, label: targetName, note: shape.rotationDeg ? `turned ${shape.rotationDeg}°` : "as found", ring: tint },
          { grid: shape.match, label: "Here", note: `relief ${Math.round(shape.reliefM)} m`, ring: "rgb(255 255 255 / 0.5)" },
        ].map((d, k) => (
          <figure key={k} className="flex flex-col items-center" style={{ animation: `rise-in .7s var(--ease-out-expo) ${0.12 + k * 0.08}s both` }}>
            <div className="relative rounded-full p-[3px]" style={{ boxShadow: `inset 0 0 0 1px ${d.ring}` }}>
              <ReliefDisk grid={d.grid} lim={lim} pxM={shape.pxM} size={size} />
              {k === 0 && (
                <svg width="14" height="14" viewBox="0 0 14 14" className="absolute left-1/2 top-1 -translate-x-1/2 text-white/60" style={{ transform: `translateX(-50%) rotate(${-shape.rotationDeg}deg)` }} aria-hidden>
                  <path d="M7 2l3 7H4z" fill="currentColor" />
                </svg>
              )}
            </div>
            <figcaption className="mt-2 text-center">
              <span className="block max-w-[150px] truncate text-[12px] text-white/85">{d.label}</span>
              <span className="block text-[10.5px] text-white/35">{d.note}</span>
            </figcaption>
          </figure>
        ))}
      </div>

      <div className="mt-4 flex items-center gap-2 font-mono text-[9.5px] tabular-nums text-white/35">
        <span>{fmt(-lim)} m</span>
        <span className="h-[5px] flex-1 rounded-full" style={{ background: `linear-gradient(90deg, ${STOPS.map(([t, c]) => `rgb(${c.join(" ")}) ${t * 100}%`).join(", ")})` }} />
        <span>{fmt(lim)} m</span>
      </div>
    </section>
  );
}
