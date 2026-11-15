"use client";

import { DIVE, useUi } from "@/lib/ui";
import { research, useResearch } from "@/lib/research";
import { formatCoord, type Candidate } from "@/lib/candidates";
import { BODY } from "@/lib/catalog";
import { DIMS, FIELDS, matchProfile, overallScore, targetOf, type DimMatch, type Filters, type NumKey, type Tab } from "@/lib/profile";
import type { AnalogQuery, Source } from "@/lib/search";
import { Label } from "./search/primitives";
import { ShapeCompare } from "./ShapeCompare";

const AMBER = "#f3b453";
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

const COLS = "grid grid-cols-[76px_minmax(0,1fr)_minmax(0,1fr)_40px_52px] items-center gap-x-2.5";

/** Measured values side by side: the site, the target, and how close they are. */
function MatchTable({ match, weights, target, tint, deltas, hover }: { match: DimMatch[]; weights: Filters["weights"]; target: string; tint: string; deltas: (number | null)[]; hover: Tab | null }) {
  return (
    <div role="table" aria-label={`Measured values against ${target}`}>
      <div role="row" className={`${COLS} pb-1.5 text-[10px] font-medium uppercase tracking-[0.12em] text-white/35`}>
        <span role="columnheader" />
        <span role="columnheader">Here</span>
        <span role="columnheader" title={target}>
          Target
        </span>
        <span role="columnheader" className="col-span-2 text-right">
          Match
        </span>
      </div>
      {match.map((m, i) => {
        const ignored = weights[m.dim] === 0;
        const short = !!m.gap && !ignored;
        const tab = DIMS[m.dim].tab;
        return (
          <button
            key={m.dim}
            type="button"
            role="row"
            onClick={() => research.open(tab)}
            onPointerEnter={() => research.hover(tab)}
            onPointerLeave={() => research.hover(null)}
            onFocus={() => research.hover(tab)}
            onBlur={() => research.hover(null)}
            title={m.gap ?? `Refine on ${DIMS[m.dim].label.toLowerCase()}`}
            className={`${COLS} -mx-2 w-[calc(100%+16px)] rounded-lg px-2 py-[7px] text-left transition-colors duration-200 focus-visible:outline-none ${hover === tab ? "bg-white/[0.06]" : "hover:bg-white/[0.04]"} ${ignored ? "opacity-35" : ""}`}
          >
            <span role="cell" className="flex items-center gap-1.5 text-[12px] text-white/50">
              {DIMS[m.dim].metric}
              {weights[m.dim] === 2 && <span title="Prioritised" className="h-1 w-1 rounded-full" style={{ background: tint }} />}
            </span>
            <span role="cell" title={m.earth} className="truncate text-[13px] tabular-nums" style={{ color: short ? AMBER : "rgb(255 255 255 / 0.92)" }}>
              {m.earth}
            </span>
            <span role="cell" title={m.target} className="truncate text-[13px] tabular-nums text-white/40">
              {m.target}
            </span>
            <span role="cell" aria-hidden className="relative h-[3px] overflow-hidden rounded-full bg-white/[0.07]">
              <span
                className="absolute inset-y-0 left-0 rounded-full"
                style={{ width: `${pct(m.score)}%`, background: short ? AMBER : tint, transformOrigin: "0 50%", animation: `bar-in .9s var(--ease-out-expo) ${0.2 + i * 0.05}s both` }}
              />
            </span>
            <span role="cell" className="flex items-center justify-end gap-1">
              <Delta value={deltas[i]} />
              <span className="font-mono text-[11px] tabular-nums" style={{ color: short ? AMBER : "rgb(255 255 255 / 0.55)" }}>
                {ignored ? "—" : pct(m.score)}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

function Body({
  c,
  index,
  total,
  q,
  source,
  applied,
  hover,
  prev,
}: {
  c: Candidate;
  index: number;
  total: number;
  q: AnalogQuery;
  source: Source;
  applied: Filters;
  hover: Tab | null;
  prev: { c: Candidate; q: AnalogQuery } | null;
}) {
  const tint = BODY[q.target].tint;
  const target = targetOf(q);
  const match = matchProfile(c, q);
  const before = prev ? matchProfile(prev.c, prev.q) : null;
  const deltas = match.map((m, i) => (before ? pct(m.score) - pct(before[i].score) : null));
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

      <section className="mt-6" style={{ animation: "rise-in .6s var(--ease-out-expo) .1s both" }}>
        <MatchTable match={match} weights={applied.weights} target={target.short} tint={tint} deltas={deltas} hover={hover} />
      </section>

      <details className="group mt-6 border-t border-white/[0.06] pt-4 text-[12px]" style={{ animation: "rise-in .6s var(--ease-out-expo) .4s both" }}>
        <summary className="flex cursor-pointer list-none items-center justify-between text-white/40 transition-colors hover:text-white/70 [&::-webkit-details-marker]:hidden">
          About this site
          <svg width="10" height="10" viewBox="0 0 10 10" className="transition-transform group-open:rotate-90" aria-hidden>
            <path d="M3.5 2l3 3-3 3" stroke="currentColor" strokeWidth="1.4" fill="none" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </summary>
        <p className="mt-3 text-[13px] leading-relaxed text-white/70">{c.summary}</p>
        <ul className="mt-3 space-y-1.5">
          {c.why.map((w) => (
            <li key={w} className="flex gap-2.5 leading-snug text-white/55">
              <span className="mt-[8px] h-px w-2 shrink-0 bg-white/30" aria-hidden />
              {w}
            </li>
          ))}
        </ul>
        <Label className="mt-4">Where it differs</Label>
        <ul className="mt-1.5 space-y-1.5">
          {c.breaks.map((b) => (
            <li key={b} className="flex gap-2.5 leading-snug text-white/45">
              <span className="mt-[8px] h-px w-2 shrink-0 bg-white/20" aria-hidden />
              {b}
            </li>
          ))}
        </ul>
        <p className="mt-4 text-[10.5px] leading-relaxed text-white/30">
          Imagery: NASA HLS via GIBS, {c.imagery.date}. Climate: NASA POWER climatology. Target values are indicative.
        </p>
      </details>
    </div>
  );
}

/** Right-third panel: the terrain shape match, and measured values against the target. */
export function EvidencePanel() {
  const { mode, results, active, query, source, searchFrom, trail, trailAt } = useUi();
  const { applied, hover } = useResearch();
  const c = results[active];
  const shown = mode === "site" || mode === "diving" || mode === "surfacing" || (mode === "searching" && searchFrom === "site");
  if (!c || !query || !shown) return null;
  // On a refined step's top result, compare with the previous step's top result.
  const before = active === 0 && trailAt > 0 && trail[trailAt]?.results === results ? trail[trailAt - 1] : null;
  const prev = before ? { c: before.results[0], q: before.query } : null;
  return (
    <aside
      aria-label="Candidate evidence"
      className="fixed right-6 top-[72px] z-20 hidden max-h-[calc(100vh-96px)] w-[min(420px,33vw)] flex-col md:flex"
      style={{
        animation: mode === "diving" ? `rise-in .9s var(--ease-out-expo) ${DIVE.panel}s both` : undefined,
        opacity: mode === "surfacing" ? 0 : 1,
        transform: mode === "surfacing" ? "translateX(16px)" : undefined,
        transition: "opacity .35s ease, transform .5s var(--ease-out-expo)",
      }}
    >
      <div className="min-h-0 overflow-y-auto overscroll-contain rounded-[22px] border border-white/[0.08] bg-[rgb(10_11_14/0.62)] p-5 shadow-[0_30px_80px_-30px_rgb(0_0_0/0.9),inset_0_1px_0_rgb(255_255_255/0.05)] backdrop-blur-2xl backdrop-saturate-150 [scrollbar-width:none]">
        <Body key={`${c.id}:${trailAt}`} c={c} index={active} total={results.length} q={query} source={source} applied={applied} hover={hover} prev={prev} />
      </div>
    </aside>
  );
}
