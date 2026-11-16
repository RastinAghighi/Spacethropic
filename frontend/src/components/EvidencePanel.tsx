"use client";

import { useEffect, useState } from "react";
import { DIVE, useUi } from "@/lib/ui";
import { formatCoord, type Candidate } from "@/lib/candidates";
import { BODY } from "@/lib/catalog";
import { FIELDS, matchProfile, overallScore, targetOf, type NumKey } from "@/lib/profile";
import { analyse, type Analysis, type AnalogQuery, type Point, type Source } from "@/lib/search";
import { Label } from "./search/primitives";
import { ShapeCompare } from "./ShapeCompare";
import { Measurements } from "./Measurements";

const pct = (v: number) => Math.round(v * 100);

function Ticker({ value, className }: { value: number; className?: string }) {
  return (
    <span
      className={`ticker tabular-nums ${className ?? ""}`}
      style={{ ["--num" as string]: value, animation: "count-up 1.1s var(--ease-out-expo) .15s both" }}
      aria-label={String(value)}
    />
  );
}

function ScoreRing({ score, delta, tint }: { score: number; delta: number | null; tint: string }) {
  const r = 24;
  const circ = 2 * Math.PI * r;
  return (
    <div className="flex shrink-0 items-center gap-2" title="Overall match">
      <Delta value={delta} />
      <div className="relative grid h-14 w-14 place-items-center">
        <svg width="56" height="56" viewBox="0 0 56 56" className="absolute inset-0 -rotate-90" aria-hidden>
          <circle cx="28" cy="28" r={r} fill="none" stroke="rgb(255 255 255 / 0.07)" strokeWidth="2.5" />
          <circle
            cx="28"
            cy="28"
            r={r}
            fill="none"
            stroke={tint}
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeDasharray={circ}
            strokeDashoffset={circ * (1 - score)}
            style={{ ["--circ" as string]: `${circ}`, animation: "ring-in 1.1s var(--ease-out-expo) .15s both", filter: `drop-shadow(0 0 5px ${tint}55)` }}
          />
        </svg>
        <span className="text-[16px] font-medium tracking-[-0.03em] text-white">
          <Ticker value={pct(score)} />
          <span className="text-[10px] text-white/40">%</span>
        </span>
      </div>
    </div>
  );
}

/**
 * What the last refine gained. Only gains are called out: a refine trades breadth for the
 * property asked for, and the numbers themselves already show the rest.
 */
function Delta({ value, className }: { value: number | null; className?: string }) {
  if (value === null || value < 5) return null;
  return (
    <p
      className={`font-mono text-[10px] tabular-nums text-[#8fe3b0] ${className ?? ""}`}
      style={{ animation: "rise-in .6s var(--ease-out-expo) .9s both" }}
      title="Gained since the previous step"
    >
      +{value}
    </p>
  );
}

/** Plain-language gaps between a site and the target's measured values (search service results). */
function measuredGaps(c: Candidate, t: Record<string, number>, short: string): string[] {
  const v = (k: NumKey) => FIELDS[k].get(c);
  const out: string[] = [];
  const cap = short[0].toUpperCase() + short.slice(1);
  if (t.slope !== undefined && Math.abs(v("slope") - t.slope) >= 2)
    out.push(`${v("slope") > t.slope ? "Steeper" : "Gentler"} than ${short}: ${v("slope").toFixed(1)}° slopes against ${t.slope.toFixed(1)}°.`);
  if (t.meanTemp !== undefined) {
    const d = Math.round(v("meanTemp") - t.meanTemp);
    if (Math.abs(d) >= 5) out.push(`${Math.abs(d)} °C ${d > 0 ? "warmer" : "colder"} on average than ${short}'s surface. Pair field work with a thermal-vacuum test.`);
  }
  if (t.dayNight !== undefined && Math.abs(v("dayNight") - t.dayNight) >= 10)
    out.push(`${cap} swings ${Math.round(t.dayNight)} °C between day and night; here it's ${Math.round(v("dayNight"))} °C.`);
  if (t.dust !== undefined && Number.isFinite(v("dust")) && t.dust > 2 * v("dust"))
    out.push(`Dustier sky on ${short}: optical depth ${t.dust.toFixed(2)} against ${v("dust").toFixed(2)} here.`);
  return out;
}

/** The model's reading of this site against the target: pending, done, or failed (fall back to the measured text). */
function useAnalysis(c: Candidate, q: AnalogQuery, live: boolean): Analysis | "pending" | null {
  const [state, setState] = useState<{ id: string; a: Analysis | "pending" | null }>({ id: "", a: null });
  useEffect(() => {
    if (!live) return;
    let on = true;
    analyse(c, q.target).then(
      (a) => on && setState({ id: c.id, a }),
      () => on && setState({ id: c.id, a: null }),
    );
    return () => {
      on = false;
    };
  }, [c, q.target, live]);
  return live && state.id === c.id ? state.a : live ? "pending" : null;
}

function Bullets({ items, dot, tone }: { items: (string | Point)[]; dot: string; tone: string }) {
  return (
    <ul className="space-y-2.5">
      {items.map((w, i) => (
        <li key={typeof w === "string" ? w : w.point} className="flex gap-2.5 leading-snug" style={{ animation: `rise-in .5s var(--ease-out-expo) ${0.05 * i}s both` }}>
          <span className="mt-[6px] h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: dot }} aria-hidden />
          {typeof w === "string" ? (
            <span className={tone}>{w}</span>
          ) : (
            <span className="min-w-0">
              <span className="block text-[13px] text-white/90">{w.point}</span>
              <span className="mt-0.5 block text-[11.5px] tabular-nums text-white/45">{w.evidence}</span>
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

function Thinking() {
  return (
    <div className="space-y-4" aria-label="Analysing the measurements">
      <p className="flex items-center gap-2 text-[11px] text-white/40">
        <span className="h-3 w-3 rounded-full border-[1.5px] border-white/15 border-t-white/60" style={{ animation: "orbit .8s linear infinite" }} aria-hidden />
        Weighing the measurements against the target
      </p>
      {[0, 1].map((g) => (
        <div key={g} className="space-y-2">
          <div className="h-2 w-24 animate-pulse rounded-full bg-white/[0.07]" />
          {[92, 78, 85].map((w, i) => (
            <div key={i} className="h-2.5 animate-pulse rounded-full bg-white/[0.05]" style={{ width: `${w - g * 6}%`, animationDelay: `${0.1 * (g * 3 + i)}s` }} />
          ))}
        </div>
      ))}
    </div>
  );
}

function Body({
  c,
  index,
  total,
  q,
  source,
  prev,
}: {
  c: Candidate;
  index: number;
  total: number;
  q: AnalogQuery;
  source: Source;
  prev: { c: Candidate; q: AnalogQuery } | null;
}) {
  const tint = BODY[q.target].tint;
  const target = targetOf(q);
  // Where it differs: the measured gaps against the target, then what the data can't speak to
  const gaps = c.targetMetrics ? measuredGaps(c, c.targetMetrics, target.short) : matchProfile(c, q).flatMap((m) => (m.gap && m.dim !== "geology" ? [m.gap] : []));
  const differs = [...gaps, ...c.breaks];
  const analysis = useAnalysis(c, q, source === "live" && !!c.shape);
  const ai = analysis && analysis !== "pending" ? analysis : null;
  const scoreDelta = prev ? pct(overallScore(c, q)) - pct(overallScore(prev.c, prev.q)) : null;

  return (
    <div>
      <div className="flex items-center justify-between gap-3 text-[11px] text-white/40" style={{ animation: "rise-in .6s var(--ease-out-expo) both" }}>
        <span className="flex items-center gap-2">
          <span className="font-mono tabular-nums text-white/60">
            {String(index + 1).padStart(2, "0")}
            <span className="text-white/25"> / {String(total).padStart(2, "0")}</span>
          </span>
          <span className="h-[6px] w-[6px] rounded-full" style={{ background: tint }} />
          {BODY[q.target].label} analog
        </span>
        {source === "sample" ? (
          <span title="No search backend connected: ranked over the bundled sample sites">Sample data</span>
        ) : (
          c.shape && <span title={`H3 res 7 cell ${c.shape.cell}; target terrain from ${c.shape.dem}`}>Terrain search</span>
        )}
      </div>

      <div className="mt-3 flex items-center justify-between gap-4" style={{ animation: "rise-in .6s var(--ease-out-expo) .03s both" }}>
        <div className="min-w-0">
          <h2 className="text-[26px] font-medium leading-[1.1] tracking-[-0.025em] text-white">{c.name}</h2>
          {!!c.missed?.length && (
            <p className="mb-1 flex items-center gap-1.5 text-[11px] text-[#f3b453]" title="Too few sites met every limit, so the closest ones are shown">
              <span className="h-1.5 w-1.5 rounded-full bg-[#f3b453]" />
              Near miss · outside {c.missed.map((k) => (k in FIELDS ? FIELDS[k as NumKey].label.toLowerCase() : k)).join(", ")}
            </p>
          )}
          <p className="mt-1 truncate text-[12.5px] text-white/45">
            {c.region}
            <span className="ml-2 font-mono text-[10.5px] text-white/30">{formatCoord(c.lat, c.lon)}</span>
          </p>
        </div>
        <ScoreRing score={overallScore(c, q)} delta={scoreDelta} tint={tint} />
      </div>

      {c.shape && (
        <div className="mt-6">
          <ShapeCompare shape={c.shape} targetName={target.short} tint={tint} />
        </div>
      )}

      {/* Reasoning, up front: why it's an analog and where the analogy breaks */}
      <section className="mt-6 space-y-4 text-[12.5px]" style={{ animation: "rise-in .6s var(--ease-out-expo) .12s both" }}>
        {analysis === "pending" ? (
          <Thinking />
        ) : (
          <>
            {ai && (
              <p className="text-[14px] leading-snug tracking-[-0.01em] text-white/90" style={{ animation: "rise-in .6s var(--ease-out-expo) both" }}>
                {ai.verdict}.
              </p>
            )}
            <div>
              <Label className="mb-2">Why it&apos;s an analog</Label>
              <Bullets items={ai ? ai.holds : c.why} dot={tint} tone="text-white/75" />
            </div>
            <div>
              <Label className="mb-2">Where it differs</Label>
              <Bullets items={ai ? ai.breaks : differs} dot="#f3b453" tone="text-white/55" />
            </div>
            {ai?.test && (
              <div>
                <Label className="mb-2">Rehearse here</Label>
                <p className="leading-snug text-white/75" style={{ animation: "rise-in .5s var(--ease-out-expo) .1s both" }}>
                  {ai.test}
                </p>
              </div>
            )}
          </>
        )}
      </section>

      <details className="group mt-6 border-t border-white/[0.06] pt-4 text-[12px]" style={{ animation: "rise-in .6s var(--ease-out-expo) .2s both" }}>
        <summary className="flex cursor-pointer list-none items-center justify-between text-white/45 transition-colors hover:text-white/75 [&::-webkit-details-marker]:hidden">
          Measured values
          <svg width="10" height="10" viewBox="0 0 10 10" className="transition-transform group-open:rotate-90" aria-hidden>
            <path d="M3.5 2l3 3-3 3" stroke="currentColor" strokeWidth="1.4" fill="none" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </summary>
        <div className="mt-4">
          <Measurements c={c} q={q} tint={tint} />
        </div>
        <p className="mt-4 text-[10.5px] leading-relaxed text-white/30">
          Imagery: {c.imagery.source}. Climate: {c.climate.source}.{c.soil && " Surface material: WRB 2006 world soil map."}
          {ai && ` Reasoning written by ${ai.model} from these measured values only.`}
        </p>
      </details>
    </div>
  );
}

/** Right-third panel: the terrain shape match, and measured values against the target. */
export function EvidencePanel() {
  const { mode, results, active, query, source, searchFrom, trail, trailAt } = useUi();
  const c = results[active];
  const shown = mode === "site" || mode === "diving" || mode === "surfacing" || (mode === "searching" && searchFrom === "site");
  if (!c || !query || !shown) return null;
  // On a refined step's top result, compare with the previous step's top result.
  const before = active === 0 && trailAt > 0 && trail[trailAt]?.results === results ? trail[trailAt - 1] : null;
  const prev = before ? { c: before.results[0], q: before.query } : null;
  return (
    <aside
      aria-label="Candidate evidence"
      className="fixed right-6 top-[72px] z-20 hidden max-h-[calc((100vh-96px)/var(--ui-zoom,1))] w-[min(420px,33vw)] flex-col md:flex"
      style={{
        animation: mode === "diving" ? `rise-in .9s var(--ease-out-expo) ${DIVE.panel}s both` : undefined,
        opacity: mode === "surfacing" ? 0 : 1,
        transform: mode === "surfacing" ? "translateX(16px)" : undefined,
        transition: "opacity .35s ease, transform .5s var(--ease-out-expo)",
      }}
    >
      <div className="min-h-0 overflow-y-auto overscroll-contain rounded-[22px] border border-white/[0.08] bg-[rgb(10_11_14/0.62)] p-5 shadow-[0_30px_80px_-30px_rgb(0_0_0/0.9),inset_0_1px_0_rgb(255_255_255/0.05)] backdrop-blur-2xl backdrop-saturate-150 [scrollbar-width:none]">
        <Body key={`${c.id}:${trailAt}`} c={c} index={active} total={results.length} q={query} source={source} prev={prev} />
      </div>
    </aside>
  );
}
