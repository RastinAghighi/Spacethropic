"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { ui, useUi } from "@/lib/ui";
import { EXAMPLE_PROMPTS, QUICK_FILTERS, findCandidates, type AnalogTarget } from "@/lib/search";
import { CandidateTray } from "./CandidateTray";

// eslint-disable-next-line @typescript-eslint/no-unused-vars -- used by the commented-out target selector
const TARGETS: { id: AnalogTarget; label: string; tint: string }[] = [
  { id: "moon", label: "Moon", tint: "#cfd2d8" },
  { id: "mars", label: "Mars", tint: "#d9774f" },
];

const MAX_LINES = 4;
const LINE_HEIGHT = 24;

type Variant = "full" | "compressed" | "minimal";

function ArrowUp() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
      <path d="M8 13V3.5M8 3.5L3.75 7.75M8 3.5l4.25 4.25" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function SearchGlyph() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden className="shrink-0">
      <circle cx="8" cy="8" r="5.25" stroke="currentColor" strokeWidth="1.4" />
      <path d="M12 12l3.25 3.25" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      <circle cx="8" cy="8" r="1.4" fill="currentColor" />
    </svg>
  );
}

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-[5px] border border-white/10 bg-white/[0.04] px-1 font-mono text-[10.5px] leading-none text-white/50">
      {children}
    </kbd>
  );
}

function Dots() {
  return (
    <span className="flex items-center gap-[5px]" aria-hidden>
      {[0, 1, 2].map((i) => (
        <span key={i} className="h-[6px] w-[6px] rounded-full bg-white" style={{ animation: `bounce-dot 1.1s ease-in-out ${i * 0.14}s infinite` }} />
      ))}
    </span>
  );
}

function SubmitButton({ disabled, small }: { disabled: boolean; small?: boolean }) {
  return (
    <button
      type="submit"
      aria-label="Search"
      disabled={disabled}
      className={`flex shrink-0 items-center justify-center rounded-full transition-all duration-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/50 focus-visible:ring-offset-2 focus-visible:ring-offset-black ${
        small ? "h-8 w-8" : "h-9 w-9"
      } ${
        disabled
          ? "bg-white/[0.06] text-white/25"
          : "bg-white text-black shadow-[0_0_24px_-4px_rgb(255_255_255/0.45)] hover:scale-[1.04] active:scale-95"
      }`}
    >
      <ArrowUp />
    </button>
  );
}

/** Natural-language analog search, docked to the bottom of the viewport. */
export function SearchBar() {
  const { landed, mode, query, searchFrom, barOpen } = useUi();
  const inputId = useId();
  const textarea = useRef<HTMLTextAreaElement>(null);
  const abort = useRef<AbortController | null>(null);

  const [value, setValue] = useState("");
  // Moon/Mars selection is commented out below: the target comes from the search constraints.
  const [target] = useState<AnalogTarget>("moon");
  const [focused, setFocused] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [promptIndex, setPromptIndex] = useState(0);

  const variant: Variant =
    mode === "searching"
      ? "compressed"
      : mode === "diving" || mode === "site" || (mode === "surfacing" && !barOpen)
        ? "minimal"
        : "full";
  const inSite = variant === "minimal" || (variant === "compressed" && searchFrom === "site");
  const full = variant === "full";
  const compressed = variant === "compressed";
  const empty = value.trim().length === 0;
  const examples = EXAMPLE_PROMPTS[target];

  useEffect(() => {
    if (!empty || variant !== "full") return;
    const id = window.setInterval(() => setPromptIndex((i) => i + 1), 4200);
    return () => window.clearInterval(id);
  }, [empty, variant]);

  // "/" or ⌘K / Ctrl+K focuses the search from anywhere; Esc in the site view returns to Earth.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLElement && e.target.closest("input, textarea, [contenteditable]");
      if ((e.key === "/" && !typing) || (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey))) {
        e.preventDefault();
        textarea.current?.focus();
      } else if (e.key === "Escape" && !typing && ui.get().mode === "site") {
        ui.surface();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const resize = useCallback(() => {
    const el = textarea.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, LINE_HEIGHT * (variant === "full" ? MAX_LINES : 1))}px`;
  }, [variant]);

  const fill = (text: string) => {
    setValue(text);
    setError(null);
    requestAnimationFrame(() => {
      resize();
      const el = textarea.current;
      el?.focus();
      el?.setSelectionRange(text.length, text.length);
    });
  };

  const submit = async () => {
    const text = value.trim();
    if (!text || mode === "searching" || mode === "diving" || mode === "surfacing") return;
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    setError(null);
    textarea.current?.blur();
    const q = { text, target };
    ui.startSearch(q);
    try {
      const { candidates, source } = await findCandidates(q, controller.signal);
      setValue("");
      ui.showResults(candidates, source);
      if (!candidates.length) setError("No candidates matched — try describing the terrain or conditions differently.");
    } catch (e) {
      if ((e as Error).name === "AbortError") return;
      ui.searchFailed();
      setError((e as Error).message);
    }
  };

  const showFilters = variant === "full" && focused && empty;
  // const targetIndex = TARGETS.findIndex((t) => t.id === target);
  const width = variant === "compressed" ? 132 : variant === "minimal" ? 600 : 720;

  return (
    <div
      className="pointer-events-none fixed inset-x-0 bottom-0 z-30 flex justify-center px-3 pb-4 sm:pb-7"
      style={{
        opacity: landed ? 1 : 0,
        transform: landed ? "none" : "translateY(18px)",
        filter: landed ? "none" : "blur(6px)",
        paddingRight: inSite ? "var(--panel-space)" : undefined,
        transition:
          "opacity 1.1s var(--ease-out-expo), transform 1.1s var(--ease-out-expo), filter 1.1s var(--ease-out-expo), padding .8s var(--ease-out-expo)",
      }}
    >
      <div className="pointer-events-auto flex w-full flex-col items-center">
        {/* Candidates (site view) or quick filters (globe) */}
        <div className="relative mb-3 flex min-h-8 w-full max-w-[720px] items-end justify-center">
          {inSite ? (
            <CandidateTray />
          ) : (
            <div
              className="flex w-full items-center gap-1.5 overflow-x-auto [scrollbar-width:none]"
              style={{
                opacity: showFilters ? 1 : 0,
                transform: showFilters ? "none" : "translateY(4px)",
                pointerEvents: showFilters ? "auto" : "none",
                transition: "opacity .35s var(--ease-out-expo), transform .35s var(--ease-out-expo)",
              }}
            >
              {QUICK_FILTERS.map((f) => (
                <button
                  key={f.label}
                  type="button"
                  tabIndex={showFilters ? 0 : -1}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => fill(f.prompt)}
                  className="h-7 shrink-0 rounded-full border border-white/[0.08] bg-[rgb(14_15_19/0.7)] px-3 text-[12px] text-white/60 backdrop-blur-xl transition-colors hover:border-white/20 hover:text-white/90 focus-visible:border-white/30 focus-visible:text-white focus-visible:outline-none"
                >
                  {f.label}
                </button>
              ))}
            </div>
          )}
          {error && (
            <p role="status" className="absolute -top-7 left-1 flex items-center gap-2 text-[12.5px] text-white/60">
              <span className="h-1.5 w-1.5 rounded-full bg-[#ff6b5e]" />
              {error}
            </p>
          )}
        </div>

        <div className="relative w-full" style={{ maxWidth: width, transition: `max-width ${compressed ? ".5s" : ".75s"} var(--ease-out-expo)` }}>
          {/* Environment glow: tinted by the sun on the globe, by the imagery in the site view */}
          <div
            aria-hidden
            className="pointer-events-none absolute -inset-x-12 -bottom-6 -top-16"
            style={{
              background:
                "radial-gradient(50% 55% at var(--glow-x) 72%, color-mix(in oklab, var(--glow-color) calc(var(--glow-strength) * 42%), transparent), transparent 78%)",
              filter: "blur(16px)",
            }}
          />
          <form
            role="search"
            onSubmit={(e) => {
              e.preventDefault();
              submit();
            }}
            className="relative overflow-hidden p-px"
            style={{
              borderRadius: 24,
              background: `linear-gradient(to bottom, color-mix(in oklab, var(--glow-color) calc(var(--glow-strength) * 30%), rgb(255 255 255 / ${focused ? 0.22 : 0.13})), rgb(255 255 255 / ${focused ? 0.08 : 0.04}))`,
              boxShadow: focused
                ? "0 24px 70px -24px rgb(0 0 0 / 0.9), 0 0 0 4px rgb(255 255 255 / 0.03)"
                : "0 24px 70px -24px rgb(0 0 0 / 0.9)",
              transition: "box-shadow .5s",
            }}
          >
            <div className="relative rounded-[23px] bg-[rgb(11_12_16/0.74)] shadow-[inset_0_1px_0_rgb(255_255_255/0.05)] backdrop-blur-2xl backdrop-saturate-150">
              <label htmlFor={inputId} className="sr-only">
                Describe the environment you&apos;re looking for
              </label>

              {/* Searching: the bar folds down to a pill of dots */}
              <div
                role="status"
                aria-label={compressed ? "Searching" : undefined}
                className="pointer-events-none absolute inset-0 flex items-center justify-center"
                style={{ opacity: compressed ? 1 : 0, transition: `opacity ${compressed ? ".35s .15s" : ".2s"} ease` }}
              >
                {compressed && <Dots />}
              </div>

              <div
                style={{
                  opacity: compressed ? 0 : 1,
                  filter: compressed ? "blur(6px)" : "none",
                  transition: compressed ? "opacity .18s ease, filter .25s ease" : "opacity .45s ease .1s, filter .5s var(--ease-out-expo) .1s",
                }}
              >
                {/* Input row: the same element in every state, so nothing re-mounts or jumps */}
                <div className="relative flex min-h-12 items-start gap-3 py-3 pl-5 transition-[padding] duration-500" style={{ paddingRight: full ? 20 : 8 }}>
                  <span className="mt-[3px] text-white/40">
                    <SearchGlyph />
                  </span>
                  <div className="relative min-w-0 flex-1">
                    {empty && (
                      <span
                        key={full ? `${target}-${promptIndex}` : "refine"}
                        aria-hidden
                        className="pointer-events-none absolute inset-x-0 top-0 truncate text-[15px] leading-6 text-white/35"
                        style={{ animation: "prompt-in .7s var(--ease-out-expo) both" }}
                      >
                        {full ? examples[promptIndex % examples.length] : query ? `Refine “${query.text}”` : "Refine your search"}
                      </span>
                    )}
                    <textarea
                      ref={textarea}
                      id={inputId}
                      rows={1}
                      value={value}
                      spellCheck={false}
                      onChange={(e) => {
                        setValue(e.target.value);
                        setError(null);
                        resize();
                      }}
                      onFocus={() => setFocused(true)}
                      onBlur={() => setFocused(false)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && (!e.shiftKey || !full) && !e.nativeEvent.isComposing) {
                          e.preventDefault();
                          submit();
                        } else if (e.key === "Escape") {
                          e.currentTarget.blur();
                        } else if (e.key === "Tab" && empty && !e.shiftKey && full) {
                          e.preventDefault();
                          fill(examples[promptIndex % examples.length]);
                        }
                      }}
                      className="block max-h-24 w-full resize-none bg-transparent text-[15px] leading-6 text-white/95 caret-white outline-none [scrollbar-width:thin]"
                    />
                  </div>
                  {/* Refine controls slide in from the right in the site view */}
                  <div
                    aria-hidden={full}
                    className="-my-1 flex shrink-0 items-center gap-2 overflow-hidden"
                    style={{
                      maxWidth: full ? 0 : 48,
                      opacity: full ? 0 : 1,
                      transform: full ? "translateX(8px)" : "none",
                      transition: "max-width .6s var(--ease-out-expo), opacity .35s ease, transform .6s var(--ease-out-expo)",
                    }}
                  >
                    {/* Target chip — inferred from the search constraints for now.
                    <button
                      type="button"
                      tabIndex={full ? -1 : 0}
                      onClick={() => setTarget((t) => (t === "moon" ? "mars" : "moon"))}
                      aria-label={`Analog for ${target === "moon" ? "Moon" : "Mars"} — switch`}
                      className="flex h-8 shrink-0 items-center gap-1.5 rounded-full bg-white/[0.05] px-3 text-[12px] text-white/70 ring-1 ring-white/[0.07] transition-colors hover:text-white focus-visible:outline-none focus-visible:ring-white/40"
                    >
                      <span className="h-[7px] w-[7px] rounded-full" style={{ background: TARGETS[targetIndex].tint }} />
                      {TARGETS[targetIndex].label}
                    </button>
                    */}
                    <SubmitButton disabled={empty || full} small />
                  </div>
                </div>

                {/* Toolbar: grows open underneath on the globe */}
                <div className="grid" style={{ gridTemplateRows: full ? "1fr" : "0fr", transition: "grid-template-rows .65s var(--ease-out-expo)" }}>
                  <div className="min-h-0 overflow-hidden">
                    <div
                      aria-hidden={!full}
                      className="flex items-center justify-end gap-3 px-3 pb-3 pl-4 pt-1.5"
                      style={{
                        opacity: full ? 1 : 0,
                        transform: full ? "none" : "translateY(-8px)",
                        transition: full ? "opacity .5s ease .12s, transform .65s var(--ease-out-expo) .05s" : "opacity .15s ease, transform .3s ease",
                      }}
                    >
                      {/* Analog target is now inferred from the search constraints; selector kept for reference.
                      <div className="flex items-center gap-2.5">
                        <span className="hidden text-[11.5px] text-white/35 sm:inline">Analog for</span>
                        <div role="radiogroup" aria-label="Analog for" className="relative flex rounded-full bg-white/[0.04] p-[3px] ring-1 ring-white/[0.07]">
                          <span
                            aria-hidden
                            className="absolute bottom-[3px] left-[3px] top-[3px] w-[calc(50%-3px)] rounded-full bg-white/[0.09] shadow-[inset_0_1px_0_rgb(255_255_255/0.08)]"
                            style={{ transform: `translateX(${targetIndex * 100}%)`, transition: "transform .45s var(--ease-out-expo)" }}
                          />
                          {TARGETS.map((t) => (
                            <button
                              key={t.id}
                              type="button"
                              role="radio"
                              tabIndex={full ? 0 : -1}
                              aria-checked={target === t.id}
                              onClick={() => {
                                setTarget(t.id);
                                setPromptIndex(0);
                              }}
                              className={`relative z-10 flex h-7 w-[76px] items-center justify-center gap-1.5 rounded-full text-[12.5px] transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/40 ${
                                target === t.id ? "text-white" : "text-white/45 hover:text-white/75"
                              }`}
                            >
                              <span className="h-[7px] w-[7px] rounded-full" style={{ background: t.tint, opacity: target === t.id ? 1 : 0.55 }} />
                              {t.label}
                            </button>
                          ))}
                        </div>
                      </div>
                      */}
                      <div className="flex items-center gap-3">
                        <span className="hidden items-center gap-1.5 text-[11.5px] text-white/35 sm:flex">
                          {focused ? (
                            empty ? (
                              <>
                                <Kbd>Tab</Kbd> use example
                              </>
                            ) : (
                              <>
                                <Kbd>↵</Kbd> search <span className="mx-1 text-white/15">·</span> <Kbd>⇧↵</Kbd> new line
                              </>
                            )
                          ) : (
                            <>
                              <Kbd>/</Kbd> to search
                            </>
                          )}
                        </span>
                        <SubmitButton disabled={empty || !full} />
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
