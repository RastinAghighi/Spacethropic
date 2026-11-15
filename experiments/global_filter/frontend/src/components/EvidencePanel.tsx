"use client";

import { DIVE, useUi } from "@/lib/ui";
import { formatCoord, type Candidate } from "@/lib/candidates";
import type { AnalogTarget } from "@/lib/search";

const TARGET = {
  moon: { label: "Lunar analog", tint: "#cfd2d8" },
  mars: { label: "Mars analog", tint: "#d9774f" },
} as const;

/** Reference conditions on the target body, for the stat tiles. */
const REFERENCE: Record<AnalogTarget, { temp: string; cold: string; precip: string; solar: string }> = {
  mars: {
    temp: "Mars mean −63 °C",
    cold: "Mars winter nights −125 °C",
    precip: "Mars: none",
    solar: "Mars ~43% of Earth's",
  },
  moon: {
    temp: "Lunar equator −173 to 127 °C",
    cold: "Polar shadow < −230 °C",
    precip: "Moon: none",
    solar: "No atmosphere to attenuate",
  },
};

function Stat({ label, value, unit, note }: { label: string; value: string; unit: string; note: string }) {
  return (
    <div className="rounded-xl border border-white/[0.07] bg-white/[0.025] px-3.5 py-3">
      <p className="text-[11px] text-white/45">{label}</p>
      <p className="mt-1 text-[22px] font-medium leading-none tracking-[-0.02em] text-white tabular-nums">
        {value}
        <span className="ml-1 text-[12px] font-normal tracking-normal text-white/50">{unit}</span>
      </p>
      <p className="mt-1.5 text-[10.5px] text-white/35">{note}</p>
    </div>
  );
}

function Section({ title, children, i }: { title: string; children: React.ReactNode; i: number }) {
  return (
    <section className="mt-6" style={{ animation: `rise-in .6s var(--ease-out-expo) ${0.06 * i}s both` }}>
      <h3 className="mb-2.5 text-[11px] font-medium uppercase tracking-[0.14em] text-white/40">{title}</h3>
      {children}
    </section>
  );
}

function Body({ c, index, total, target, source }: { c: Candidate; index: number; total: number; target: AnalogTarget; source: "live" | "sample" }) {
  // Describe the site by the bodies it's an analog for; compare against the searched one when it applies.
  const body: AnalogTarget = c.targets.includes(target) ? target : c.targets[0];
  const ref = REFERENCE[body];
  const k = c.climate;
  return (
    <div key={c.id}>
      <div className="flex items-center justify-between gap-3" style={{ animation: "rise-in .6s var(--ease-out-expo) both" }}>
        <div className="flex items-center gap-2 text-[11.5px] text-white/50">
          <span className="font-mono tabular-nums text-white/70">
            {String(index + 1).padStart(2, "0")}
            <span className="text-white/30"> / {String(total).padStart(2, "0")}</span>
          </span>
          <span className="h-3 w-px bg-white/15" />
          {c.targets.map((b) => (
            <span key={b} className="h-[7px] w-[7px] rounded-full" style={{ background: TARGET[b].tint }} />
          ))}
          {c.targets.length > 1 ? "Moon & Mars analog" : TARGET[c.targets[0]].label}
        </div>
        {source === "sample" && (
          <span className="rounded-full border border-white/10 px-2 py-0.5 text-[10px] text-white/45" title="No search backend connected — showing the bundled sample candidates">
            Sample data
          </span>
        )}
      </div>

      <div className="mt-4" style={{ animation: "rise-in .6s var(--ease-out-expo) .03s both" }}>
        <div className="min-w-0">
          <h2 className="text-[26px] font-medium leading-[1.1] tracking-[-0.025em] text-white">{c.name}</h2>
          <p className="mt-1.5 text-[13px] text-white/55">{c.region}</p>
          <p className="mt-1 font-mono text-[11px] text-white/35">{formatCoord(c.lat, c.lon)}</p>
        </div>
      </div>

      <p className="mt-4 text-[14px] leading-relaxed text-white/75" style={{ animation: "rise-in .6s var(--ease-out-expo) .06s both" }}>
        {c.summary}
      </p>

      <Section title="Climate · NASA POWER" i={3}>
        <div className="grid grid-cols-2 gap-2">
          <Stat label="Mean temperature" value={k.meanTempC.toFixed(1)} unit="°C" note={ref.temp} />
          <Stat label="Coldest-month low" value={k.coldestMonthMinC.toFixed(1)} unit="°C" note={ref.cold} />
          <Stat label="Precipitation" value={Math.round(k.precipMmYr).toLocaleString()} unit="mm/yr" note={ref.precip} />
          <Stat label="Solar irradiance" value={k.solarKwhM2Day.toFixed(1)} unit="kWh/m²·day" note={ref.solar} />
        </div>
        <p className="mt-2 text-[10.5px] leading-relaxed text-white/30">Regional climatology on a ~50 km grid; local conditions vary.</p>
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

      <Section title="Where it breaks down" i={5}>
        <ul className="space-y-2">
          {c.breaks.map((b) => (
            <li key={b} className="flex gap-2.5 text-[13px] leading-snug text-white/55">
              <span className="mt-[9px] h-px w-2.5 shrink-0 bg-white/40" aria-hidden />
              {b}
            </li>
          ))}
        </ul>
      </Section>

      <p className="mt-7 border-t border-white/[0.07] pt-4 text-[10.5px] leading-relaxed text-white/35" style={{ animation: "rise-in .6s var(--ease-out-expo) .36s both" }}>
        Imagery: NASA HLS (Harmonized Landsat Sentinel-2) via GIBS, {c.imagery.date}.
        <br />
        Climate: NASA POWER long-term climatology.
      </p>
    </div>
  );
}

/** Right-third panel making the case for the selected candidate. */
export function EvidencePanel() {
  const { mode, results, active, query, source, searchFrom } = useUi();
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
        <Body c={c} index={active} total={results.length} target={query.target} source={source} />
      </div>
    </aside>
  );
}
