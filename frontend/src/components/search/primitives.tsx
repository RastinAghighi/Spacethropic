"use client";

import { useRef, useState } from "react";
import { findCandidates, type AnalogQuery, type AnalogTarget } from "@/lib/search";
import { ui, useUi } from "@/lib/ui";
import { BODY } from "@/lib/catalog";
import { imageUrl, thumbUrl, type Candidate } from "@/lib/candidates";

export function Icon({ d, size = 16, className, strokeWidth = 1.3 }: { d: string; size?: number; className?: string; strokeWidth?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" aria-hidden className={`shrink-0 ${className ?? ""}`}>
      <path d={d} stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/**
 * Loading bar that fills as the search moves through its stages. Each stage sets where the bar
 * is heading; a long ease-out creeps toward it, so it keeps moving while a stage runs.
 */
export function LoadingBar({ className }: { className?: string }) {
  const { progress } = useUi();
  const done = progress >= 1;
  return (
    <span aria-hidden className={`relative block h-[3px] overflow-hidden rounded-full bg-white/[0.1] ${className ?? ""}`}>
      <span
        className="load-fill absolute inset-y-0 left-0 rounded-full bg-white shadow-[0_0_8px_rgb(255_255_255/0.6)]"
        style={{ width: `${progress * 100}%`, transition: `width ${done ? ".25s ease-out" : "4s cubic-bezier(.08,.7,.2,1)"}` }}
      />
    </span>
  );
}

export function ArrowRight({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 14 14" fill="none" aria-hidden className="shrink-0">
      <path d="M2.5 7h9M7.75 3.25L11.5 7l-3.75 3.75" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function FindButton({ onClick, disabled, label = "Find analogs", tabIndex }: { onClick: () => void; disabled?: boolean; label?: string; tabIndex?: number }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      tabIndex={tabIndex}
      className={`group flex h-9 shrink-0 items-center gap-2 rounded-full pl-4 pr-3.5 text-[13px] font-medium transition-all duration-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/50 focus-visible:ring-offset-2 focus-visible:ring-offset-black ${
        disabled
          ? "bg-white/[0.06] text-white/25"
          : "bg-white text-black shadow-[0_0_24px_-4px_rgb(255_255_255/0.45)] hover:shadow-[0_0_30px_-2px_rgb(255_255_255/0.55)] active:scale-[0.97]"
      }`}
    >
      {label}
      <span className="transition-transform duration-300 group-hover:translate-x-0.5">
        <ArrowRight />
      </span>
    </button>
  );
}

/** Moon / Mars segmented control with a sliding thumb. */
export function BodyToggle({ value, onChange, tabIndex }: { value: AnalogTarget; onChange: (b: AnalogTarget) => void; tabIndex?: number }) {
  const bodies: AnalogTarget[] = ["moon", "mars"];
  const i = bodies.indexOf(value);
  return (
    <div role="radiogroup" aria-label="Analog for" className="relative flex shrink-0 rounded-full bg-white/[0.04] p-[3px] ring-1 ring-white/[0.07]">
      <span
        aria-hidden
        className="absolute bottom-[3px] left-[3px] top-[3px] w-[calc(50%-3px)] rounded-full bg-white/[0.09] shadow-[inset_0_1px_0_rgb(255_255_255/0.08)]"
        style={{ transform: `translateX(${i * 100}%)`, transition: "transform .45s var(--ease-out-expo)" }}
      />
      {bodies.map((b) => (
        <button
          key={b}
          type="button"
          role="radio"
          tabIndex={tabIndex}
          aria-checked={value === b}
          onClick={() => onChange(b)}
          className={`relative z-10 flex h-7 w-[72px] items-center justify-center gap-1.5 rounded-full text-[12.5px] transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/40 ${
            value === b ? "text-white" : "text-white/45 hover:text-white/75"
          }`}
        >
          <span className="h-[7px] w-[7px] rounded-full" style={{ background: BODY[b].tint, opacity: value === b ? 1 : 0.55 }} />
          {BODY[b].label}
        </button>
      ))}
    </div>
  );
}

/** Toggleable pill. */
export function Chip({
  on,
  onClick,
  children,
  tint,
  tabIndex,
  title,
}: {
  on: boolean;
  onClick: () => void;
  children: React.ReactNode;
  tint?: string;
  tabIndex?: number;
  title?: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      tabIndex={tabIndex}
      title={title}
      className={`flex h-7 shrink-0 items-center gap-1.5 rounded-full border px-3 text-[12px] transition-[color,background-color,border-color,box-shadow] duration-300 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/40 ${
        on
          ? "border-white/25 bg-white/[0.09] text-white shadow-[inset_0_1px_0_rgb(255_255_255/0.08)]"
          : "border-white/[0.07] bg-white/[0.02] text-white/50 hover:border-white/15 hover:text-white/80"
      }`}
    >
      {tint && <span className="h-[6px] w-[6px] rounded-full transition-opacity" style={{ background: tint, opacity: on ? 1 : 0.45 }} />}
      {children}
    </button>
  );
}

/** "Hide well-known analogs" switch. */
export function DiscoveryToggle({ on, onChange, tabIndex }: { on: boolean; onChange: (v: boolean) => void; tabIndex?: number }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      tabIndex={tabIndex}
      onClick={() => onChange(!on)}
      title="Hide famous, well-studied analog sites to surface new candidates"
      className="group flex h-7 shrink-0 items-center gap-2 rounded-full pl-1 pr-1 text-[12px] text-white/50 transition-colors hover:text-white/80 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/40"
    >
      <span
        className="relative h-[18px] w-[30px] rounded-full transition-colors duration-300"
        style={{ background: on ? "rgb(255 255 255 / 0.85)" : "rgb(255 255 255 / 0.1)" }}
      >
        <span
          className="absolute top-[2px] h-[14px] w-[14px] rounded-full shadow-[0_1px_3px_rgb(0_0_0/0.4)]"
          style={{
            left: 2,
            background: on ? "#0b0c10" : "rgb(255 255 255 / 0.7)",
            transform: on ? "translateX(12px)" : "none",
            transition: "transform .4s var(--ease-out-expo), background-color .3s",
          }}
        />
      </span>
      <span className={on ? "text-white/85" : undefined}>Unexplored only</span>
    </button>
  );
}

export function Label({ children, className }: { children: React.ReactNode; className?: string }) {
  return <p className={`text-[10px] font-medium uppercase tracking-[0.12em] text-white/35 ${className ?? ""}`}>{children}</p>;
}

/** Runs a query through the shared choreography: fold to a loading bar → dive (or punch-slide in the site view). */
/** Fetch the top result's image and every thumbnail into the browser cache (bounded wait). */
async function preloadImagery(candidates: Candidate[], signal: AbortSignal) {
  const get = (url: string) => fetch(url, { signal }).then((r) => r.blob()).catch(() => null);
  const all = Promise.all([...(candidates[0] ? [get(imageUrl(candidates[0].id))] : []), ...candidates.map((c) => get(thumbUrl(c.id)))]);
  await Promise.race([all, new Promise((r) => setTimeout(r, 15000))]);
}

export function useRunSearch() {
  const { mode } = useUi();
  const abort = useRef<AbortController | null>(null);
  const [error, setError] = useState<string | null>(null);
  const busy = mode === "searching" || mode === "diving" || mode === "surfacing";

  const run = async (q: AnalogQuery) => {
    if (busy) return;
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    setError(null);
    (document.activeElement as HTMLElement | null)?.blur?.();
    ui.startSearch(q);
    try {
      // Stage 1: the search itself (the bar creeps toward 55% meanwhile)
      // (after the bar has painted empty, so it visibly fills)
      setTimeout(() => ui.get().mode === "searching" && ui.get().progress < 0.55 && ui.setProgress(0.55), 80);
      const { candidates, source } = await findCandidates(q, controller.signal);
      // Stage 2: the imagery the dive lands on, so the clouds part onto a finished image
      ui.setProgress(0.92);
      await preloadImagery(candidates, controller.signal);
      if (controller.signal.aborted) return;
      ui.setProgress(1);
      await new Promise((r) => setTimeout(r, 280));
      ui.showResults(candidates, source);
      if (!candidates.length) setError("No candidates matched — try loosening a limit.");
    } catch (e) {
      if ((e as Error).name === "AbortError") return;
      ui.searchFailed();
      setError((e as Error).message);
    }
  };

  return { run, error, busy };
}
