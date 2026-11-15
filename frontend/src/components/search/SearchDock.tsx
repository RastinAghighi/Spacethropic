"use client";

import { useEffect, useRef, useState } from "react";
import { useUi } from "@/lib/ui";
import { CandidateTray } from "../CandidateTray";
import { Dots, Icon } from "./primitives";

type Variant = "full" | "compressed" | "minimal";

const PENCIL = "M10.5 2.5l3 3L6 13H3v-3z M9 4l3 3";

/** Glass surface with the environment-tinted border, shared by the dock and its site-view editor. */
function Glass({ children, focused, className }: { children: React.ReactNode; focused?: boolean; className?: string }) {
  return (
    <div
      data-dock-frame
      className={`relative overflow-hidden p-px ${className ?? ""}`}
      style={{
        borderRadius: 24,
        background: `linear-gradient(to bottom, color-mix(in oklab, var(--glow-color) calc(var(--glow-strength) * 30%), rgb(255 255 255 / ${focused ? 0.22 : 0.13})), rgb(255 255 255 / ${focused ? 0.08 : 0.04}))`,
        boxShadow: "0 24px 70px -24px rgb(0 0 0 / 0.9)",
      }}
    >
      <div className="relative rounded-[23px] bg-[rgb(11_12_16/0.74)] shadow-[inset_0_1px_0_rgb(255_255_255/0.05)] backdrop-blur-2xl backdrop-saturate-150">
        {children}
      </div>
    </div>
  );
}

/**
 * Bottom dock for a structured search concept. Mirrors the natural-language bar's choreography:
 * full editor on the globe, folds to dots while searching, and a one-line summary in the site
 * view whose "Edit" opens the same editor above it, in place of the candidate tray.
 */
export function SearchDock({
  width,
  editor,
  summary,
  tint,
  error,
  label,
}: {
  width: number;
  editor: React.ReactNode;
  /** One-line description of the current query, for the site view. */
  summary: React.ReactNode;
  tint?: string;
  error?: string | null;
  label: string;
}) {
  const { landed, mode, searchFrom, barOpen } = useUi();
  const [editing, setEditing] = useState(false);
  const panel = useRef<HTMLDivElement>(null);

  const variant: Variant =
    mode === "searching" ? "compressed" : mode === "diving" || mode === "site" || (mode === "surfacing" && !barOpen) ? "minimal" : "full";
  const full = variant === "full";
  const compressed = variant === "compressed";
  const minimal = variant === "minimal";
  const inSite = minimal || (compressed && searchFrom === "site");
  const editorOpen = editing && mode === "site";

  // Close the site-view editor when a search starts (or we leave the site), on Esc, or on a click outside it.
  const [seenMode, setSeenMode] = useState(mode);
  if (mode !== seenMode) {
    setSeenMode(mode);
    if (mode !== "site") setEditing(false);
  }
  useEffect(() => {
    if (!editorOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopImmediatePropagation();
        setEditing(false);
      }
    };
    const onDown = (e: PointerEvent) => {
      const t = e.target as Node;
      if (panel.current?.contains(t) || (t instanceof Element && t.closest("[data-dock-popover]"))) return;
      setEditing(false);
    };
    window.addEventListener("keydown", onKey, true);
    window.addEventListener("pointerdown", onDown, true);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      window.removeEventListener("pointerdown", onDown, true);
    };
  }, [editorOpen]);

  const w = compressed ? 132 : minimal ? 600 : width;

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
        {/* Site view: candidates, or the editor when refining */}
        <div className="relative mb-3 flex min-h-8 w-full items-end justify-center" style={{ maxWidth: editorOpen ? width : 720 }}>
          {inSite && !editorOpen && <CandidateTray />}
          {editorOpen && (
            <div ref={panel} className="w-full" style={{ animation: "rise-in .5s var(--ease-out-expo) both" }}>
              <Glass focused>{editor}</Glass>
            </div>
          )}
          {error && (
            <p role="status" className="absolute -top-7 left-1 flex items-center gap-2 text-[12.5px] text-white/60">
              <span className="h-1.5 w-1.5 rounded-full bg-[#ff6b5e]" />
              {error}
            </p>
          )}
        </div>

        <div className="relative w-full" style={{ maxWidth: w, transition: `max-width ${compressed ? ".5s" : ".75s"} var(--ease-out-expo)` }}>
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
          <section aria-label={label} className="relative">
            <Glass>
              <div role="status" aria-label={compressed ? "Searching" : undefined} className="pointer-events-none absolute inset-0 flex items-center justify-center" style={{ opacity: compressed ? 1 : 0, transition: `opacity ${compressed ? ".35s .15s" : ".2s"} ease` }}>
                {compressed && <Dots />}
              </div>
              <div
                className="min-h-12"
                style={{
                  opacity: compressed ? 0 : 1,
                  filter: compressed ? "blur(6px)" : "none",
                  transition: compressed ? "opacity .18s ease, filter .25s ease" : "opacity .45s ease .1s, filter .5s var(--ease-out-expo) .1s",
                }}
              >
                {/* Globe: the full editor grows open */}
                <div className="grid" style={{ gridTemplateRows: full ? "1fr" : "0fr", transition: "grid-template-rows .65s var(--ease-out-expo)" }}>
                  <div className="min-h-0 overflow-hidden" aria-hidden={!full} inert={!full}>
                    {!editorOpen && (
                      <div
                        style={{
                          opacity: full ? 1 : 0,
                          transform: full ? "none" : "translateY(-8px)",
                          transition: full ? "opacity .5s ease .12s, transform .65s var(--ease-out-expo) .05s" : "opacity .15s ease, transform .3s ease",
                        }}
                      >
                        {editor}
                      </div>
                    )}
                  </div>
                </div>
                {/* Site view: one-line summary */}
                <div className="grid" style={{ gridTemplateRows: minimal ? "1fr" : "0fr", transition: "grid-template-rows .65s var(--ease-out-expo)" }}>
                  <div className="min-h-0 overflow-hidden" aria-hidden={!minimal} inert={!minimal}>
                    <div className="flex h-12 items-center gap-3 pl-5 pr-2" style={{ opacity: minimal ? 1 : 0, transition: "opacity .4s ease .1s" }}>
                      {tint && <span className="h-[7px] w-[7px] shrink-0 rounded-full" style={{ background: tint }} />}
                      <div className="min-w-0 flex-1 truncate text-[13.5px] text-white/75">{summary}</div>
                      <button
                        type="button"
                        onClick={() => setEditing((v) => !v)}
                        aria-expanded={editorOpen}
                        className={`flex h-8 shrink-0 items-center gap-1.5 rounded-full px-3 text-[12px] ring-1 transition-colors focus-visible:outline-none focus-visible:ring-white/40 ${
                          editorOpen ? "bg-white text-black ring-white" : "bg-white/[0.05] text-white/70 ring-white/[0.07] hover:text-white"
                        }`}
                      >
                        <Icon d={PENCIL} size={12} strokeWidth={1.4} />
                        {editorOpen ? "Close" : "Edit search"}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </Glass>
          </section>
        </div>
      </div>
    </div>
  );
}
