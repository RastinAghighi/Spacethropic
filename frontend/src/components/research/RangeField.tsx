"use client";

import { useRef, useState } from "react";
import { FIELDS, formatField, type NumKey } from "@/lib/profile";

const INSET = 7; // thumb radius: thumbs never leave the track

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
  // Thumbs sit inside the track: positions map onto [INSET, width - INSET]
  const pointAt = (clientX: number) => {
    const b = track.current!.getBoundingClientRect();
    return valueAt((clientX - b.left - INSET) / (b.width - 2 * INSET));
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

  const offScale = target !== undefined && (target < f.min || target > f.max);
  const readout = !value ? "Any" : r[0] <= f.min ? `≤ ${formatField(k, r[1])}` : r[1] >= f.max ? `≥ ${formatField(k, r[0])}` : `${formatField(k, r[0])} – ${formatField(k, r[1])}`;
  const x = (v: number) => `calc(${INSET}px + ${pos(v)} * (100% - ${2 * INSET}px))`;

  return (
    <div className="group/field">
      <div className="flex h-5 items-center justify-between gap-3">
        <p className="truncate text-[12.5px] text-white/75">{f.label}</p>
        <div className="flex shrink-0 items-center gap-1.5">
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
        className="relative mt-2 h-8 cursor-pointer touch-none select-none"
      >
        {/* Candidates as a rug of ticks: bright if they pass the draft limits, the site on screen tallest */}
        {dots.map((d) => (
          <span
            key={d.id}
            title={`${d.name} · ${formatField(k, d.v)}`}
            className="absolute bottom-[13px] w-[2px] -translate-x-1/2 rounded-full transition-[background-color,height] duration-300"
            style={{
              left: x(d.v),
              height: d.current ? 14 : 9,
              background: d.current ? "#fff" : d.pass ? "rgb(255 255 255 / 0.6)" : "rgb(255 255 255 / 0.15)",
              boxShadow: d.current ? "0 0 8px rgb(255 255 255 / 0.5)" : undefined,
            }}
          />
        ))}

        {/* Track, selection and target */}
        <div aria-hidden className="absolute bottom-[7px] h-[2px] rounded-full bg-white/10" style={{ left: INSET, right: INSET }} />
        <div
          aria-hidden
          className="absolute bottom-[7px] h-[2px] rounded-full transition-colors"
          style={{ left: x(r[0]), width: `calc(${pos(r[1]) - pos(r[0])} * (100% - ${2 * INSET}px))`, background: value ? "rgb(255 255 255 / 0.8)" : "rgb(255 255 255 / 0.2)" }}
        />
        {target !== undefined && (
          <span aria-hidden className="absolute bottom-0 -translate-x-1/2" style={{ left: x(Math.min(f.max, Math.max(f.min, target))) }}>
            <svg width="8" height="5" viewBox="0 0 8 5" className="block">
              <path d="M4 0L8 5H0z" fill={tint} />
            </svg>
          </span>
        )}
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
            className="absolute bottom-[8px] h-3.5 w-3.5 rounded-full bg-white shadow-[0_1px_4px_rgb(0_0_0/0.5)] outline-none transition-[transform,opacity] duration-200 focus-visible:ring-2 focus-visible:ring-white/50"
            style={{
              left: x(r[t]),
              transform: `translate(-50%, 50%) scale(${drag === t ? 1.2 : value ? 1 : 0.72})`,
              opacity: value || drag !== null ? 1 : 0.55,
            }}
          />
        ))}
      </div>

      <div aria-hidden className="mt-1 flex items-center justify-between font-mono text-[9.5px] tabular-nums text-white/25" style={{ paddingInline: INSET - 3 }}>
        <span>{formatField(k, f.min)}</span>
        {target !== undefined && (
          <span style={{ color: tint }}>
            {offScale ? (target < f.min ? "◂ " : "") : ""}target {formatField(k, target)}
            {offScale && target > f.max ? " ▸" : ""}
          </span>
        )}
        <span>{formatField(k, f.max)}</span>
      </div>
    </div>
  );
}
