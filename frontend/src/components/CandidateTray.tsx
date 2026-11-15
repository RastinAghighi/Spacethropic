"use client";

import { useEffect, useRef, useState } from "react";
import { DIVE, ui, useUi } from "@/lib/ui";
import { thumbUrl } from "@/lib/candidates";
import { useResearch } from "@/lib/research";
import { overallScore, passes, sameFilters } from "@/lib/profile";

const SIZE = 58;
/** Pointer influence radius (px) for the approach swell. */
const REACH = 150;
const APPROACH = 0.07;
const HOVER = 0.16;

/** Row of candidate thumbnails above the search bar; swells toward the pointer. */
export function CandidateTray() {
  const { mode, results, active, searchFrom, query } = useUi();
  const { draft, applied } = useResearch();
  // While limits are being drafted, preview which of these candidates would survive them.
  const previewing = !sameFilters(draft, applied);
  const items = useRef<(HTMLButtonElement | null)[]>([]);
  const [hovered, setHovered] = useState<number | null>(null);
  const shown = mode === "site" || mode === "diving" || mode === "surfacing" || (mode === "searching" && searchFrom === "site");
  const leaving = mode === "surfacing";

  // Approach magnification: scale each square by pointer proximity, without re-rendering.
  useEffect(() => {
    if (!shown) return;
    let raf = 0;
    let px = -1e4;
    let py = -1e4;
    const apply = () => {
      raf = 0;
      items.current.forEach((el) => {
        if (!el) return;
        const r = el.getBoundingClientRect();
        const d = Math.hypot(px - (r.left + r.width / 2), py - (r.top + r.height / 2));
        const near = Math.exp(-((d / REACH) ** 2));
        const over = d < r.width / 2 ? 1 : 0;
        const s = 1 + APPROACH * near + (HOVER - APPROACH) * over;
        el.style.setProperty("--s", s.toFixed(4));
        el.style.setProperty("--lift", `${(-6 * near - 4 * over).toFixed(2)}px`);
      });
    };
    const onMove = (e: PointerEvent) => {
      px = e.clientX;
      py = e.clientY;
      if (!raf) raf = requestAnimationFrame(apply);
    };
    const onLeave = () => {
      px = py = -1e4;
      if (!raf) raf = requestAnimationFrame(apply);
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    document.addEventListener("pointerleave", onLeave);
    return () => {
      window.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerleave", onLeave);
      cancelAnimationFrame(raf);
    };
  }, [shown, results]);

  // Arrow keys step through candidates.
  useEffect(() => {
    if (mode !== "site") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLElement && e.target.closest("input, textarea")) return;
      if (e.key === "ArrowRight") ui.select(Math.min(active + 1, results.length - 1));
      if (e.key === "ArrowLeft") ui.select(Math.max(active - 1, 0));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mode, active, results.length]);

  if (!shown || !results.length) return null;

  return (
    <div
      role="tablist"
      aria-label="Candidates"
      className="flex items-end justify-center gap-2.5"
      style={{
        opacity: leaving ? 0 : 1,
        transform: leaving ? "translateY(10px) scale(0.96)" : "none",
        filter: leaving ? "blur(4px)" : "none",
        pointerEvents: leaving ? "none" : undefined,
        transition: "opacity .4s ease, transform .5s var(--ease-out-expo), filter .5s ease",
      }}
    >
      {results.map((c, i) => {
        const isActive = i === active;
        const [r, g, b] = c.avgColor;
        const cut = previewing && !passes(c, draft);
        const score = query ? Math.round(overallScore(c, query) * 100) : null;
        return (
          <button
            key={c.id}
            ref={(el) => {
              items.current[i] = el;
            }}
            role="tab"
            aria-selected={isActive}
            aria-label={`${c.name}, ${c.region}${cut ? ", fails the drafted limits" : ""}`}
            onClick={() => ui.select(i)}
            onPointerEnter={() => setHovered(i)}
            onPointerLeave={() => setHovered((h) => (h === i ? null : h))}
            onFocus={() => setHovered(i)}
            onBlur={() => setHovered((h) => (h === i ? null : h))}
            className="group relative shrink-0 rounded-[13px] outline-none focus-visible:ring-2 focus-visible:ring-white/60"
            style={{
              width: SIZE,
              height: SIZE,
              transform: "translateY(var(--lift, 0px)) scale(var(--s, 1))",
              transformOrigin: "50% 100%",
              transition: "transform .22s var(--ease-out-expo)",
              animation: mode === "diving" ? `rise-in .7s var(--ease-out-expo) ${DIVE.tray + i * 0.045}s both` : undefined,
            }}
          >
            {/* Hover glow takes the site's own colour */}
            <span
              aria-hidden
              className="absolute -inset-2 rounded-[18px] opacity-0 blur-md transition-opacity duration-300 group-hover:opacity-100"
              style={{ background: `rgb(${r} ${g} ${b} / 0.55)` }}
            />
            <span
              className={`relative block h-full w-full overflow-hidden rounded-[13px] border transition-[border-color,box-shadow] duration-300 ${
                isActive
                  ? "border-white/80 shadow-[0_0_0_3px_rgb(255_255_255/0.12)]"
                  : "border-white/15 group-hover:border-white/45"
              }`}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={thumbUrl(c.id)}
                alt=""
                draggable={false}
                className="h-full w-full object-cover"
                style={{ filter: cut ? "grayscale(1) brightness(.45)" : "none", transition: "filter .4s ease" }}
              />
              {cut && (
                <span aria-hidden className="absolute inset-0 grid place-items-center" style={{ animation: "rise-in .3s var(--ease-out-expo) both" }}>
                  <svg width="16" height="16" viewBox="0 0 16 16">
                    <path d="M4 4l8 8M12 4l-8 8" stroke="white" strokeOpacity=".75" strokeWidth="1.5" strokeLinecap="round" />
                  </svg>
                </span>
              )}
              {!isActive && <span aria-hidden className="absolute inset-0 bg-black/25 transition-opacity duration-300 group-hover:opacity-0" />}
            </span>
            <span
              className="pointer-events-none absolute bottom-full left-1/2 mb-2.5 whitespace-nowrap rounded-lg border border-white/10 bg-[rgb(10_11_14/0.85)] px-2.5 py-1.5 text-center backdrop-blur-xl"
              style={{
                opacity: hovered === i ? 1 : 0,
                transform: `translate(-50%, ${hovered === i ? 0 : 4}px)`,
                transition: "opacity .2s, transform .25s var(--ease-out-expo)",
              }}
            >
              <span className="block text-[12px] font-medium text-white">{c.name}</span>
              <span className="block text-[10.5px] text-white/50">
                {c.region}
                {score !== null && <span className="text-white/75"> · {score}% match</span>}
              </span>
              {cut && <span className="mt-0.5 block text-[10.5px] text-[#f3b453]">Cut by your new limits</span>}
            </span>
          </button>
        );
      })}
    </div>
  );
}
