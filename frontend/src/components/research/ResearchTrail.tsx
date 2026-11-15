"use client";

import { ui, useUi } from "@/lib/ui";
import { BODY } from "@/lib/catalog";
import { DEFAULT_FILTERS, describeFilters, overallScore, targetOf } from "@/lib/profile";

const MAX_STEPS = 4;

function Chevron() {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden className="shrink-0 text-white/20">
      <path d="M3.5 2l3 3-3 3" stroke="currentColor" strokeWidth="1.3" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/**
 * The research loop made visible: the broad physical match, then one step per refine,
 * each with its candidate count and best match. Any step can be revisited.
 */
export function ResearchTrail() {
  const { mode, query, trail, trailAt, searchFrom } = useUi();
  const pending = mode === "searching" && searchFrom === "site";
  const inSite = mode === "site" || pending;
  const first = trail[0]?.query;
  if (!first) return null;

  const tint = BODY[first.target].tint;
  const steps = trail.map((s, i) => ({ s, i }));
  const shown = steps.length > MAX_STEPS ? steps.slice(-MAX_STEPS) : steps;

  return (
    <div
      className="min-w-0"
      aria-hidden={!inSite}
      inert={!inSite}
      style={{
        opacity: inSite ? 1 : 0,
        transform: inSite ? "none" : "translateY(-4px)",
        filter: inSite ? "none" : "blur(3px)",
        transition: "opacity .6s ease .1s, transform .7s var(--ease-out-expo) .1s, filter .6s ease .1s",
      }}
    >
      <p className="flex items-center gap-2 text-[13px] font-medium tracking-[-0.01em] text-white/90">
        <span className="h-[7px] w-[7px] rounded-full" style={{ background: tint, boxShadow: `0 0 8px ${tint}` }} />
        Earth&apos;s mirror of {targetOf(first).short}
      </p>
      <nav aria-label="Research trail" className="mt-2">
        <ol className="flex items-center gap-1">
          {shown.length < steps.length && (
            <li className="flex items-center gap-1 text-[11px] text-white/30">
              …<Chevron />
            </li>
          )}
          {shown.map(({ s, i }, j) => {
            const on = i === trailAt && !pending;
            const best = Math.round(overallScore(s.results[0], s.query) * 100);
            const limits = describeFilters(s.query.filters ?? DEFAULT_FILTERS);
            return (
              <li key={i} className="flex items-center gap-1" style={{ animation: "rise-in .5s var(--ease-out-expo) both" }}>
                {j > 0 && <Chevron />}
                <button
                  type="button"
                  onClick={() => ui.restore(i)}
                  aria-current={on ? "step" : undefined}
                  title={limits.length ? limits.join(" · ") : "Physical match, no limits"}
                  className={`flex h-7 max-w-[220px] items-center gap-1.5 rounded-full border pl-1 pr-2.5 text-[11.5px] backdrop-blur-xl transition-[background-color,border-color,color] duration-300 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/40 ${
                    on ? "border-white/25 bg-white/[0.12] text-white" : "border-white/[0.07] bg-[rgb(10_11_14/0.5)] text-white/50 hover:border-white/20 hover:text-white/85"
                  }`}
                >
                  <span className={`grid h-5 w-5 shrink-0 place-items-center rounded-full text-[10px] font-semibold tabular-nums ${on ? "bg-white text-black" : "bg-white/10 text-white/60"}`}>{i + 1}</span>
                  <span className="truncate">{s.label}</span>
                  <span className="shrink-0 font-mono text-[10px] tabular-nums text-white/40">
                    {s.results.length} · {best}%
                  </span>
                </button>
              </li>
            );
          })}
          {pending && query && (
            <li className="flex items-center gap-1" style={{ animation: "rise-in .4s var(--ease-out-expo) both" }}>
              <Chevron />
              <span className="flex h-7 items-center gap-1.5 rounded-full border border-dashed border-white/20 px-2.5 text-[11.5px] text-white/60">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-white" />
                {query.step ?? "Refining"}
              </span>
            </li>
          )}
        </ol>
      </nav>
    </div>
  );
}
