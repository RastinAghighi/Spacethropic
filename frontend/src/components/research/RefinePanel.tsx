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
  MEASURED_GEOLOGY,
  describeChange,
  limitsIn,
  matchProfile,
  passes,
  poolFor,
  sameFilters,
  targetValue,
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

/** `fields` lead each drawer; `more` waits behind a disclosure with the weights. `hidden` drawers
 * stay wired up but off the rail until their data exists. */
export const TABS: { id: Tab; label: string; icon: string; fields: NumKey[]; more: NumKey[]; dims: Dim[]; hidden?: boolean }[] = [
  { id: "terrain", label: "Terrain", icon: "M1.5 13.5l4.25-7.5 3 5 2-3 3.75 5.5z", fields: ["match", "slope", "flatGround", "elevation", "relief", "slopeMax", "heightRange", "roughness", "concavity"], more: [], dims: ["terrain"] },
  { id: "geology", label: "Geology", icon: "M8 1.75l5.75 4.5L8 14.25 2.25 6.25z M2.25 6.25h11.5 M6 6.25L8 14.25l2-8", fields: [], more: [], dims: ["geology"] },
  { id: "thermal", label: "Thermal", icon: "M8 2.25c.83 0 1.5.67 1.5 1.5v5.6a3 3 0 1 1-3 0v-5.6c0-.83.67-1.5 1.5-1.5z M8 7v4", fields: ["meanTemp", "coldMin", "hotMax", "dayNight", "airDayNight"], more: [], dims: ["thermal"] },
  { id: "weather", label: "Atmosphere", icon: "M4.75 12.5h6.5a2.75 2.75 0 0 0 .4-5.47A3.75 3.75 0 0 0 4.5 8a2.25 2.25 0 0 0 .25 4.5z", fields: ["solar", "wind", "humidity", "cloud", "dust", "dustConc", "pressure"], more: [], dims: ["sun"] },
];
const tabById = (id: Tab) => TABS.find((t) => t.id === id)!;

const AMBER = "#f3b453";
const CLOSE = "M4 4l8 8M12 4l-8 8";

function WeightControl({ dim, value }: { dim: Dim; value: Weight }) {
  const opts: { w: Weight; label: string }[] = [
    { w: 0, label: "Ignore" },
    { w: 1, label: "Normal" },
    { w: 2, label: "Priority" },
  ];
  return (
    <div>
      <p className="mb-2 text-[12.5px] text-white/75">{DIMS[dim].label} weight</p>
      <div role="radiogroup" aria-label={`${DIMS[dim].label} weight`} className="relative flex w-fit rounded-full bg-white/[0.04] p-[3px] ring-1 ring-white/[0.07]">
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

function GeologyPicker({ draft, c, q, tint, live }: { draft: Filters; c: Candidate; q: AnalogQuery; tint: string; live: boolean }) {
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
        {(live ? MEASURED_GEOLOGY : (Object.keys(GEOLOGY) as Geology[])).map((g) => {
          const on = draft.geology.includes(g);
          // None anywhere in the searched area: the limit could never be met
          const none = live && !!c.area && !c.area.materials[g] && !on;
          return (
            <button
              key={g}
              type="button"
              aria-pressed={on}
              title={none ? `${GEOLOGY[g].note}. None in the searched area yet.` : GEOLOGY[g].note}
              disabled={none}
              onClick={() => research.toggleGeology(g)}
              className={`rounded-xl border px-3 py-2 text-left transition-[background-color,border-color] duration-300 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/40 ${
                on ? "border-white/30 bg-white/[0.09]" : none ? "cursor-default border-white/[0.04] opacity-35" : "border-white/[0.07] bg-white/[0.02] hover:border-white/15"
              }`}
            >
              <span className="flex items-center justify-between gap-2">
                <span className={`truncate text-[12.5px] ${on ? "text-white" : "text-white/75"}`}>{GEOLOGY[g].label}</span>
                <span className="flex items-center gap-1">
                  {here.includes(g) && <span title="At this site" className="h-[6px] w-[6px] rounded-full bg-white/80" />}
                  {profile.geology.includes(g) && <span title="At the target" className="h-[7px] w-[7px] rounded-full" style={{ boxShadow: `inset 0 0 0 1.5px ${tint}` }} />}
                </span>
              </span>
            </button>
          );
        })}
      </div>
      {live && <p className="mt-3 text-[10.5px] leading-relaxed text-white/30">Dominant surface material over each cell, from the WRB 2006 world soil map at 0.02°.</p>}
    </>
  );
}

function Drawer({ tab, c, q, draft, applied, pool, live }: { tab: Tab; c: Candidate; q: AnalogQuery; draft: Filters; applied: Filters; pool: Candidate[]; live: boolean }) {
  const def = tabById(tab);
  const tint = BODY[q.target].tint;
  const field = (k: NumKey) => (
    <RangeField
      key={k}
      k={k}
      value={draft.ranges[k]}
      onChange={(r) => research.setRange(k, r)}
      tint={tint}
      target={targetValue(k, c, q)}
      dots={pool.map((s) => ({ id: s.id, name: s.name, v: FIELDS[k].get(s), pass: passes(s, draft), current: s.id === c.id }))}
    />
  );

  return (
    <div key={tab} style={{ animation: "rise-in .45s var(--ease-out-expo) both" }}>
      <section>
        {tab === "geology" && <Label className="mb-3">Require any of</Label>}
        <div className="space-y-4">
          {def.fields.map(field)}
          {tab === "geology" && <GeologyPicker draft={draft} c={c} q={q} tint={tint} live={live} />}
        </div>
      </section>

      {/* Weights only re-rank the bundled sample sites; live search ranks on terrain shape */}
      {def.dims.length > 0 && !live && (
        <section className="mt-6 space-y-3 border-t border-white/[0.06] pt-4">
          {def.dims.map((d) => (
            <WeightControl key={d} dim={d} value={draft.weights[d]} />
          ))}
          {def.dims.some((d) => draft.weights[d] !== applied.weights[d]) && <p className="text-[10.5px] text-white/35">Weights re-rank the candidates; they don&apos;t remove any.</p>}
        </section>
      )}
    </div>
  );
}

/** Left side of the site view: pull-out drawers of site data and the limits that steer the next search. */
export function RefinePanel() {
  const { mode, results, active, query, searchFrom, source } = useUi();
  const { drawer, draft, applied, hover } = useResearch();
  const { run, busy } = useRunSearch();
  const [shownTab, setShownTab] = useState<Tab>("terrain");
  if (drawer && drawer !== shownTab) setShownTab(drawer);

  const c = results[active];
  const shown = mode === "site" || mode === "diving" || mode === "surfacing" || (mode === "searching" && searchFrom === "site");
  if (!c || !query || !shown) return null;

  // Live results are the candidates on hand; the sample model ranks its whole bundled pool
  const pool = source === "live" ? results : poolFor(query);
  const passing = pool.filter((s) => passes(s, draft));
  // Live refines search every cell, not just these results, so none passing here is fine
  const blocked = !passing.length && source !== "live";
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
        className="fixed left-6 top-[72px] z-20"
        style={{ animation: mode === "diving" ? `rise-in .9s var(--ease-out-expo) ${DIVE.panel + 0.1}s both` : undefined }}
      >
        <div className="flex flex-col gap-0.5 rounded-[18px] border border-white/[0.08] bg-[rgb(10_11_14/0.6)] p-[3px] shadow-[0_30px_80px_-30px_rgb(0_0_0/0.9),inset_0_1px_0_rgb(255_255_255/0.05)] backdrop-blur-2xl backdrop-saturate-150">
          <p aria-hidden className="pb-1 pt-1.5 text-center text-[8.5px] font-medium uppercase tracking-[0.12em] text-white/35">
            Refine
          </p>
          {TABS.filter((t) => !t.hidden).map((t) => {
            const on = drawer === t.id;
            const n = limitsIn(t.id, draft);
            const short = shortTabs.has(t.id);
            const lit = hover === t.id && !on;
            return (
              <button
                key={t.id}
                type="button"
                aria-expanded={on}
                aria-controls="refine-drawer"
                onClick={() => research.toggle(t.id)}
                aria-label={short ? `${t.label}: this site falls short` : t.label}
                className={`group relative grid h-10 w-10 place-items-center rounded-[14px] transition-[background-color,color,box-shadow] duration-300 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/40 ${
                  on ? "bg-white text-black" : lit ? "bg-white/[0.1] text-white shadow-[0_0_0_1px_rgb(255_255_255/0.18)]" : "text-white/50 hover:bg-white/[0.06] hover:text-white"
                }`}
              >
                <Icon d={t.icon} size={16} strokeWidth={1.3} />
                {/* Name on hover, beside the rail */}
                <span
                  aria-hidden
                  className={`pointer-events-none absolute left-full ml-3 whitespace-nowrap rounded-lg border border-white/10 bg-[rgb(10_11_14/0.85)] px-2 py-1 text-[11.5px] text-white/85 opacity-0 backdrop-blur-xl transition-[opacity,transform] duration-200 ${
                    drawer ? "" : "group-hover:translate-x-0 group-hover:opacity-100 group-focus-visible:opacity-100"
                  } -translate-x-1`}
                >
                  {t.label}
                  {short && <span style={{ color: AMBER }}> · falls short</span>}
                </span>
                {short && <span aria-hidden className="absolute right-[7px] top-[7px] h-[4px] w-[4px] rounded-full" style={{ background: AMBER, boxShadow: `0 0 6px ${AMBER}` }} />}
                {n > 0 && (
                  <span
                    key={n}
                    className={`absolute -right-1 -top-1 grid h-[15px] min-w-[15px] place-items-center rounded-full px-1 text-[9px] font-semibold tabular-nums ring-2 ring-[rgb(10_11_14)] ${on ? "bg-black text-white" : "bg-white text-black"}`}
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
        className="fixed left-[84px] top-[72px] z-20 flex max-h-[calc(100vh-170px)] w-[var(--drawer-w)] flex-col"
        style={{
          opacity: open ? 1 : 0,
          transform: open ? "none" : "translateX(-14px) scale(0.985)",
          filter: open ? "none" : "blur(4px)",
          transformOrigin: "0 50%",
          pointerEvents: open ? "auto" : "none",
          transition: "opacity .35s ease, transform .55s var(--ease-out-expo), filter .4s ease",
        }}
      >
        <div className="flex min-h-0 flex-col overflow-hidden rounded-[22px] border border-white/[0.08] bg-[rgb(10_11_14/0.62)] shadow-[0_30px_80px_-30px_rgb(0_0_0/0.9),inset_0_1px_0_rgb(255_255_255/0.05)] backdrop-blur-2xl backdrop-saturate-150">
          <header className="flex items-start justify-between gap-3 px-5 pb-4 pt-5">
            <div className="min-w-0">
              <p className="text-[17px] font-medium tracking-[-0.015em] text-white">{tabById(shownTab).label}</p>
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
            <Drawer key={shownTab} tab={shownTab} c={c} q={query} draft={draft} applied={applied} pool={pool} live={source === "live"} />
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
                  {passing.length ? "pass" : blocked ? "pass · loosen a limit" : "here · refine searches every cell"}
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
                <FindButton onClick={refine} disabled={!dirty || blocked || busy} label="Refine search" />
              </div>
            </div>
          </footer>
        </div>
      </aside>
    </div>
  );
}
