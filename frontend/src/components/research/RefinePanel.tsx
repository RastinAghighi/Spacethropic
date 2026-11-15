"use client";

import { useState } from "react";
import { DIVE, useUi } from "@/lib/ui";
import { research, useResearch } from "@/lib/research";
import { BODY } from "@/lib/catalog";
import type { Candidate } from "@/lib/candidates";
import type { AnalogQuery } from "@/lib/search";
import {
  DIMS,
  FIELDS,
  GEOLOGY,
  describeChange,
  formatField,
  limitsIn,
  matchProfile,
  passes,
  poolFor,
  sameFilters,
  targetOf,
  traits,
  type Dim,
  type Filters,
  type Geology,
  type NumKey,
  type Tab,
  type Weight,
} from "@/lib/profile";
import { FindButton, Icon, Label, useRunSearch } from "../search/primitives";
import { RangeField } from "./RangeField";

export const TABS: { id: Tab; label: string; icon: string; fields: NumKey[]; dims: Dim[] }[] = [
  { id: "terrain", label: "Terrain", icon: "M1.5 13.5l4.25-7.5 3 5 2-3 3.75 5.5z", fields: ["slope", "roughness", "elevation"], dims: ["terrain"] },
  { id: "geology", label: "Geology", icon: "M8 1.75l5.75 4.5L8 14.25 2.25 6.25z M2.25 6.25h11.5 M6 6.25L8 14.25l2-8", fields: [], dims: ["geology"] },
  { id: "thermal", label: "Thermal", icon: "M8 2.25c.83 0 1.5.67 1.5 1.5v5.6a3 3 0 1 1-3 0v-5.6c0-.83.67-1.5 1.5-1.5z M8 7v4", fields: ["meanTemp", "coldMin"], dims: ["thermal"] },
  { id: "weather", label: "Weather", icon: "M4.75 12.5h6.5a2.75 2.75 0 0 0 .4-5.47A3.75 3.75 0 0 0 4.5 8a2.25 2.25 0 0 0 .25 4.5z", fields: ["precip", "humidity", "wind", "solar"], dims: ["aridity", "sun"] },
  { id: "access", label: "Access", icon: "M8 14.25s4.5-4.06 4.5-7.75a4.5 4.5 0 0 0-9 0c0 3.69 4.5 7.75 4.5 7.75z M8 8.25a1.75 1.75 0 1 0 0-3.5 1.75 1.75 0 0 0 0 3.5z", fields: ["roadKm"], dims: [] },
];
const tabById = (id: Tab) => TABS.find((t) => t.id === id)!;

const AMBER = "#f3b453";
const CLOSE = "M4 4l8 8M12 4l-8 8";

function Tile({ label, value, unit, note }: { label: string; value: string; unit?: string; note?: string }) {
  return (
    <div className="rounded-xl border border-white/[0.07] bg-white/[0.025] px-3 py-2.5">
      <p className="text-[10.5px] text-white/45">{label}</p>
      <p className="mt-1 truncate text-[17px] font-medium leading-none tracking-[-0.02em] text-white tabular-nums">
        {value}
        {unit && <span className="ml-1 text-[11px] font-normal tracking-normal text-white/45">{unit}</span>}
      </p>
      {note && <p className="mt-1.5 truncate text-[10px] text-white/35">{note}</p>}
    </div>
  );
}

/** Field value as tile parts: "−14.4" + "°C". */
function parts(k: NumKey, v: number) {
  const s = formatField(k, v);
  const unit = FIELDS[k].unit;
  return unit === "°" ? { value: s } : { value: s.slice(0, -unit.length - 1), unit };
}

function WeightControl({ dim, value }: { dim: Dim; value: Weight }) {
  const opts: { w: Weight; label: string }[] = [
    { w: 0, label: "Ignore" },
    { w: 1, label: "Normal" },
    { w: 2, label: "Priority" },
  ];
  return (
    <div className="flex items-center justify-between gap-3">
      <p className="text-[12.5px] text-white/70">{DIMS[dim].label} in the match</p>
      <div role="radiogroup" aria-label={`${DIMS[dim].label} weight`} className="relative flex rounded-full bg-white/[0.04] p-[3px] ring-1 ring-white/[0.07]">
        <span
          aria-hidden
          className="absolute bottom-[3px] left-[3px] top-[3px] w-[64px] rounded-full bg-white/[0.1] shadow-[inset_0_1px_0_rgb(255_255_255/0.08)]"
          style={{ transform: `translateX(${value * 64}px)`, transition: "transform .45s var(--ease-out-expo)" }}
        />
        {opts.map((o) => (
          <button
            key={o.w}
            type="button"
            role="radio"
            aria-checked={value === o.w}
            onClick={() => research.setWeight(dim, o.w)}
            className={`relative z-10 h-6 w-16 rounded-full text-[11px] transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/40 ${
              value === o.w ? "text-white" : "text-white/40 hover:text-white/75"
            }`}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function Readouts({ tab, c, q }: { tab: Tab; c: Candidate; q: AnalogQuery }) {
  const { profile, short } = targetOf(q);
  const t = traits(c);
  const k = c.climate;
  const tile = (key: NumKey, note?: string, label = FIELDS[key].label) => <Tile label={label} {...parts(key, FIELDS[key].get(c))} note={note} />;
  const at = (v: string) => `${short}: ${v}`;
  switch (tab) {
    case "terrain":
      return (
        <div className="grid grid-cols-2 gap-2">
          {tile("slope", at(formatField("slope", profile.slope)), "Typical slope")}
          {tile("roughness", "RMS height at 30 m")}
          {tile("elevation", "Above sea level")}
          <Tile label="Rock" value={t.geology.map((g) => GEOLOGY[g].label).join(" · ")} note="Dominant units" />
        </div>
      );
    case "geology":
      return null;
    case "thermal":
      return (
        <div className="grid grid-cols-2 gap-2">
          {tile("meanTemp", at(formatField("meanTemp", profile.meanTemp)))}
          {tile("coldMin", "Night-time extreme")}
          <Tile label="Hottest-month high" {...parts("meanTemp", k.hottestMonthMaxC)} note="Daytime extreme" />
          <Tile label="Annual swing" value={(k.hottestMonthMaxC - k.coldestMonthMinC).toFixed(0)} unit="°C" note="High minus low" />
        </div>
      );
    case "weather":
      return (
        <div className="grid grid-cols-2 gap-2">
          {tile("precip", at("none"))}
          {tile("humidity", "Relative, annual mean")}
          {tile("wind", "At 10 m")}
          {tile("solar", at(formatField("solar", profile.solar)))}
        </div>
      );
    case "access":
      return (
        <div className="grid grid-cols-2 gap-2">
          {tile("roadKm", "Straight-line distance")}
          <Tile label="Protected area" value={t.protectedArea ? "Yes" : "No"} note={t.protectedArea ? "Permits needed" : "Open land"} />
          <div className="col-span-2">
            <Tile label="Field season" value={t.access.split(";")[0]} note={t.access.split(";")[1]?.trim() || "No seasonal restrictions noted"} />
          </div>
        </div>
      );
  }
}

function GeologyPicker({ draft, c, q, tint }: { draft: Filters; c: Candidate; q: AnalogQuery; tint: string }) {
  const { profile } = targetOf(q);
  const here = traits(c).geology;
  return (
    <>
      <p className="-mt-1 mb-2.5 flex items-center gap-3 text-[10.5px] text-white/40">
        <span className="flex items-center gap-1.5">
          <span className="h-[6px] w-[6px] rounded-full bg-white/80" />
          {c.name}
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-[7px] w-[7px] rounded-full" style={{ boxShadow: `inset 0 0 0 1.5px ${tint}` }} />
          {targetOf(q).short}
        </span>
      </p>
      <div className="grid grid-cols-2 gap-1.5">
        {(Object.keys(GEOLOGY) as Geology[]).map((g) => {
          const on = draft.geology.includes(g);
          return (
            <button
              key={g}
              type="button"
              aria-pressed={on}
              onClick={() => research.toggleGeology(g)}
              className={`rounded-xl border px-3 py-2.5 text-left transition-[background-color,border-color] duration-300 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/40 ${
                on ? "border-white/30 bg-white/[0.09]" : "border-white/[0.07] bg-white/[0.02] hover:border-white/15"
              }`}
            >
              <span className="flex items-center justify-between gap-2">
                <span className={`text-[12.5px] ${on ? "text-white" : "text-white/75"}`}>{GEOLOGY[g].label}</span>
                <span className="flex items-center gap-1">
                  {here.includes(g) && <span title="At this site" className="h-[6px] w-[6px] rounded-full bg-white/80" />}
                  {profile.geology.includes(g) && <span title="At the target" className="h-[7px] w-[7px] rounded-full" style={{ boxShadow: `inset 0 0 0 1.5px ${tint}` }} />}
                </span>
              </span>
              <span className="mt-0.5 block text-[10.5px] leading-snug text-white/35">{GEOLOGY[g].note}</span>
            </button>
          );
        })}
      </div>
    </>
  );
}

function Toggle({ on, onChange, label, note }: { on: boolean; onChange: (v: boolean) => void; label: string; note: string }) {
  return (
    <button type="button" role="switch" aria-checked={on} onClick={() => onChange(!on)} className="flex w-full items-center justify-between gap-3 text-left focus-visible:outline-none">
      <span>
        <span className="block text-[12.5px] text-white/70">{label}</span>
        <span className="block text-[10.5px] text-white/35">{note}</span>
      </span>
      <span className="relative h-[18px] w-[30px] shrink-0 rounded-full transition-colors duration-300" style={{ background: on ? "rgb(255 255 255 / 0.85)" : "rgb(255 255 255 / 0.1)" }}>
        <span
          className="absolute left-[2px] top-[2px] h-[14px] w-[14px] rounded-full shadow-[0_1px_3px_rgb(0_0_0/0.4)]"
          style={{ background: on ? "#0b0c10" : "rgb(255 255 255 / 0.7)", transform: on ? "translateX(12px)" : "none", transition: "transform .4s var(--ease-out-expo), background-color .3s" }}
        />
      </span>
    </button>
  );
}

function Drawer({ tab, c, q, draft, applied }: { tab: Tab; c: Candidate; q: AnalogQuery; draft: Filters; applied: Filters }) {
  const def = tabById(tab);
  const { profile, short, name } = targetOf(q);
  const tint = BODY[q.target].tint;
  const pool = poolFor(q);
  const gaps = matchProfile(c, q).filter((m) => m.gap && def.dims.includes(m.dim));

  // A target value no Earth surface reaches: say so, and name the closest candidate.
  const thermalNote = (() => {
    if (tab !== "thermal" || profile.meanTemp >= FIELDS.meanTemp.min) return null;
    const best = [...pool].sort((a, b) => a.climate.meanTempC - b.climate.meanTempC)[0];
    return `No surface on Earth averages ${formatField("meanTemp", profile.meanTemp)}. The coldest candidate here is ${best.name} at ${formatField("meanTemp", best.climate.meanTempC)}, so thermal is always a gap for ${short}.`;
  })();

  return (
    <div key={tab} style={{ animation: "rise-in .45s var(--ease-out-expo) both" }}>
      <section>
        <Label className="mb-2">At {c.name}</Label>
        {tab === "geology" ? (
          <p className="text-[13px] leading-snug text-white/75">
            {traits(c)
              .geology.map((g) => GEOLOGY[g].label)
              .join(" and ")}
            <span className="text-white/40">
              {" "}
              · {name} is {profile.geology.map((g) => GEOLOGY[g].label.toLowerCase()).join(" and ")}
            </span>
          </p>
        ) : (
          <Readouts tab={tab} c={c} q={q} />
        )}
      </section>

      {gaps.map((g) => (
        <div key={g.dim} className="mt-3 flex gap-2.5 rounded-xl border px-3 py-2.5 text-[12px] leading-snug" style={{ borderColor: `${AMBER}33`, background: `${AMBER}0d`, color: "rgb(255 255 255 / 0.75)" }}>
          <span className="mt-[5px] h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: AMBER }} />
          <span>
            <span className="font-medium" style={{ color: AMBER }}>
              {DIMS[g.dim].label} falls short.{" "}
            </span>
            {g.gap}
          </span>
        </div>
      ))}
      {thermalNote && <p className="mt-3 text-[11.5px] leading-relaxed text-white/45">{thermalNote}</p>}

      <section className="mt-6">
        <div className="mb-3 flex items-baseline justify-between">
          <Label>{tab === "geology" ? "Require any of" : "Limits"}</Label>
          {tab !== "geology" && <span className="text-[10.5px] text-white/30">Dots are candidates · drag to limit</span>}
        </div>
        <div className="space-y-5">
          {def.fields.map((k) => (
            <RangeField
              key={k}
              k={k}
              value={draft.ranges[k]}
              onChange={(r) => research.setRange(k, r)}
              tint={tint}
              target={FIELDS[k].target?.(profile)}
              dots={pool.map((s) => ({ id: s.id, name: s.name, v: FIELDS[k].get(s), pass: passes(s, draft), current: s.id === c.id }))}
            />
          ))}
          {tab === "geology" && <GeologyPicker draft={draft} c={c} q={q} tint={tint} />}
          {tab === "access" && <Toggle on={draft.excludeProtected} onChange={research.setProtected} label="Exclude protected areas" note="Parks, reserves and heritage sites need permits" />}
        </div>
      </section>

      {def.dims.length > 0 && (
        <section className="mt-6">
          <Label className="mb-3">Weight</Label>
          <div className="space-y-2.5">
            {def.dims.map((d) => (
              <WeightControl key={d} dim={d} value={draft.weights[d]} />
            ))}
          </div>
          {def.dims.some((d) => draft.weights[d] !== applied.weights[d]) && (
            <p className="mt-2 text-[10.5px] text-white/35">Weights re-rank the candidates; they don&apos;t remove any.</p>
          )}
        </section>
      )}
    </div>
  );
}

/** Left side of the site view: pull-out drawers of site data and the limits that steer the next search. */
export function RefinePanel() {
  const { mode, results, active, query, searchFrom } = useUi();
  const { drawer, draft, applied } = useResearch();
  const { run, busy } = useRunSearch();
  const [shownTab, setShownTab] = useState<Tab>("terrain");
  if (drawer && drawer !== shownTab) setShownTab(drawer);

  const c = results[active];
  const shown = mode === "site" || mode === "diving" || mode === "surfacing" || (mode === "searching" && searchFrom === "site");
  if (!c || !query || !shown) return null;

  const pool = poolFor(query);
  const passing = pool.filter((s) => passes(s, draft));
  const dirty = !sameFilters(draft, applied);
  const shortTabs = new Set(matchProfile(c, query).flatMap((m) => (m.gap && applied.weights[m.dim] ? [DIMS[m.dim].tab] : [])));
  const open = drawer !== null && mode !== "surfacing";
  const leaving = mode === "surfacing";

  const refine = () =>
    run({
      ...query,
      filters: draft,
      step: describeChange(applied, draft),
    });

  return (
    <div className="hidden md:block" style={{ opacity: leaving ? 0 : 1, transition: "opacity .35s ease" }}>
      {/* Rail */}
      <nav
        aria-label="Refine"
        className="fixed left-5 top-24 z-20 sm:left-7"
        style={{ animation: mode === "diving" ? `rise-in .9s var(--ease-out-expo) ${DIVE.panel + 0.1}s both` : undefined }}
      >
        <div className="flex flex-col gap-1 rounded-[20px] border border-white/[0.09] bg-[rgb(10_11_14/0.62)] p-1.5 shadow-[0_30px_80px_-30px_rgb(0_0_0/0.9),inset_0_1px_0_rgb(255_255_255/0.05)] backdrop-blur-2xl backdrop-saturate-150">
          {TABS.map((t) => {
            const on = drawer === t.id;
            const n = limitsIn(t.id, draft);
            const short = shortTabs.has(t.id);
            return (
              <button
                key={t.id}
                type="button"
                aria-expanded={on}
                aria-controls="refine-drawer"
                onClick={() => research.toggle(t.id)}
                title={short ? `${t.label}: this site falls short` : t.label}
                className={`relative flex h-[54px] w-[54px] flex-col items-center justify-center gap-1 rounded-[14px] transition-[background-color,color] duration-300 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/40 ${
                  on ? "bg-white text-black" : "text-white/55 hover:bg-white/[0.06] hover:text-white"
                }`}
              >
                <Icon d={t.icon} size={17} strokeWidth={1.3} />
                <span className="text-[9.5px] font-medium tracking-[0.02em]">{t.label}</span>
                {short && <span aria-hidden className="absolute left-2 top-2 h-[5px] w-[5px] rounded-full" style={{ background: AMBER, boxShadow: `0 0 6px ${AMBER}` }} />}
                {n > 0 && (
                  <span
                    key={n}
                    className={`absolute right-1 top-1 grid h-4 min-w-4 place-items-center rounded-full px-1 text-[9px] font-semibold tabular-nums ${on ? "bg-black text-white" : "bg-white text-black"}`}
                    style={{ animation: "rise-in .35s var(--ease-out-expo) both" }}
                  >
                    {n}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </nav>

      {/* Drawer */}
      <aside
        id="refine-drawer"
        aria-label={`${tabById(shownTab).label} refine`}
        aria-hidden={!open}
        inert={!open}
        className="fixed left-[100px] top-24 z-20 flex max-h-[calc(100vh-13rem)] w-[min(360px,calc(100vw-var(--panel-space)-140px))] flex-col sm:left-[108px]"
        style={{
          opacity: open ? 1 : 0,
          transform: open ? "none" : "translateX(-14px) scale(0.985)",
          filter: open ? "none" : "blur(4px)",
          transformOrigin: "0 50%",
          pointerEvents: open ? "auto" : "none",
          transition: "opacity .35s ease, transform .55s var(--ease-out-expo), filter .4s ease",
        }}
      >
        <div className="flex min-h-0 flex-col overflow-hidden rounded-[22px] border border-white/[0.09] bg-[rgb(10_11_14/0.7)] shadow-[0_30px_80px_-30px_rgb(0_0_0/0.9),inset_0_1px_0_rgb(255_255_255/0.05)] backdrop-blur-2xl backdrop-saturate-150">
          <header className="flex items-start justify-between gap-3 px-5 pb-3 pt-5">
            <div className="min-w-0">
              <p className="text-[17px] font-medium tracking-[-0.015em] text-white">{tabById(shownTab).label}</p>
              <p className="mt-0.5 truncate text-[11.5px] text-white/40">
                {c.name} against {targetOf(query).short}
              </p>
            </div>
            <button
              type="button"
              onClick={() => research.open(null)}
              aria-label="Close"
              className="-mr-1.5 grid h-7 w-7 shrink-0 place-items-center rounded-full text-white/45 transition-colors hover:bg-white/10 hover:text-white focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/40"
            >
              <Icon d={CLOSE} size={12} strokeWidth={1.5} />
            </button>
          </header>

          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 pb-5 [scrollbar-width:thin]">
            <Drawer tab={shownTab} c={c} q={query} draft={draft} applied={applied} />
          </div>

          {/* Live consequence of the draft, and the step that runs it */}
          <footer className="border-t border-white/[0.07] bg-black/20 px-5 py-3.5">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="flex gap-[3px]" aria-hidden>
                  {pool.map((s) => (
                    <span
                      key={s.id}
                      title={s.name}
                      className="h-[5px] w-3 rounded-full transition-colors duration-300"
                      style={{ background: passes(s, draft) ? "rgb(255 255 255 / 0.85)" : "rgb(255 255 255 / 0.12)" }}
                    />
                  ))}
                </div>
                <p className="mt-1.5 text-[11.5px] tabular-nums text-white/55" aria-live="polite">
                  <span className={passing.length ? "text-white" : ""} style={passing.length ? undefined : { color: AMBER }}>
                    {passing.length} of {pool.length}
                  </span>{" "}
                  {passing.length ? "pass" : "pass · loosen a limit"}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                {dirty && (
                  <button
                    type="button"
                    onClick={research.revert}
                    className="h-9 rounded-full px-3 text-[12px] text-white/50 transition-colors hover:text-white focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/40"
                  >
                    Undo
                  </button>
                )}
                <FindButton onClick={refine} disabled={!dirty || !passing.length || busy} label="Refine search" />
              </div>
            </div>
          </footer>
        </div>
      </aside>
    </div>
  );
}
