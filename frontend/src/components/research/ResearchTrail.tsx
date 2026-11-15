"use client";

import { ui, useUi } from "@/lib/ui";
import { BODY } from "@/lib/catalog";
import { DEFAULT_FILTERS, describeFilters, targetOf } from "@/lib/profile";

const MAX_STEPS = 3;

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
      className="flex h-8 min-w-0 items-center gap-3"
      aria-hidden={!inSite}
      inert={!inSite}
      style={{
        opacity: inSite ? 1 : 0,
        transform: inSite ? "none" : "translateY(-4px)",
        filter: inSite ? "none" : "blur(3px)",
        transition: "opacity .6s ease .1s, transform .7s var(--ease-out-expo) .1s, filter .6s ease .1s",
      }}
    >
      <p className="flex shrink-0 items-center gap-2 whitespace-nowrap text-[13px] font-medium tracking-[-0.01em] text-white/90">
        <span className="h-[7px] w-[7px] rounded-full" style={{ background: tint, boxShadow: `0 0 8px ${tint}` }} />
        Earth&apos;s mirror of {targetOf(first).short}
        {trail.length === 1 && !pending && <span className="font-normal text-white/35">· {trail[0].results.length} sites</span>}
      </p>
      {(trail.length > 1 || pending) && (
        <nav aria-label="Research trail" className="flex min-w-0 items-center gap-3">
          <span aria-hidden className="h-4 w-px shrink-0 bg-white/15" />
          <ol className="flex min-w-0 items-center gap-1">
            {shown.length < steps.length && (
              <li className="flex items-center gap-1 text-[11px] text-white/30">
                …<Chevron />
              </li>
            )}
            {shown.map(({ s, i }, j) => {
              const on = i === trailAt && !pending;
              const limits = describeFilters(s.query.filters ?? DEFAULT_FILTERS);
              return (
                <li key={i} className="flex items-center gap-1" style={{ animation: "rise-in .5s var(--ease-out-expo) both" }}>
                  {j > 0 && <Chevron />}
                  <span
                    className={`group/pill relative flex h-7 max-w-[220px] items-center rounded-full border backdrop-blur-xl transition-[background-color,border-color,color] duration-300 ${
                      on ? "border-white/25 bg-white/[0.12] text-white" : "border-white/[0.07] bg-[rgb(10_11_14/0.5)] text-white/50 hover:border-white/20 hover:text-white/85"
                    }`}
                  >
                    {/* The number turns into a remove control on hover (not on the first, broad step) */}
                    {i > 0 ? (
                      <button
                        type="button"
                        onClick={() => ui.removeStep(i)}
                        aria-label={`Remove step ${i + 1}${i < trail.length - 1 ? " and the steps after it" : ""}`}
                        title={i < trail.length - 1 ? "Remove this step and the ones after it" : "Remove this step"}
                        className={`group/x relative ml-1 grid h-5 w-5 shrink-0 place-items-center rounded-full text-[10px] font-semibold tabular-nums transition-colors duration-200 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/50 ${
                          on ? "bg-white text-black hover:bg-[#ff6b5e] hover:text-white" : "bg-white/10 text-white/60 hover:bg-[#ff6b5e] hover:text-white"
                        }`}
                      >
                        <span className="transition-[opacity,transform] duration-200 group-hover/x:scale-50 group-hover/x:opacity-0 group-focus-visible/x:scale-50 group-focus-visible/x:opacity-0" style={{ transitionTimingFunction: "var(--ease-out-expo)" }}>
                          {i + 1}
                        </span>
                        <svg
                          width="8"
                          height="8"
                          viewBox="0 0 8 8"
                          aria-hidden
                          className="absolute rotate-[-90deg] scale-50 opacity-0 transition-[opacity,transform] duration-300 group-hover/x:rotate-0 group-hover/x:scale-100 group-hover/x:opacity-100 group-focus-visible/x:rotate-0 group-focus-visible/x:scale-100 group-focus-visible/x:opacity-100"
                          style={{ transitionTimingFunction: "var(--ease-out-expo)" }}
                        >
                          <path d="M1.5 1.5l5 5M6.5 1.5l-5 5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
                        </svg>
                      </button>
                    ) : (
                      <span className={`ml-1 grid h-5 w-5 shrink-0 place-items-center rounded-full text-[10px] font-semibold tabular-nums ${on ? "bg-white text-black" : "bg-white/10 text-white/60"}`}>{i + 1}</span>
                    )}
                    <button
                      type="button"
                      onClick={() => ui.restore(i)}
                      aria-current={on ? "step" : undefined}
                      title={`${s.results.length} sites · ${limits.length ? limits.join(" · ") : "physical match, no limits"}`}
                      className="flex h-full min-w-0 items-center gap-1.5 rounded-r-full pl-1.5 pr-2.5 text-[11.5px] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/40"
                    >
                      <span className="truncate">{s.label}</span>
                      <span className="shrink-0 font-mono text-[10px] tabular-nums text-white/40">{s.results.length}</span>
                    </button>
                  </span>
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
      )}
    </div>
  );
}
