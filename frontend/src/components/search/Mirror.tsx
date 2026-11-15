"use client";

import { useState } from "react";
import { BODY, formatLatLon, targetById, targetsFor } from "@/lib/catalog";
import type { AnalogTarget } from "@/lib/search";
import { useUi } from "@/lib/ui";
import { SearchDock } from "./SearchDock";
import { MirrorLens, type View } from "./MirrorLens";
import { BodyToggle, Chip, DiscoveryToggle, FindButton, Label, useRunSearch } from "./primitives";

const CUSTOM = "custom";

/** Concept 4: point at the place on the Moon or Mars, and Earth answers with its mirror. */
export function Mirror() {
  const { run, error } = useRunSearch();
  const { mode } = useUi();
  const [body, setBody] = useState<AnalogTarget>("moon");
  const [selected, setSelected] = useState("shackleton");
  const [pin, setPin] = useState<View | null>(null);
  const [touched, setTouched] = useState(false);
  const [discovery, setDiscovery] = useState(false);

  const sites = targetsFor(body);
  const target = selected === CUSTOM ? null : targetById(selected)!;
  const name = target ? target.name : `Point at ${formatLatLon(pin!.lat, pin!.lon)}`;
  const coords = target ? formatLatLon(target.lat, target.lon, 2) : formatLatLon(pin!.lat, pin!.lon, 2);
  const tint = BODY[body].tint;

  const switchBody = (b: AnalogTarget) => {
    setBody(b);
    setSelected(targetsFor(b)[0].id);
    setPin(null);
  };

  const submit = () =>
    run({
      text: `Earth's mirror of ${name}`,
      target: body,
      place: target?.id ?? `${body}:${pin!.lat.toFixed(3)},${pin!.lon.toFixed(3)}`,
      discovery,
    });

  const editor = (
    <div className="flex flex-col items-center gap-4 p-4 sm:flex-row sm:items-stretch sm:gap-6 sm:p-5">
      <div className="relative flex flex-col items-center">
        {/* Faint orbit ring framing the lens */}
        <div aria-hidden className="pointer-events-none absolute left-1/2 top-[104px] h-[236px] w-[236px] -translate-x-1/2 -translate-y-1/2 rounded-full border border-white/[0.05]" />
        <MirrorLens
          key={body}
          body={body}
          sites={sites}
          selected={selected}
          pin={pin}
          spinning={!touched && mode === "globe"}
          onSelect={(id) => {
            setTouched(true);
            setSelected(id);
          }}
          onPin={(p) => {
            setTouched(true);
            setPin(p);
            setSelected(CUSTOM);
          }}
        />
        <p className="mt-2 text-[10.5px] text-white/30">Drag to turn · click to drop a pin</p>
      </div>

      <div className="flex w-full min-w-0 flex-1 flex-col">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <Label>Mirror</Label>
            <p className="mt-1 text-[16px] font-medium tracking-[-0.015em] text-white/95">Where on {BODY[body].long}?</p>
          </div>
          <BodyToggle value={body} onChange={switchBody} />
        </div>

        <div key={selected + (pin ? `${pin.lat}${pin.lon}` : "")} className="mt-3 rounded-2xl border border-white/[0.07] bg-white/[0.025] px-3.5 py-3" style={{ animation: "rise-in .5s var(--ease-out-expo) both" }}>
          <div className="flex items-baseline justify-between gap-3">
            <p className="truncate text-[14px] font-medium text-white">{name}</p>
            <p className="shrink-0 font-mono text-[10.5px] text-white/40">{coords}</p>
          </div>
          <p className="mt-1 line-clamp-2 text-[12px] leading-snug text-white/50">
            {target ? target.summary : "A point you dropped. The search matches Earth against the terrain, thermal and surface profile of the cells around it."}
          </p>
          {target && <p className="mt-1.5 truncate text-[10.5px] text-white/30">{target.source}</p>}
        </div>

        <div className="mt-3 flex gap-1.5 overflow-x-auto py-0.5 [mask-image:linear-gradient(to_right,black_88%,transparent)] [scrollbar-width:none]">
          {sites.map((s) => (
            <Chip
              key={s.id}
              on={s.id === selected}
              onClick={() => {
                setTouched(true);
                setSelected(s.id);
              }}
            >
              {s.short}
            </Chip>
          ))}
        </div>

        <div className="mt-auto flex items-center justify-between gap-3 pt-4">
          <DiscoveryToggle on={discovery} onChange={setDiscovery} />
          <FindButton onClick={submit} label="Find Earth's mirror" />
        </div>
      </div>
    </div>
  );

  return (
    <SearchDock
      label="Mirror search"
      width={720}
      editor={editor}
      error={error}
      tint={tint}
      summary={
        <>
          Earth&apos;s mirror of <span className="text-white">{target ? target.short : name}</span>
          <span className="text-white/35"> · {BODY[body].label}</span>
        </>
      }
    />
  );
}
