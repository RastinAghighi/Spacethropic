"use client";

import { useState } from "react";
import { DIVE, useUi } from "@/lib/ui";
import { research, useResearch } from "@/lib/research";
import { formatCoord, type Candidate } from "@/lib/candidates";
import { BODY } from "@/lib/catalog";
import { DIMS, matchProfile, overallScore, suggest, targetOf, type DimMatch, type Filters, type Tab } from "@/lib/profile";
import type { AnalogQuery } from "@/lib/search";
import { useRunSearch } from "./search/primitives";

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
  const r = 25;
  const circ = 2 * Math.PI * r;
  return (
    <div className="flex flex-col items-center">
      <div className="relative grid h-[62px] w-[62px] place-items-center">
        <svg width="62" height="62" viewBox="0 0 62 62" className="absolute inset-0 -rotate-90" aria-hidden>
          <circle cx="31" cy="31" r={r} fill="none" stroke="rgb(255 255 255 / 0.07)" strokeWidth="2.5" />
          <circle
            cx="31"
            cy="31"
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
        <span className="text-[17px] font-medium tracking-[-0.03em] text-white">
          <Ticker value={pct(score)} />
          <span className="text-[10px] text-white/40">%</span>
        </span>
      </div>
      <Delta value={delta} className="mt-1" fallback="match" />
    </div>
  );
}

/**
 * What the last refine gained. Only gains are called out: a refine trades breadth for the
 * property asked for, and the numbers themselves already show the rest.
 */
function Delta({ value, className, fallback }: { value: number | null; className?: string; fallback?: string }) {
  if (value === null || value < 5)
    return fallback ? <p className={`text-[9.5px] uppercase tracking-[0.14em] text-white/30 ${className ?? ""}`}>{fallback}</p> : null;
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
      <div role="row" className={`${COLS} pb-1.5 text-[10px] uppercase tracking-[0.12em] text-white/30`}>
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

/** The tool's proposed next refine, stated as the limit itself and its measured effect. */
function NextStep({ c, q, results, tint }: { c: Candidate; q: AnalogQuery; results: Candidate[]; tint: string }) {
  const { run, busy } = useRunSearch();
  const [i, setI] = useState(0);
  const ideas = suggest(q, c, results);
  if (!ideas.length) return null;
  const s = ideas[i % ideas.length];
  const tab = DIMS[s.dim].tab;
  const enter = () => {
    research.preview(s.filters);
    research.hover(tab);
  };
  const leave = () => {
    research.preview(null);
    research.hover(null);
  };
  const go = () => {
    leave();
    run({ ...q, filters: s.filters, step: s.limit });
  };

  return (
    <div className="mt-5" style={{ animation: "rise-in .7s var(--ease-out-expo) .35s both" }}>
      <div className="mb-1.5 flex items-center justify-between">
        <p className="text-[10px] uppercase tracking-[0.12em] text-white/30">Suggested refine</p>
        {ideas.length > 1 && (
          <button
            type="button"
            onClick={() => setI((v) => v + 1)}
            className="flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10.5px] tabular-nums text-white/35 transition-colors hover:text-white focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/40"
            aria-label="Another suggestion"
          >
            {(i % ideas.length) + 1} / {ideas.length}
            <svg width="11" height="11" viewBox="0 0 12 12" aria-hidden>
              <path d="M10 6a4 4 0 1 1-1.2-2.85M10 1.75V4H7.75" stroke="currentColor" strokeWidth="1.2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        )}
      </div>
      {/* Gradient border with a single sheen on arrival */}
      <div
        className="rounded-[14px] p-px"
        style={{
          background: `linear-gradient(110deg, rgb(255 255 255 / 0.09) 30%, ${tint}aa 50%, rgb(255 255 255 / 0.09) 70%) 0 0 / 250% 100%`,
          animation: "suggest-sheen 2.4s var(--ease-out-expo) .6s both",
        }}
      >
        <button
          key={s.limit}
          type="button"
          onClick={go}
          disabled={busy}
          onPointerEnter={enter}
          onPointerLeave={leave}
          onFocus={enter}
          onBlur={leave}
          title={`${s.title}. ${s.reason}.`}
          className="group flex w-full items-center justify-between gap-3 rounded-[13px] bg-[rgb(14_15_19/0.92)] py-2.5 pl-3.5 pr-2.5 text-left transition-colors hover:bg-[rgb(22_23_28/0.95)] focus-visible:outline-none disabled:opacity-60"
        >
          <span className="min-w-0" style={{ animation: "rise-in .45s var(--ease-out-expo) both" }}>
            <span className="block truncate font-mono text-[13px] text-white">{s.limit}</span>
            <span className="mt-0.5 block truncate text-[11px] tabular-nums text-white/40">
              {DIMS[s.dim].metric.toLowerCase()} match {pct(s.before)} → <span className="text-[#8fe3b0]">{pct(s.after)}</span>
              <span className="text-white/20"> · </span>
              {results.length} → {s.results.length} sites
            </span>
          </span>
          <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-white text-black transition-transform duration-300 group-hover:translate-x-0.5">
            <svg width="12" height="12" viewBox="0 0 14 14" fill="none" aria-hidden>
              <path d="M2.5 7h9M7.75 3.25L11.5 7l-3.75 3.75" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
        </button>
      </div>
    </div>
  );
}

function Body({
  c,
  index,
  total,
  q,
  results,
  source,
  applied,
  hover,
  prev,
}: {
  c: Candidate;
  index: number;
  total: number;
  q: AnalogQuery;
  results: Candidate[];
  source: "live" | "sample";
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
        {source === "sample" && <span title="No search backend connected: ranked over the bundled sample sites">Sample data</span>}
      </div>

      <div className="mt-4 flex items-start justify-between gap-4" style={{ animation: "rise-in .6s var(--ease-out-expo) .03s both" }}>
        <div className="min-w-0">
          <h2 className="text-[26px] font-medium leading-[1.1] tracking-[-0.025em] text-white">{c.name}</h2>
          <p className="mt-1.5 text-[12.5px] text-white/45">
            {c.region}
            <span className="ml-2 font-mono text-[10.5px] text-white/30">{formatCoord(c.lat, c.lon)}</span>
          </p>
        </div>
        <ScoreRing score={overallScore(c, q)} delta={scoreDelta} tint={tint} />
      </div>

      <section className="mt-6" style={{ animation: "rise-in .6s var(--ease-out-expo) .1s both" }}>
        <MatchTable match={match} weights={applied.weights} target={target.short} tint={tint} deltas={deltas} hover={hover} />
      </section>

      <NextStep c={c} q={q} results={results} tint={tint} />

      <details className="group mt-6 border-t border-white/[0.06] pt-3 text-[12px]" style={{ animation: "rise-in .6s var(--ease-out-expo) .4s both" }}>
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
        <p className="mt-4 text-[10px] uppercase tracking-[0.12em] text-white/30">Where it differs</p>
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

/** Right-third panel: measured values against the target, and the tool's suggested next refine. */
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
      className="fixed right-5 top-5 z-20 hidden max-h-[calc(100vh-40px)] w-[min(420px,33vw)] flex-col md:flex"
      style={{
        animation: mode === "diving" ? `rise-in .9s var(--ease-out-expo) ${DIVE.panel}s both` : undefined,
        opacity: mode === "surfacing" ? 0 : 1,
        transform: mode === "surfacing" ? "translateX(16px)" : undefined,
        transition: "opacity .35s ease, transform .5s var(--ease-out-expo)",
      }}
    >
      <div className="min-h-0 overflow-y-auto overscroll-contain rounded-[22px] border border-white/[0.08] bg-[rgb(10_11_14/0.6)] p-6 shadow-[0_30px_80px_-30px_rgb(0_0_0/0.9),inset_0_1px_0_rgb(255_255_255/0.05)] backdrop-blur-2xl backdrop-saturate-150 [scrollbar-width:none]">
        <Body key={`${c.id}:${trailAt}`} c={c} index={active} total={results.length} q={query} results={results} source={source} applied={applied} hover={hover} prev={prev} />
      </div>
    </aside>
  );
}
