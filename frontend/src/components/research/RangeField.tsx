"use client";

import { useRef, useState } from "react";
import { FIELDS, formatField, type NumKey } from "@/lib/profile";

export interface Dot {
  id: string;
  name: string;
  v: number;
  pass: boolean;
  current: boolean;
}

/**
 * Two-thumb limit slider over a strip plot of the candidate pool: every site is a dot at
 * its value (bright if it passes the draft limits), the site on screen is ringed, and the
 * target's own value is a tinted tick, so the researcher sees the trade before applying it.
 */
export function RangeField({
  k,
  value,
  onChange,
  dots,
  target,
  tint,
}: {
  k: NumKey;
  value?: [number, number];
  onChange: (r: [number, number] | null) => void;
  dots: Dot[];
  target?: number;
  tint: string;
}) {
  const f = FIELDS[k];
  const track = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<0 | 1 | null>(null);
  const r: [number, number] = value ?? [f.min, f.max];

  const sc = (v: number) => (f.scale === "sqrt" ? Math.sqrt(Math.max(0, v - f.min)) : v - f.min);
  const span = sc(f.max);
  const pos = (v: number) => Math.min(1, Math.max(0, sc(v) / span));
  const valueAt = (p: number) => {
    const u = Math.min(1, Math.max(0, p)) * span;
    const v = f.min + (f.scale === "sqrt" ? u * u : u);
    return Math.min(f.max, Math.max(f.min, Math.round(v / f.step) * f.step));
  };

  const commit = (next: [number, number]) => {
    const lo = Math.min(next[0], next[1]);
    const hi = Math.max(next[0], next[1]);
    onChange(lo <= f.min && hi >= f.max ? null : [+lo.toFixed(f.digits), +hi.toFixed(f.digits)]);
  };
  const pointAt = (clientX: number) => {
    const b = track.current!.getBoundingClientRect();
    return valueAt((clientX - b.left) / b.width);
  };

  const onDown = (e: React.PointerEvent) => {
    const v = pointAt(e.clientX);
    const thumb = Math.abs(pos(v) - pos(r[0])) < Math.abs(pos(v) - pos(r[1])) || (r[0] === r[1] && v < r[0]) ? 0 : 1;
    setDrag(thumb);
    e.currentTarget.setPointerCapture(e.pointerId);
    commit(thumb === 0 ? [v, r[1]] : [r[0], v]);
  };
  const onMove = (e: React.PointerEvent) => {
    if (drag === null) return;
    if (!(e.buttons & 1)) return setDrag(null);
    const v = pointAt(e.clientX);
    // Thumbs swap roles when dragged past each other.
    if (drag === 0 && v > r[1]) setDrag(1);
    if (drag === 1 && v < r[0]) setDrag(0);
    commit(drag === 0 ? [v, r[1]] : [r[0], v]);
  };

  const onKey = (thumb: 0 | 1) => (e: React.KeyboardEvent) => {
    const step = f.step * (e.shiftKey ? 10 : 1);
    const d = { ArrowLeft: -step, ArrowDown: -step, ArrowRight: step, ArrowUp: step }[e.key];
    let v: number | undefined = d === undefined ? undefined : r[thumb] + d;
    if (e.key === "Home") v = f.min;
    if (e.key === "End") v = f.max;
    if (v === undefined) return;
    e.preventDefault();
    v = Math.min(f.max, Math.max(f.min, v));
    commit(thumb === 0 ? [Math.min(v, r[1]), r[1]] : [r[0], Math.max(v, r[0])]);
  };

  // Stack dots that would overlap into up to three rows.
  const placed = [...dots]
    .sort((a, b) => a.v - b.v)
    .reduce<(Dot & { x: number; row: number })[]>((acc, d) => {
      const x = pos(d.v);
      let row = 0;
      while (row < 2 && acc.some((o) => o.row === row && Math.abs(o.x - x) < 0.035)) row++;
      acc.push({ ...d, x, row });
      return acc;
    }, []);

  const offScale = target !== undefined && (target < f.min || target > f.max);
  const readout = !value ? "Any" : r[0] <= f.min ? `≤ ${formatField(k, r[1])}` : r[1] >= f.max ? `≥ ${formatField(k, r[0])}` : `${formatField(k, r[0])} – ${formatField(k, r[1])}`;

  return (
    <div className="group/field">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-[12.5px] text-white/70">{f.label}</p>
        <div className="flex items-center gap-1.5">
          <span key={readout} className={`font-mono text-[11.5px] tabular-nums ${value ? "text-white" : "text-white/35"}`}>
            {readout}
          </span>
          {value && (
            <button
              type="button"
              onClick={() => onChange(null)}
              aria-label={`Clear ${f.label.toLowerCase()} limit`}
              className="-mr-1 grid h-5 w-5 place-items-center rounded-full text-white/40 transition-colors hover:bg-white/10 hover:text-white focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/40"
            >
              <svg width="8" height="8" viewBox="0 0 8 8" aria-hidden>
                <path d="M1.5 1.5l5 5M6.5 1.5l-5 5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
              </svg>
            </button>
          )}
        </div>
      </div>

      <div
        ref={track}
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={() => setDrag(null)}
        onPointerCancel={() => setDrag(null)}
        onLostPointerCapture={() => setDrag(null)}
        className="relative mt-1.5 h-[46px] cursor-pointer touch-none select-none"
      >
        {/* Selected band behind the dots */}
        <div
          aria-hidden
          className="absolute bottom-[7px] top-1 rounded-md bg-white/[0.035] transition-opacity"
          style={{ left: `${pos(r[0]) * 100}%`, right: `${(1 - pos(r[1])) * 100}%`, opacity: value ? 1 : 0 }}
        />

        {/* Target value */}
        {target !== undefined && (
          <div aria-hidden className="absolute bottom-[7px] top-0" style={{ left: `${pos(target) * 100}%` }}>
            <span className="absolute bottom-0 top-3 w-px -translate-x-1/2" style={{ background: `linear-gradient(to top, ${tint}, transparent)` }} />
            <span
              className={`absolute top-0 whitespace-nowrap text-[9.5px] font-medium tracking-[0.04em] ${pos(target) > 0.8 ? "right-1" : pos(target) < 0.2 ? "left-1" : "-translate-x-1/2"}`}
              style={{ color: tint }}
            >
              {offScale ? (target! < f.min ? `◂ Target ${formatField(k, target!)}` : `Target ${formatField(k, target!)} ▸`) : "Target"}
            </span>
          </div>
        )}

        {/* Candidate pool */}
        {placed.map((d) => (
          <span
            key={d.id}
            title={`${d.name} · ${formatField(k, d.v)}`}
            className="absolute rounded-full"
            style={{
              left: `${d.x * 100}%`,
              bottom: 13 + d.row * 8,
              width: d.current ? 9 : 6,
              height: d.current ? 9 : 6,
              transform: "translate(-50%, 50%)",
              background: d.current ? "transparent" : d.pass ? "rgb(255 255 255 / 0.85)" : "rgb(255 255 255 / 0.16)",
              boxShadow: d.current ? `0 0 0 1.5px ${d.pass ? "#fff" : "rgb(255 255 255 / 0.4)"}, 0 0 10px rgb(255 255 255 / 0.35)` : undefined,
              transition: "background-color .25s ease, box-shadow .25s ease",
            }}
          />
        ))}

        {/* Track and thumbs */}
        <div aria-hidden className="absolute inset-x-0 bottom-[6px] h-[2px] rounded-full bg-white/10" />
        <div
          aria-hidden
          className="absolute bottom-[6px] h-[2px] rounded-full transition-colors"
          style={{ left: `${pos(r[0]) * 100}%`, right: `${(1 - pos(r[1])) * 100}%`, background: value ? "rgb(255 255 255 / 0.75)" : "rgb(255 255 255 / 0.18)" }}
        />
        {([0, 1] as const).map((t) => (
          <span
            key={t}
            role="slider"
            tabIndex={0}
            aria-label={`${f.label} ${t === 0 ? "minimum" : "maximum"}`}
            aria-valuemin={f.min}
            aria-valuemax={f.max}
            aria-valuenow={r[t]}
            aria-valuetext={formatField(k, r[t])}
            onKeyDown={onKey(t)}
            className="absolute bottom-[7px] h-3.5 w-3.5 rounded-full bg-white shadow-[0_1px_4px_rgb(0_0_0/0.5)] outline-none transition-[transform,opacity] duration-200 focus-visible:ring-2 focus-visible:ring-white/50 focus-visible:ring-offset-2 focus-visible:ring-offset-black"
            style={{
              left: `${pos(r[t]) * 100}%`,
              transform: `translate(-50%, 50%) scale(${drag === t ? 1.2 : value ? 1 : 0.72})`,
              opacity: value || drag !== null ? 1 : 0.55,
            }}
          />
        ))}
      </div>

      <div aria-hidden className="mt-0.5 flex justify-between font-mono text-[9.5px] text-white/20">
        <span>{formatField(k, f.min)}</span>
        <span>{formatField(k, f.max)}</span>
      </div>
    </div>
  );
}
