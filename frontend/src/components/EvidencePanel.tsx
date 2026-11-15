"use client";

import { DIVE, useUi } from "@/lib/ui";
import { research, useResearch } from "@/lib/research";
import { formatCoord, type Candidate } from "@/lib/candidates";
import { BODY } from "@/lib/catalog";
import { DIMS, matchProfile, overallScore, targetOf, type DimMatch, type Filters } from "@/lib/profile";
import type { AnalogQuery } from "@/lib/search";

const AMBER = "#f3b453";
const pct = (v: number) => `${Math.round(v * 100)}%`;

function Section({ title, children, i, aside }: { title: string; children: React.ReactNode; i: number; aside?: React.ReactNode }) {
  return (
    <section className="mt-7" style={{ animation: `rise-in .6s var(--ease-out-expo) ${0.05 * i}s both` }}>
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h3 className="text-[11px] font-medium uppercase tracking-[0.14em] text-white/40">{title}</h3>
        {aside}
      </div>
      {children}
    </section>
  );
}

function ScoreRing({ score, tint }: { score: number; tint: string }) {
  const r = 25;
  const circ = 2 * Math.PI * r;
  return (
    <div className="relative grid h-[62px] w-[62px] shrink-0 place-items-center">
      <svg width="62" height="62" viewBox="0 0 62 62" className="absolute inset-0 -rotate-90" aria-hidden>
        <circle cx="31" cy="31" r={r} fill="none" stroke="rgb(255 255 255 / 0.08)" strokeWidth="3" />
        <circle
          cx="31"
          cy="31"
          r={r}
          fill="none"
          stroke={tint}
          strokeWidth="3"
          strokeLinecap="round"
          strokeDasharray={circ}
          strokeDashoffset={circ * (1 - score)}
          style={{ ["--circ" as string]: `${circ}`, animation: "ring-in 1.1s var(--ease-out-expo) .15s both", filter: `drop-shadow(0 0 6px ${tint}66)` }}
        />
      </svg>
      <span className="text-[17px] font-medium tracking-[-0.03em] text-white tabular-nums">
        {Math.round(score * 100)}
        <span className="text-[10px] text-white/45">%</span>
      </span>
    </div>
  );
}

function MatchRow({ m, weight, tint, i }: { m: DimMatch; weight: number; tint: string; i: number }) {
  const ignored = weight === 0;
  const short = !!m.gap && !ignored;
  return (
    <li className={`py-2.5 ${ignored ? "opacity-40" : ""}`}>
      <div className="flex items-center gap-3">
        <p className="flex w-[92px] shrink-0 items-center gap-1.5 text-[12.5px] text-white/80">
          {DIMS[m.dim].label}
          {weight === 2 && (
            <span title="Prioritised" className="rounded px-1 text-[9px] font-semibold text-black" style={{ background: tint }}>
              ×2
            </span>
          )}
        </p>
        <div className="relative h-[5px] flex-1 overflow-hidden rounded-full bg-white/[0.07]">
          <div
            className="absolute inset-y-0 left-0 rounded-full"
            style={{
              width: pct(m.score),
              background: short ? AMBER : tint,
              transformOrigin: "0 50%",
              animation: `bar-in .9s var(--ease-out-expo) ${0.25 + i * 0.05}s both`,
            }}
          />
        </div>
        <p className="w-9 shrink-0 text-right font-mono text-[11px] tabular-nums" style={{ color: short ? AMBER : "rgb(255 255 255 / 0.7)" }}>
          {ignored ? "—" : pct(m.score)}
        </p>
      </div>
      <p className="mt-1 pl-[104px] font-mono text-[10.5px] leading-snug text-white/35">
        <span className="text-white/60">{m.earth}</span>
        <span className="px-1.5 text-white/20">vs</span>
        {m.target}
      </p>
      {short && (
        <div className="ml-[104px] mt-2 rounded-lg border px-2.5 py-2" style={{ borderColor: `${AMBER}2e`, background: `${AMBER}0b` }}>
          <p className="text-[11.5px] leading-snug text-white/70">{m.gap}</p>
          <button
            type="button"
            onClick={() => research.open(DIMS[m.dim].tab)}
            className="group mt-1.5 flex items-center gap-1 text-[11px] font-medium transition-opacity hover:opacity-80 focus-visible:outline-none focus-visible:underline"
            style={{ color: AMBER }}
          >
            Refine on {DIMS[m.dim].label.toLowerCase()}
            <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden className="transition-transform group-hover:translate-x-0.5">
              <path d="M3.5 2l3 3-3 3" stroke="currentColor" strokeWidth="1.4" fill="none" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        </div>
      )}
    </li>
  );
}

/** One plain-language line a non-specialist can read off the profile. */
function verdict(match: DimMatch[], weights: Filters["weights"]) {
  const counted = match.filter((m) => weights[m.dim] > 0);
  const strong = counted.filter((m) => m.score >= 0.75).sort((a, b) => b.score - a.score);
  const weak = counted.filter((m) => m.gap);
  const list = (ms: DimMatch[]) => ms.map((m) => DIMS[m.dim].label.toLowerCase()).join(ms.length > 2 ? ", " : " and ");
  const a = strong.length ? `Strong on ${list(strong.slice(0, 3))}.` : "No single strong dimension.";
  const b = weak.length ? ` Falls short on ${list(weak)}.` : " No dimension falls short.";
  return a + b;
}

function Body({ c, index, total, q, source, applied }: { c: Candidate; index: number; total: number; q: AnalogQuery; source: "live" | "sample"; applied: Filters }) {
  const tint = BODY[q.target].tint;
  const target = targetOf(q);
  const match = matchProfile(c, q);
  const score = overallScore(c, q);
  const shortCount = match.filter((m) => m.gap && applied.weights[m.dim] > 0).length;

  return (
    <div key={c.id}>
      <div className="flex items-center justify-between gap-3" style={{ animation: "rise-in .6s var(--ease-out-expo) both" }}>
        <div className="flex items-center gap-2 text-[11.5px] text-white/50">
          <span className="font-mono tabular-nums text-white/70">
            {String(index + 1).padStart(2, "0")}
            <span className="text-white/30"> / {String(total).padStart(2, "0")}</span>
          </span>
          <span className="h-3 w-px bg-white/15" />
          <span className="h-[7px] w-[7px] rounded-full" style={{ background: tint }} />
          {BODY[q.target].label} analog
        </div>
        {source === "sample" && (
          <span className="rounded-full border border-white/10 px-2 py-0.5 text-[10px] text-white/45" title="No search backend connected: ranked over the bundled sample sites">
            Sample data
          </span>
        )}
      </div>

      <div className="mt-4 flex items-start justify-between gap-4" style={{ animation: "rise-in .6s var(--ease-out-expo) .03s both" }}>
        <div className="min-w-0">
          <h2 className="text-[26px] font-medium leading-[1.1] tracking-[-0.025em] text-white">{c.name}</h2>
          <p className="mt-1.5 text-[13px] text-white/55">{c.region}</p>
          <p className="mt-1 font-mono text-[11px] text-white/35">{formatCoord(c.lat, c.lon)}</p>
        </div>
        <div className="flex flex-col items-center">
          <ScoreRing score={score} tint={tint} />
          <p className="mt-1 text-[9.5px] uppercase tracking-[0.14em] text-white/35">Match</p>
        </div>
      </div>

      <p className="mt-4 text-[14px] leading-relaxed text-white/75" style={{ animation: "rise-in .6s var(--ease-out-expo) .06s both" }}>
        {c.summary}
      </p>

      <Section
        title={`Against ${target.short}`}
        i={2}
        aside={
          shortCount > 0 && (
            <span className="flex items-center gap-1.5 text-[10.5px]" style={{ color: AMBER }}>
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: AMBER }} />
              {shortCount} gap{shortCount > 1 ? "s" : ""}
            </span>
          )
        }
      >
        <p className="mb-1 text-[12.5px] leading-snug text-white/55">{verdict(match, applied.weights)}</p>
        <ul className="divide-y divide-white/[0.05]">
          {match.map((m, i) => (
            <MatchRow key={m.dim} m={m} weight={applied.weights[m.dim]} tint={tint} i={i} />
          ))}
        </ul>
        <p className="mt-2 text-[10.5px] leading-relaxed text-white/30">
          Earth value first, then {target.name}. Target values are indicative.
        </p>
      </Section>

      <Section title="Why it's analogous" i={4}>
        <ul className="space-y-2">
          {c.why.map((w) => (
            <li key={w} className="flex gap-2.5 text-[13px] leading-snug text-white/80">
              <svg width="14" height="14" viewBox="0 0 14 14" className="mt-[3px] shrink-0 text-white/70" aria-hidden>
                <path d="M3 7.5l2.5 2.5L11 4.5" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              {w}
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Field notes on its limits" i={5}>
        <ul className="space-y-2">
          {c.breaks.map((b) => (
            <li key={b} className="flex gap-2.5 text-[13px] leading-snug text-white/55">
              <span className="mt-[9px] h-px w-2.5 shrink-0 bg-white/40" aria-hidden />
              {b}
            </li>
          ))}
        </ul>
      </Section>

      <p className="mt-7 border-t border-white/[0.07] pt-4 text-[10.5px] leading-relaxed text-white/35" style={{ animation: "rise-in .6s var(--ease-out-expo) .32s both" }}>
        Imagery: NASA HLS (Harmonized Landsat Sentinel-2) via GIBS, {c.imagery.date}.
        <br />
        Climate: NASA POWER long-term climatology.
      </p>
    </div>
  );
}

/** Right-third panel: how the selected candidate matches the target, and where it falls short. */
export function EvidencePanel() {
  const { mode, results, active, query, source, searchFrom } = useUi();
  const { applied } = useResearch();
  const c = results[active];
  const shown = mode === "site" || mode === "diving" || mode === "surfacing" || (mode === "searching" && searchFrom === "site");
  if (!c || !query || !shown) return null;
  return (
    <aside
      aria-label="Candidate evidence"
      className="fixed bottom-5 right-5 top-5 z-20 hidden w-[min(420px,33vw)] md:block"
      style={{
        animation: mode === "diving" ? `rise-in .9s var(--ease-out-expo) ${DIVE.panel}s both` : undefined,
        opacity: mode === "surfacing" ? 0 : 1,
        transform: mode === "surfacing" ? "translateX(16px)" : undefined,
        transition: "opacity .35s ease, transform .5s var(--ease-out-expo)",
      }}
    >
      <div className="h-full overflow-y-auto overscroll-contain rounded-[22px] border border-white/[0.09] bg-[rgb(10_11_14/0.62)] p-6 shadow-[0_30px_80px_-30px_rgb(0_0_0/0.9),inset_0_1px_0_rgb(255_255_255/0.05)] backdrop-blur-2xl backdrop-saturate-150 [scrollbar-width:thin]">
        <Body c={c} index={active} total={results.length} q={query} source={source} applied={applied} />
      </div>
    </aside>
  );
}
