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

/** Fill the cells outside the disk from their nearest inside neighbour, so interpolation has no holes. */
function filled(grid: Grid): number[][] {
  const n = grid.length;
  const c = (n - 1) / 2;
  return grid.map((row, i) =>
    row.map((v, j) => {
      if (v !== null) return v;
      // Step toward the centre until inside the disk
      for (let t = 0.1; t <= 1; t += 0.1) {
        const ii = Math.round(i + (c - i) * t);
        const jj = Math.round(j + (c - j) * t);
        const w = grid[ii][jj];
        if (w !== null) return w;
      }
      return 0;
    }),
  );
}

/** Heights as a smooth shaded-relief disk, on a scale shared with its pair. */
function ReliefDisk({ grid, lim, pxM, size, radiusPx }: { grid: Grid; lim: number; pxM: number; size: number; radiusPx: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const z = filled(grid);
    const n = z.length;
    const c = (n - 1) / 2;
    const dpr = window.devicePixelRatio || 1;
    const S = Math.round(size * dpr);
    canvas.width = canvas.height = S;
    const ctx = canvas.getContext("2d")!;
    const img = ctx.createImageData(S, S);
    // Bilinear height at grid coordinates (row, col)
    const h = (r: number, q: number) => {
      const r0 = Math.max(0, Math.min(n - 2, Math.floor(r)));
      const q0 = Math.max(0, Math.min(n - 2, Math.floor(q)));
      const fr = r - r0;
      const fq = q - q0;
      return z[r0][q0] * (1 - fr) * (1 - fq) + z[r0][q0 + 1] * (1 - fr) * fq + z[r0 + 1][q0] * fr * (1 - fq) + z[r0 + 1][q0 + 1] * fr * fq;
    };
    const scale = (radiusPx * 2) / S; // grid px per screen px: the disk fills the canvas
    const e = 0.5; // grid px step for gradients
    const [lx, ly, lz] = [-0.6, 0.6, 0.53]; // toward the light: west, north, up (~32°)
    for (let y = 0; y < S; y++) {
      for (let x = 0; x < S; x++) {
        const dxp = x + 0.5 - S / 2;
        const dyp = y + 0.5 - S / 2;
        const rad = Math.hypot(dxp, dyp);
        const edge = S / 2 - rad; // antialiased rim
        if (edge <= 0) continue;
        const r = c + dyp * scale;
        const q = c + dxp * scale;
        const v = h(r, q);
        // Exaggerate relief 3x for the shading so gentle ground still reads
        const gx = ((h(r, q + e) - h(r, q - e)) / (2 * e * pxM)) * 3;
        const gy = ((h(r + e, q) - h(r - e, q)) / (2 * e * pxM)) * 3;
        const nz = 1 / Math.hypot(gx, gy, 1);
        // Normal (−dz/dE, −dz/dN, 1); rows run south, so dz/dN = −gy
        const lambert = Math.max(0, nz * (-gx * lx + gy * ly + lz));
        const shade = 0.55 + 0.6 * lambert;
        const [cr, cg, cb] = ramp(0.5 + v / (2 * lim));
        const o = (y * S + x) * 4;
        img.data[o] = Math.min(255, cr * shade);
        img.data[o + 1] = Math.min(255, cg * shade);
        img.data[o + 2] = Math.min(255, cb * shade);
        img.data[o + 3] = Math.round(255 * Math.min(1, edge));
      }
    }
    ctx.putImageData(img, 0, 0);
  }, [grid, lim, pxM, size, radiusPx]);
  return <canvas ref={ref} style={{ width: size, height: size }} className="block" aria-hidden />;
}

/** West–east section through the centre of both disks, on its own vertical scale. */
function Section({ target, match, tint, width }: { target: Grid; match: Grid; tint: string; width: number }) {
  const h = 56;
  const mid = Math.floor(target.length / 2);
  const vals = [...target[mid], ...match[mid]].filter((v): v is number => v !== null);
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const pad = Math.max(1, (hi - lo) * 0.12);
  const line = (row: (number | null)[]) => {
    const pts = row.flatMap((v, j) => (v === null ? [] : [[(j / (row.length - 1)) * width, h - ((v - lo + pad) / (hi - lo + 2 * pad)) * h]]));
    return pts.map((p, k) => `${k ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  };
  return (
    <svg viewBox={`0 0 ${width} ${h}`} preserveAspectRatio="none" className="block h-14 w-full overflow-visible" aria-hidden>
      <path d={line(match[mid])} fill="none" stroke="white" strokeWidth={1.5} strokeLinejoin="round" strokeOpacity={0.9} vectorEffect="non-scaling-stroke" />
      <path d={line(target[mid])} fill="none" stroke={tint} strokeWidth={1.5} strokeDasharray="4 3" strokeLinejoin="round" vectorEffect="non-scaling-stroke" style={{ filter: `drop-shadow(0 0 4px ${tint}66)` }} />
    </svg>
  );
}

/** The target's terrain beside this site's, turned to fit: the shape match, shown. */
export function ShapeCompare({ shape, targetName, tint }: { shape: ShapeMatch; targetName: string; tint: string }) {
  // Colour scale from the 98th percentile of |height|, so one spike doesn't wash out the rest
  const abs = [...shape.target.flat(), ...shape.match.flat()].flatMap((v) => (v === null ? [] : [Math.abs(v)])).sort((a, b) => a - b);
  const lim = Math.max(1, abs[Math.floor(abs.length * 0.98)] ?? 1);
  const n = shape.target.length;
  const radiusPx = Math.max(...shape.target.flatMap((row, i) => row.flatMap((v, j) => (v === null ? [] : [Math.hypot(i - (n - 1) / 2, j - (n - 1) / 2) + 0.5]))));
  const size = 150;
  const diskKm = ((radiusPx * 2 * shape.pxM) / 1000).toFixed(1);
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
              <ReliefDisk grid={d.grid} lim={lim} pxM={shape.pxM} size={size} radiusPx={radiusPx} />
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

      <div className="mt-4">
        <Section target={shape.target} match={shape.match} tint={tint} width={312} />
        <div className="mt-1.5 flex items-center justify-between text-[10px] text-white/35">
          <span>W</span>
          <span className="flex items-center gap-3">
            <span className="flex items-center gap-1.5">
              <svg width="12" height="2" aria-hidden>
                <line x1="0" x2="12" y1="1" y2="1" stroke={tint} strokeWidth="2" strokeDasharray="4 3" />
              </svg>
              {targetName}
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-[2px] w-3 rounded-full bg-white" />
              Here
            </span>
            <span className="font-mono">{diskKm} km</span>
          </span>
          <span>E</span>
        </div>
      </div>

      <div className="mt-3 flex items-center gap-2 font-mono text-[9.5px] tabular-nums text-white/35">
        <span>{fmt(-lim)} m</span>
        <span className="h-[5px] flex-1 rounded-full" style={{ background: `linear-gradient(90deg, ${STOPS.map(([t, c]) => `rgb(${c.join(" ")}) ${t * 100}%`).join(", ")})` }} />
        <span>{fmt(lim)} m</span>
      </div>
    </section>
  );
}
