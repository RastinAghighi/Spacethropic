"use client";

import { useUi } from "@/lib/ui";
import { CandidateTray } from "../CandidateTray";
import { LoadingBar } from "./primitives";

type Variant = "full" | "compressed" | "hidden";

/** Glass surface with the environment-tinted border. */
function Glass({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="relative overflow-hidden p-px"
      style={{
        borderRadius: 24,
        background:
          "linear-gradient(to bottom, color-mix(in oklab, var(--glow-color) calc(var(--glow-strength) * 30%), rgb(255 255 255 / 0.13)), rgb(255 255 255 / 0.04))",
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
 * Bottom dock. On the globe it holds the search editor; while a search runs it folds to
 * a loading bar; in the site view it steps away entirely, leaving only the candidate tray, since
 * refining happens in the side drawers.
 */
export function SearchDock({ width, editor, tint, error, label }: { width: number; editor: React.ReactNode; tint?: string; error?: string | null; label: string }) {
  const { landed, mode, searchFrom, barOpen } = useUi();

  const variant: Variant =
    mode === "searching" ? "compressed" : mode === "diving" || mode === "site" || (mode === "surfacing" && !barOpen) ? "hidden" : "full";
  const full = variant === "full";
  const compressed = variant === "compressed";
  const hidden = variant === "hidden";
  const inSite = hidden || (compressed && searchFrom === "site");
  const w = compressed ? 144 : width;

  return (
    <div
      className="pointer-events-none fixed inset-x-0 bottom-0 z-30 flex justify-center px-3 pb-4 sm:pb-6"
      style={{
        opacity: landed ? 1 : 0,
        transform: landed ? "none" : "translateY(18px)",
        filter: landed ? "none" : "blur(6px)",
        transition:
          "opacity 1.1s var(--ease-out-expo), transform 1.1s var(--ease-out-expo), filter 1.1s var(--ease-out-expo)",
      }}
    >
      <div className="pointer-events-auto flex w-full flex-col items-center">
        {/* Site view: the candidates */}
        <div className="relative flex min-h-8 w-full max-w-[720px] items-end justify-center" style={{ marginBottom: hidden ? 0 : 12, transition: "margin .6s var(--ease-out-expo)" }}>
          {inSite && <CandidateTray />}
          {error && (
            <p role="status" className="absolute -top-7 left-1 flex items-center gap-2 text-[12.5px] text-white/60">
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: tint ?? "#ff6b5e" }} />
              {error}
            </p>
          )}
        </div>

        {/* The bar folds away under the tray in the site view */}
        <div
          className="grid w-full justify-items-center"
          style={{
            gridTemplateRows: hidden ? "0fr" : "1fr",
            opacity: hidden ? 0 : 1,
            transition: hidden ? "grid-template-rows .6s var(--ease-out-expo), opacity .25s ease" : "grid-template-rows .6s var(--ease-out-expo), opacity .4s ease .1s",
          }}
        >
          <div className="min-h-0 w-full" style={{ overflow: hidden ? "hidden" : "visible" }} aria-hidden={hidden} inert={hidden}>
            <div className="relative mx-auto w-full" style={{ maxWidth: w, transition: `max-width ${compressed ? ".5s" : ".75s"} var(--ease-out-expo)` }}>
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
                    {compressed && <LoadingBar className="w-[96px]" />}
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
                        <div
                          style={{
                            opacity: full ? 1 : 0,
                            transform: full ? "none" : "translateY(-8px)",
                            transition: full ? "opacity .5s ease .12s, transform .65s var(--ease-out-expo) .05s" : "opacity .15s ease, transform .3s ease",
                          }}
                        >
                          {editor}
                        </div>
                      </div>
                    </div>
                  </div>
                </Glass>
              </section>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
