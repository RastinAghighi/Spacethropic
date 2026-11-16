"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { BODY, formatLatLon, targetById, targetsFor, type Target } from "@/lib/catalog";
import type { AnalogTarget } from "@/lib/search";
import { useUi } from "@/lib/ui";
import { SearchDock } from "./SearchDock";
import { MirrorLens, type View } from "./MirrorLens";
import { BodyToggle, FindButton, useRunSearch } from "./primitives";

const CUSTOM = "custom";

function Chevron({ open }: { open: boolean }) {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden className="shrink-0 text-white/40 transition-transform duration-300" style={{ transform: open ? "rotate(180deg)" : "none" }}>
      <path d="M3 4.5L6 7.5l3-3" stroke="currentColor" strokeWidth="1.4" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

type Metrics = Record<string, number>;

/** The target's measured values at a point, from the search service (null while loading or offline). */
function useTargetMetrics(body: AnalogTarget, lat: number, lon: number) {
  const key = `${body}:${lat.toFixed(3)},${lon.toFixed(3)}`;
  const [got, setGot] = useState<{ key: string; m: Metrics | null } | null>(null);
  useEffect(() => {
    const ctl = new AbortController();
    fetch(`/api/target?body=${body}&lat=${lat}&lon=${lon}`, { signal: ctl.signal })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => setGot({ key, m: d?.metrics ?? null }))
      .catch((e) => e.name !== "AbortError" && setGot({ key, m: null }));
    return () => ctl.abort();
  }, [body, lat, lon, key]);
  return got?.key === key ? { loading: false, m: got.m } : { loading: true, m: null };
}

/** What the search will look for: the target's own measured terrain and surface temperatures. */
function Profile({ body, lat, lon }: { body: AnalogTarget; lat: number; lon: number }) {
  const { loading, m } = useTargetMetrics(body, lat, lon);
  const f = (v: number | undefined, d = 0) => (v === undefined ? "—" : v.toFixed(d).replace("-", "−"));
  const cells = [
    { label: "Slope", value: f(m?.slope, 1), unit: "°" },
    { label: "Relief", value: f(m?.relief), unit: "m" },
    { label: "Surface temp", value: f(m?.meanTemp), unit: "°C" },
    { label: "Day–night", value: f(m?.dayNight), unit: "°C" },
  ];
  return (
    <div className="grid grid-cols-4 gap-x-4" title={m ? "Measured at this point: LOLA / HRSC-MOLA terrain, Diviner / MCD surface temperatures" : undefined}>
      {cells.map((c, i) => (
        <div key={c.label} className="min-w-0">
          <p className="truncate text-[10px] uppercase tracking-[0.12em] text-white/35">{c.label}</p>
          {loading ? (
            <span className="mt-1.5 block h-[15px] w-12 animate-pulse rounded bg-white/[0.08]" />
          ) : (
            <p className="mt-1 truncate text-[15px] font-medium tracking-[-0.01em] text-white tabular-nums" style={{ animation: `rise-in .5s var(--ease-out-expo) ${i * 0.04}s both` }}>
              {c.value}
              {c.value !== "—" && <span className="ml-0.5 text-[10.5px] font-normal text-white/40">{c.unit}</span>}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

/** Grouped list of named places. Hovering a row turns the lens to it. */
function PlaceList({ sites, selected, tint, onPick, onPreview, onClose }: { sites: Target[]; selected: string; tint: string; onPick: (id: string) => void; onPreview: (id: string | null) => void; onClose: () => void }) {
  const list = useRef<HTMLDivElement>(null);
  const [cursor, setCursor] = useState(() => Math.max(0, sites.findIndex((s) => s.id === selected)));

  useEffect(() => {
    list.current?.querySelector<HTMLElement>('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
    list.current?.focus();
  }, []);

  const onKey = (e: React.KeyboardEvent) => {
    const step = { ArrowDown: 1, ArrowUp: -1 }[e.key];
    if (step) {
      e.preventDefault();
      const i = (cursor + step + sites.length) % sites.length;
      setCursor(i);
      onPreview(sites[i].id);
      list.current?.querySelectorAll<HTMLElement>("[role=option]")[i]?.scrollIntoView({ block: "nearest" });
    }
    if (e.key === "Enter") onPick(sites[cursor].id);
    if (e.key === "Escape") {
      e.stopPropagation();
      onClose();
    }
  };

  return (
    <div
      ref={list}
      role="listbox"
      tabIndex={-1}
      aria-label="Places"
      onKeyDown={onKey}
      onPointerLeave={() => onPreview(null)}
      className="absolute inset-0 overflow-y-auto overscroll-contain outline-none [mask-image:linear-gradient(to_bottom,black_88%,transparent)] [scrollbar-width:none]"
      style={{ animation: "rise-in .35s var(--ease-out-expo) both" }}
    >
      {sites.map((s, i) => (
        <div key={s.id}>
          {s.group !== sites[i - 1]?.group && (
            <p className="px-2.5 pb-1 pt-3 text-[10px] font-medium uppercase tracking-[0.12em] text-white/35 first:pt-0">{s.group}</p>
          )}
          <button
            type="button"
            role="option"
            aria-selected={s.id === selected}
            onClick={() => onPick(s.id)}
            onPointerEnter={() => {
              setCursor(i);
              onPreview(s.id);
            }}
            className={`flex w-full items-center justify-between gap-3 rounded-lg px-2.5 py-2 text-left transition-colors duration-150 ${i === cursor ? "bg-white/[0.08]" : ""}`}
          >
            <span className="flex min-w-0 items-center gap-2">
              <span className="h-1.5 w-1.5 shrink-0 rounded-full transition-opacity" style={{ background: tint, opacity: s.id === selected ? 1 : 0 }} />
              <span className={`truncate text-[13.5px] ${s.id === selected ? "text-white" : "text-white/75"}`}>{s.name}</span>
            </span>
            <span className="shrink-0 font-mono text-[10.5px] tabular-nums text-white/30">{formatLatLon(s.lat, s.lon)}</span>
          </button>
        </div>
      ))}
    </div>
  );
}

/** Pick a place on the Moon or Mars; Earth answers with its closest match. */
export function Mirror() {
  const { run, error } = useRunSearch();
  const { mode } = useUi();
  const [body, setBody] = useState<AnalogTarget>("moon");
  const [selected, setSelected] = useState("shackleton");
  const [pin, setPin] = useState<View | null>(null);
  const [touched, setTouched] = useState(false);
  const [picking, setPicking] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const card = useRef<HTMLDivElement>(null);

  const sites = useMemo(() => targetsFor(body), [body]);
  const target = selected === CUSTOM ? null : targetById(selected)!;
  const place = target?.id ?? `${body}:${pin!.lat.toFixed(3)},${pin!.lon.toFixed(3)}`;
  const name = target ? target.name : "Dropped pin";
  const tint = BODY[body].tint;

  // The list closes on a click anywhere outside the card.
  useEffect(() => {
    if (!picking) return;
    const onDown = (e: PointerEvent) => {
      if (!card.current?.contains(e.target as Node)) setPicking(false);
    };
    window.addEventListener("pointerdown", onDown, true);
    return () => window.removeEventListener("pointerdown", onDown, true);
  }, [picking]);

  const choose = (id: string) => {
    setTouched(true);
    setSelected(id);
    setPicking(false);
    setPreview(null);
  };

  const switchBody = (b: AnalogTarget) => {
    setBody(b);
    setSelected(targetsFor(b)[0].id);
    setPin(null);
    setPicking(false);
  };

  const submit = () => run({ text: `Earth's mirror of ${name}`, target: body, place, step: "Physical match" });

  const editor = (
    <div ref={card} className="flex flex-col items-center gap-4 p-4 sm:flex-row sm:items-stretch sm:gap-6 sm:p-5">
      <div className="flex flex-col items-center justify-center">
        <MirrorLens
          key={body}
          body={body}
          size={180}
          sites={sites}
          selected={preview ?? selected}
          pin={pin}
          spinning={!touched && mode === "globe"}
          onSelect={choose}
          onPin={(p) => {
            setTouched(true);
            setPin(p);
            setSelected(CUSTOM);
            setPicking(false);
          }}
        />
        <p className="mt-2 text-[10.5px] text-white/30">Drag to turn · scroll to zoom · click to pin</p>
      </div>

      <div className="flex w-full min-w-0 flex-1 flex-col">
        <div className="flex items-center justify-between gap-3">
          <p className="text-[12.5px] text-white/45">Pick a place on {BODY[body].long}</p>
          <BodyToggle value={body} onChange={switchBody} />
        </div>

        <div className="relative mt-2 flex-1" style={{ minHeight: picking ? 300 : 0, transition: "min-height .55s var(--ease-out-expo)" }}>
          <div aria-hidden={picking} inert={picking} style={{ opacity: picking ? 0 : 1, transition: "opacity .2s ease" }}>
            <button
              type="button"
              onClick={() => {
                setTouched(true);
                setPicking(true);
              }}
              aria-haspopup="listbox"
              aria-expanded={picking}
              className="group -mx-2.5 flex w-[calc(100%+20px)] items-center justify-between gap-3 rounded-xl px-2.5 py-1.5 text-left transition-colors hover:bg-white/[0.05] focus-visible:bg-white/[0.05] focus-visible:outline-none"
            >
              <span key={place} className="truncate text-[20px] font-medium tracking-[-0.02em] text-white" style={{ animation: "rise-in .45s var(--ease-out-expo) both" }}>
                {name}
              </span>
              <span className="flex items-center gap-1.5 text-[11.5px] text-white/40 transition-colors group-hover:text-white/70">
                {sites.length} places
                <Chevron open={picking} />
              </span>
            </button>
            <p className="mt-0.5 flex items-center gap-2 text-[11px] text-white/35">
              <span className="font-mono">{target ? formatLatLon(target.lat, target.lon, 2) : formatLatLon(pin!.lat, pin!.lon, 2)}</span>
              <span className="h-3 w-px bg-white/10" />
              <span className="truncate">{target ? target.group : "Profile estimated from latitude"}</span>
            </p>
            <div className="mt-4 border-t border-white/[0.06] pt-3">
              <Profile body={body} lat={target ? target.lat : pin!.lat} lon={target ? target.lon : pin!.lon} />
            </div>
          </div>
          {picking && <PlaceList sites={sites} selected={selected} tint={tint} onPick={choose} onPreview={setPreview} onClose={() => setPicking(false)} />}
        </div>

        <div className="mt-4 flex items-center justify-end">
          <FindButton onClick={submit} label="Find Earth's mirror" />
        </div>
      </div>
    </div>
  );

  return <SearchDock label="Mirror search" width={660} editor={editor} error={error} tint={tint} />;
}
