"use client";

import type { Candidate } from "@/lib/candidates";
import { FIELDS, formatField, targetOf, targetValue, type NumKey, type Tab } from "@/lib/profile";
import { research } from "@/lib/research";
import type { AnalogQuery } from "@/lib/search";

const GROUPS: { tab: Tab; label: string; keys: NumKey[] }[] = [
  { tab: "terrain", label: "Terrain", keys: ["slope", "relief", "roughness", "elevation"] },
  { tab: "thermal", label: "Thermal", keys: ["meanTemp", "dayNight", "coldMin"] },
  // Weather is hidden until it has data finer than the 10° grid
];

/** Each measured value as a small gauge on its field's full range, with the target's value marked. */
export function Measurements({ c, q, tint }: { c: Candidate; q: AnalogQuery; tint: string }) {
  const { short } = targetOf(q);
  return (
    <div className="space-y-4">
      {GROUPS.map((g, gi) => {
        const rows = g.keys.map((k) => ({ k, v: FIELDS[k].get(c), t: targetValue(k, c, q) })).filter((r) => Number.isFinite(r.v));
        if (!rows.length) return null;
        return (
          <div key={g.tab}>
            <button
              type="button"
              onClick={() => research.open(g.tab)}
              onPointerEnter={() => research.hover(g.tab)}
              onPointerLeave={() => research.hover(null)}
              className="mb-1.5 text-[10px] font-medium uppercase tracking-[0.12em] text-white/35 transition-colors hover:text-white/70"
              title={`Refine on ${g.label.toLowerCase()}`}
            >
              {g.label}
            </button>
            <div className="grid grid-cols-2 gap-x-4 gap-y-2.5">
              {rows.map(({ k, v, t }, i) => {
                const f = FIELDS[k];
                const p = (x: number) => Math.min(1, Math.max(0, (x - f.min) / (f.max - f.min)));
                return (
                  <div key={k} className="min-w-0" style={{ animation: `rise-in .5s var(--ease-out-expo) ${0.03 * (gi * 4 + i)}s both` }}>
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="truncate text-[11px] text-white/45">{f.label}</span>
                      <span className="shrink-0 text-[12.5px] font-medium tabular-nums text-white">{formatField(k, v)}</span>
                    </div>
                    <div className="relative mt-1.5 h-[4px] rounded-full bg-white/[0.07]" aria-hidden>
                      <span
                        className="absolute inset-y-0 left-0 rounded-full bg-white/60"
                        style={{ width: `${p(v) * 100}%`, transformOrigin: "0 50%", animation: `bar-in .9s var(--ease-out-expo) ${0.15 + 0.03 * i}s both` }}
                      />
                      {t !== undefined && (
                        <span
                          title={`${short}: ${formatField(k, t)}`}
                          className="absolute -top-[3px] h-[10px] w-[2px] -translate-x-1/2 rounded-full"
                          style={{ left: `${p(t) * 100}%`, background: tint, boxShadow: `0 0 6px ${tint}` }}
                        />
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
      <p className="flex items-center gap-1.5 text-[10px] text-white/30">
        <span className="h-[10px] w-[2px] rounded-full" style={{ background: tint }} />
        {short}&apos;s value, where known
      </p>
    </div>
  );
}
