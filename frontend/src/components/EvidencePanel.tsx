"use client";

import { useState } from "react";
import { DIVE, useUi } from "@/lib/ui";
import { research, useResearch } from "@/lib/research";
import { formatCoord, type Candidate } from "@/lib/candidates";
import { BODY } from "@/lib/catalog";
import { DIMS, matchProfile, overallScore, suggest, targetOf, type DimMatch, type Filters } from "@/lib/profile";
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

/** One dimension: a quiet bar that opens its detail and lights its drawer tab on hover. */
function FingerprintRow({ m, weight, tint, delta, i }: { m: DimMatch; weight: number; tint: string; delta: number | null; i: number }) {
  const ignored = weight === 0;
  const short = !!m.gap && !ignored;
  const tab = DIMS[m.dim].tab;
  return (
    <li>
      <button
        type="button"
        onClick={() => research.open(tab)}
        onPointerEnter={() => research.hover(tab)}
        onPointerLeave={() => research.hover(null)}
        onFocus={() => research.hover(tab)}
        onBlur={() => research.hover(null)}
        className={`group -mx-2.5 block w-[calc(100%+20px)] rounded-xl px-2.5 py-2 text-left transition-colors duration-200 hover:bg-white/[0.035] focus-visible:bg-white/[0.035] focus-visible:outline-none ${ignored ? "opacity-35" : ""}`}
      >
        <span className="flex items-center gap-3">
          <span className="flex w-[84px] shrink-0 items-center gap-1.5 text-[12.5px] text-white/70 transition-colors group-hover:text-white">
            {DIMS[m.dim].label}
            {weight === 2 && <span title="Prioritised" className="h-1 w-1 rounded-full" style={{ background: tint }} />}
          </span>
          <span className="relative h-[3px] flex-1 overflow-hidden rounded-full bg-white/[0.07]">
            <span
              className="absolute inset-y-0 left-0 rounded-full"
              style={{
                width: `${pct(m.score)}%`,
                background: short ? AMBER : tint,
                opacity: short ? 0.9 : 0.8,
                transformOrigin: "0 50%",
                animation: `bar-in .9s var(--ease-out-expo) ${0.2 + i * 0.05}s both`,
              }}
            />
          </span>
          <span className="flex w-[64px] shrink-0 items-center justify-end gap-1.5">
            <Delta value={delta} />
            <span className="font-mono text-[11px] tabular-nums" style={{ color: short ? AMBER : "rgb(255 255 255 / 0.6)" }}>
              {ignored ? "—" : pct(m.score)}
            </span>
          </span>
        </span>
        {/* Detail on demand */}
        <span className="grid grid-rows-[0fr] transition-[grid-template-rows] duration-300 ease-out group-hover:grid-rows-[1fr] group-focus-visible:grid-rows-[1fr]">
          <span className="min-h-0 overflow-hidden">
            <span className="flex items-baseline justify-between gap-3 pl-[96px] pt-1.5 text-[11px] leading-snug">
              <span className="text-white/55">
                <span className="font-mono text-white/80">{m.earth}</span>
                <span className="px-1.5 text-white/25">vs</span>
                <span className="font-mono">{m.target}</span>
              </span>
              <span className="shrink-0 text-white/40">Refine ›</span>
            </span>
          </span>
        </span>
      </button>
    </li>
  );
}

/** One plain sentence a non-specialist can act on. */
function Verdict({ match, weights }: { match: DimMatch[]; weights: Filters["weights"] }) {
  const counted = match.filter((m) => weights[m.dim] > 0);
  const strong = counted.filter((m) => m.score >= 0.75).sort((a, b) => b.score - a.score);
  const worst = counted.filter((m) => m.gap).sort((a, b) => a.score - b.score)[0];
  const list = (ms: DimMatch[]) => ms.map((m) => DIMS[m.dim].label.toLowerCase()).join(ms.length > 2 ? ", " : " and ");
  return (
    <p className="text-[14.5px] leading-[1.45] tracking-[-0.005em] text-white/85">
      {strong.length ? <>Strong on {list(strong.slice(0, 3))}.</> : <>A partial match.</>}{" "}
      {worst ? (
        <span className="text-white/50">
          Weakest on {DIMS[worst.dim].label.toLowerCase()}: <span style={{ color: AMBER }}>{worst.brief}</span>.
        </span>
      ) : (
        <span className="text-white/50">No dimension falls short.</span>
      )}
    </p>
  );
}

/** The tool's proposal for the next refine, with its predicted effect. */
function NextStep({ c, q, results, tint }: { c: Candidate; q: AnalogQuery; results: Candidate[]; tint: string }) {
  const { run, busy } = useRunSearch();
  const [i, setI] = useState(0);
  const ideas = suggest(q, c, results);
  if (!ideas.length)
    return (
      <p className="mt-6 text-[12px] leading-relaxed text-white/40">
        Nothing in this pool closes the remaining gaps. Open a drawer on the left to set your own limits.
      </p>
    );
  const s = ideas[i % ideas.length];
  const go = () => run({ ...q, filters: s.filters, step: s.limit });

  return (
    <div className="mt-6" style={{ animation: "rise-in .7s var(--ease-out-expo) .35s both" }}>
      <div className="mb-2 flex items-center justify-between">
        <p className="text-[10.5px] font-medium uppercase tracking-[0.14em] text-white/40">Suggested next step</p>
        {ideas.length > 1 && (
          <button
            type="button"
            onClick={() => setI((v) => v + 1)}
            className="flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10.5px] tabular-nums text-white/40 transition-colors hover:text-white focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/40"
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
        className="rounded-2xl p-px"
        style={{
          background: `linear-gradient(110deg, rgb(255 255 255 / 0.08) 30%, ${tint}aa 50%, rgb(255 255 255 / 0.08) 70%) 0 0 / 250% 100%`,
          animation: "suggest-sheen 2.4s var(--ease-out-expo) .6s both",
        }}
      >
        <button
          key={s.limit}
          type="button"
          onClick={go}
          disabled={busy}
          onPointerEnter={() => research.preview(s.filters)}
          onPointerLeave={() => research.preview(null)}
          onFocus={() => research.preview(s.filters)}
          onBlur={() => research.preview(null)}
          className="group block w-full rounded-[15px] bg-[rgb(14_15_19/0.92)] px-4 py-3.5 text-left transition-colors hover:bg-[rgb(22_23_28/0.95)] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/40 disabled:opacity-60"
        >
          <span className="flex items-center justify-between gap-3" style={{ animation: "rise-in .45s var(--ease-out-expo) both" }}>
            <span className="text-[14px] font-medium tracking-[-0.01em] text-white">{s.title}</span>
            <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-white text-black transition-transform duration-300 group-hover:translate-x-0.5">
              <svg width="12" height="12" viewBox="0 0 14 14" fill="none" aria-hidden>
                <path d="M2.5 7h9M7.75 3.25L11.5 7l-3.75 3.75" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
          </span>
          <span className="mt-0.5 block text-[12px] text-white/45">{s.reason}.</span>
          <span className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px]">
            <span className="rounded-md bg-white/[0.06] px-1.5 py-0.5 font-mono text-white/70">{s.limit}</span>
            <span className="text-white/35">→</span>
            <span className="tabular-nums text-white/55">
              {s.results.length} site{s.results.length > 1 ? "s" : ""} · {DIMS[s.dim].label.toLowerCase()} {pct(s.before)}
              <span className="text-white/30"> → </span>
              <span className="text-[#8fe3b0]">{pct(s.after)}</span>
            </span>
          </span>
        </button>
      </div>
    </div>
  );
}

function Body({ c, index, total, q, results, source, applied, prev }: { c: Candidate; index: number; total: number; q: AnalogQuery; results: Candidate[]; source: "live" | "sample"; applied: Filters; prev: { c: Candidate; q: AnalogQuery } | null }) {
  const tint = BODY[q.target].tint;
  const target = targetOf(q);
  const match = matchProfile(c, q);
  const before = prev ? matchProfile(prev.c, prev.q) : null;
  const dimDelta = (i: number) => (before ? pct(match[i].score) - pct(before[i].score) : null);
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

      <div className="mt-5" style={{ animation: "rise-in .6s var(--ease-out-expo) .08s both" }}>
        <Verdict match={match} weights={applied.weights} />
      </div>

      <section className="mt-5" style={{ animation: "rise-in .6s var(--ease-out-expo) .12s both" }} aria-label={`Match against ${target.name}`}>
        <p className="mb-1 text-[10.5px] font-medium uppercase tracking-[0.14em] text-white/40">Against {target.short}</p>
        <ul>
          {match.map((m, i) => (
            <FingerprintRow key={m.dim} m={m} weight={applied.weights[m.dim]} tint={tint} delta={dimDelta(i)} i={i} />
          ))}
        </ul>
      </section>

      <NextStep c={c} q={q} results={results} tint={tint} />

      <section className="mt-8" style={{ animation: "rise-in .6s var(--ease-out-expo) .4s both" }}>
        <p className="text-[13px] leading-relaxed text-white/60">{c.summary}</p>
        <ul className="mt-3 space-y-1.5">
          {c.why.map((w) => (
            <li key={w} className="flex gap-2.5 text-[12.5px] leading-snug text-white/55">
              <span className="mt-[8px] h-px w-2 shrink-0 bg-white/30" aria-hidden />
              {w}
            </li>
          ))}
        </ul>
        <details className="group mt-4 text-[12px] text-white/40">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 transition-colors hover:text-white/70 [&::-webkit-details-marker]:hidden">
            <svg width="9" height="9" viewBox="0 0 10 10" className="transition-transform group-open:rotate-90" aria-hidden>
              <path d="M3.5 2l3 3-3 3" stroke="currentColor" strokeWidth="1.4" fill="none" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Field limits and sources
          </summary>
          <ul className="mt-2 space-y-1.5 pl-4">
            {c.breaks.map((b) => (
              <li key={b} className="leading-snug text-white/50">
                {b}
              </li>
            ))}
          </ul>
          <p className="mt-3 pl-4 text-[10.5px] leading-relaxed text-white/30">
            Imagery: NASA HLS via GIBS, {c.imagery.date}. Climate: NASA POWER climatology. Target values are indicative.
          </p>
        </details>
      </section>
    </div>
  );
}

/** Right-third panel: a verdict, the match fingerprint, and the tool's suggested next step. */
export function EvidencePanel() {
  const { mode, results, active, query, source, searchFrom, trail, trailAt } = useUi();
  const { applied } = useResearch();
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
        <Body key={`${c.id}:${trailAt}`} c={c} index={active} total={results.length} q={query} results={results} source={source} applied={applied} prev={prev} />
      </div>
    </aside>
  );
}
