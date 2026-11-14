"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useUi } from "@/lib/ui";
import {
  EXAMPLE_PROMPTS,
  QUICK_FILTERS,
  SearchUnavailableError,
  searchAnalogs,
  type AnalogResult,
  type AnalogTarget,
} from "@/lib/search";

const TARGETS: { id: AnalogTarget; label: string; tint: string }[] = [
  { id: "moon", label: "Moon", tint: "#cfd2d8" },
  { id: "mars", label: "Mars", tint: "#d9774f" },
];

const MAX_LINES = 4;
const LINE_HEIGHT = 24;

type Status =
  | { kind: "idle" }
  | { kind: "pending" }
  | { kind: "info"; message: string }
  | { kind: "error"; message: string };

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

function Spinner() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden style={{ animation: "orbit 0.9s linear infinite" }}>
      <circle cx="8" cy="8" r="6" stroke="currentColor" strokeOpacity="0.2" strokeWidth="1.6" />
      <path d="M14 8a6 6 0 00-6-6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
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

/** Natural-language analog search, docked to the bottom of the viewport. */
export function SearchBar({ onResults }: { onResults?: (results: AnalogResult[]) => void }) {
  const { landed } = useUi();
  const inputId = useId();
  const textarea = useRef<HTMLTextAreaElement>(null);
  const abort = useRef<AbortController | null>(null);

  const [value, setValue] = useState("");
  const [target, setTarget] = useState<AnalogTarget>("moon");
  const [focused, setFocused] = useState(false);
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [promptIndex, setPromptIndex] = useState(0);

  const empty = value.trim().length === 0;
  const pending = status.kind === "pending";
  const examples = EXAMPLE_PROMPTS[target];

  // Rotate the example prompt while the field is empty.
  useEffect(() => {
    if (!empty) return;
    const id = window.setInterval(() => setPromptIndex((i) => i + 1), 4200);
    return () => window.clearInterval(id);
  }, [empty]);

  // "/" or ⌘K / Ctrl+K focuses the search from anywhere.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLElement && e.target.closest("input, textarea, [contenteditable]");
      if ((e.key === "/" && !typing) || (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey))) {
        e.preventDefault();
        textarea.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const resize = useCallback(() => {
    const el = textarea.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, LINE_HEIGHT * MAX_LINES)}px`;
  }, []);

  const fill = (text: string) => {
    setValue(text);
    setStatus({ kind: "idle" });
    requestAnimationFrame(() => {
      resize();
      const el = textarea.current;
      el?.focus();
      el?.setSelectionRange(text.length, text.length);
    });
  };

  const submit = async () => {
    const text = value.trim();
    if (!text || pending) return;
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    setStatus({ kind: "pending" });
    try {
      const results = await searchAnalogs({ text, target }, controller.signal);
      setStatus({ kind: "idle" });
      onResults?.(results);
    } catch (e) {
      if ((e as Error).name === "AbortError") return;
      setStatus(
        e instanceof SearchUnavailableError
          ? { kind: "info", message: "The analog index isn't connected yet — your query is ready to send." }
          : { kind: "error", message: (e as Error).message },
      );
    }
  };

  const showFilters = focused && empty && !pending;
  const targetIndex = TARGETS.findIndex((t) => t.id === target);

  return (
    <div
      className="pointer-events-none fixed inset-x-0 bottom-0 z-20 flex justify-center px-3 pb-4 sm:pb-7"
      style={{
        opacity: landed ? 1 : 0,
        transform: landed ? "none" : "translateY(18px)",
        filter: landed ? "none" : "blur(6px)",
        transition: "opacity 1.1s var(--ease-out-expo), transform 1.1s var(--ease-out-expo), filter 1.1s var(--ease-out-expo)",
      }}
    >
      <div className="pointer-events-auto w-full max-w-[720px]">
        {/* Status + quick filters */}
        <div className="relative mb-2.5 h-8">
          <div
            className="absolute inset-0 flex items-center gap-1.5 overflow-x-auto [scrollbar-width:none]"
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
          <div
            role="status"
            aria-live="polite"
            className="absolute inset-0 flex items-center gap-2 px-1 text-[12.5px]"
            style={{
              opacity: status.kind === "info" || status.kind === "error" || pending ? 1 : 0,
              transition: "opacity .35s var(--ease-out-expo)",
            }}
          >
            {pending && <span className="text-white/55">Searching Earth for {target === "moon" ? "lunar" : "Martian"} analogs…</span>}
            {(status.kind === "info" || status.kind === "error") && (
              <>
                <span className={`h-1.5 w-1.5 rounded-full ${status.kind === "error" ? "bg-[#ff6b5e]" : "bg-[#e8b04a]"}`} />
                <span className="text-white/60">{status.message}</span>
              </>
            )}
          </div>
        </div>

        {/* Bar: 1px gradient hairline (with a travelling highlight while pending) around a frosted panel */}
        <form
          role="search"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
          className="rounded-[23px] p-px transition-[box-shadow] duration-500"
          style={{
            background: pending
              ? "conic-gradient(from var(--sweep-angle), rgb(255 255 255 / 0.06) 0 62%, rgb(255 255 255 / 0.55) 80%, rgb(255 255 255 / 0.06) 96%)"
              : `linear-gradient(to bottom, rgb(255 255 255 / ${focused ? 0.22 : 0.13}), rgb(255 255 255 / ${focused ? 0.08 : 0.04}))`,
            animation: pending ? "sweep 1.8s linear infinite" : undefined,
            boxShadow: focused
              ? "0 24px 70px -24px rgb(0 0 0 / 0.9), 0 0 0 4px rgb(255 255 255 / 0.03)"
              : "0 24px 70px -24px rgb(0 0 0 / 0.9)",
          }}
        >
          <div className="rounded-[22px] bg-[rgb(11_12_16/0.74)] shadow-[inset_0_1px_0_rgb(255_255_255/0.05)] backdrop-blur-2xl backdrop-saturate-150">
            <label htmlFor={inputId} className="sr-only">
              Describe the environment you&apos;re looking for
            </label>
            <div className="relative flex gap-3 px-5 pt-[18px]">
              <span className="mt-[3px] text-white/40">
                <SearchGlyph />
              </span>
              <div className="relative min-w-0 flex-1">
                {empty && (
                  <span
                    key={`${target}-${promptIndex}`}
                    aria-hidden
                    className="pointer-events-none absolute inset-x-0 top-0 truncate text-[15px] leading-6 text-white/35"
                    style={{ animation: "prompt-in .7s var(--ease-out-expo) both" }}
                  >
                    {examples[promptIndex % examples.length]}
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
                    if (status.kind !== "pending") setStatus({ kind: "idle" });
                    resize();
                  }}
                  onFocus={() => setFocused(true)}
                  onBlur={() => setFocused(false)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                      e.preventDefault();
                      submit();
                    } else if (e.key === "Escape") {
                      e.currentTarget.blur();
                    } else if (e.key === "Tab" && empty && !e.shiftKey) {
                      // Tab accepts the example prompt shown.
                      e.preventDefault();
                      fill(examples[promptIndex % examples.length]);
                    }
                  }}
                  className="block max-h-24 w-full resize-none bg-transparent text-[15px] leading-6 text-white/95 caret-white outline-none [scrollbar-width:thin]"
                />
              </div>
            </div>

            <div className="flex items-center justify-between gap-3 px-3 pb-3 pt-3.5 pl-4">
              {/* Moon / Mars target */}
              <div className="flex items-center gap-2.5">
                <span className="hidden text-[11.5px] text-white/35 sm:inline">Analog for</span>
                <div role="radiogroup" aria-label="Analog for" className="relative flex rounded-full bg-white/[0.04] p-[3px] ring-1 ring-white/[0.07]">
                  <span
                    aria-hidden
                    className="absolute top-[3px] bottom-[3px] left-[3px] w-[calc(50%-3px)] rounded-full bg-white/[0.09] shadow-[inset_0_1px_0_rgb(255_255_255/0.08)]"
                    style={{
                      transform: `translateX(${targetIndex * 100}%)`,
                      transition: "transform .45s var(--ease-out-expo)",
                    }}
                  />
                  {TARGETS.map((t) => (
                    <button
                      key={t.id}
                      type="button"
                      role="radio"
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
                <button
                  type="submit"
                  aria-label="Search"
                  disabled={empty || pending}
                  className={`flex h-9 w-9 items-center justify-center rounded-full transition-all duration-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/50 focus-visible:ring-offset-2 focus-visible:ring-offset-black ${
                    empty && !pending
                      ? "bg-white/[0.06] text-white/25"
                      : "bg-white text-black shadow-[0_0_24px_-4px_rgb(255_255_255/0.45)] hover:scale-[1.04] active:scale-95"
                  }`}
                >
                  {pending ? <Spinner /> : <ArrowUp />}
                </button>
              </div>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
