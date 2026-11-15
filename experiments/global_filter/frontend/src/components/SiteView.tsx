"use client";

import { useEffect, useState } from "react";
import { ui, useUi } from "@/lib/ui";
import { groundFrame } from "@/lib/flight";

/** A tidy scale bar length (km) near the target pixel width. */
function scaleBar(metersPerCssPx: number, targetPx = 110) {
  const km = (metersPerCssPx * targetPx) / 1000;
  const nice = [1, 2, 5, 10, 20, 50].find((n) => n >= km * 0.7) ?? 50;
  return { km: nice, px: (nice * 1000) / metersPerCssPx };
}

/** Map furniture over the satellite view (rendered by SiteRenderer): reticle, scale, north, source. */
export function SiteView() {
  const { mode, results, active } = useUi();
  const [bar, setBar] = useState({ km: 10, px: 110 });
  const [pos, setPos] = useState({ x: 0.36, y: 0.45 });
  const current = results[active];

  // Scale bar follows the cover-fit of the imagery at rest.
  useEffect(() => {
    const update = () => {
      const f = groundFrame(window.innerWidth, window.innerHeight, current?.imagery.metersPerPixel);
      setBar(scaleBar((f.kmPerUnit * 1000) / window.innerHeight));
      setPos({ x: f.anchorX, y: f.anchorY });
    };
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, [current]);

  const visible = mode === "diving" || mode === "site" || mode === "surfacing" || (mode === "searching" && ui.get().searchFrom === "site");
  const chromeIn = mode === "site" || (mode === "searching" && ui.get().searchFrom === "site");
  // The grade comes in with the punch itself, not after landing.
  const shadeIn = chromeIn || mode === "diving";
  const at = { left: `${pos.x * 100}%`, top: `${pos.y * 100}%` };

  return (
    <div aria-hidden={!visible} className="pointer-events-none fixed inset-0 z-10 overflow-hidden" style={{ visibility: visible ? "visible" : "hidden" }}>
      {/* Readability and focus: a vignette around the site, darker toward the panel and controls. */}
      <div className="absolute inset-0" style={{ opacity: shadeIn ? 1 : 0, transition: `opacity ${shadeIn ? "1.1s" : ".7s"} ease` }}>
        <div className="absolute inset-0" style={{ background: `radial-gradient(110% 85% at ${at.left} ${at.top}, transparent 38%, rgb(0 0 0 / 0.5))` }} />
        <div className="absolute inset-y-0 right-0 w-[48%] bg-gradient-to-l from-black/55 to-transparent" />
        <div className="absolute inset-x-0 bottom-0 h-64 bg-gradient-to-t from-black/60 to-transparent" />
      </div>

      <div className="transition-opacity duration-700" style={{ opacity: chromeIn ? 1 : 0 }}>
        {/* Site reticle */}
        <div className="absolute" style={at}>
          <div className="absolute h-12 w-12 rounded-full border border-white/70 shadow-[0_0_0_1px_rgb(0_0_0/0.25)]" style={{ transform: "translate(-50%, -50%)" }}>
            {[0, 90, 180, 270].map((r) => (
              <span key={r} className="absolute left-1/2 top-1/2 h-px w-2.5 bg-white/80" style={{ transform: `rotate(${r}deg) translateX(30px)`, transformOrigin: "0 0" }} />
            ))}
          </div>
        </div>

        {/* Scale, north and source */}
        <div className="absolute bottom-6 left-5 flex items-end gap-4 font-mono text-[10.5px] text-white/70 sm:bottom-8 sm:left-7">
          <div className="flex flex-col items-center gap-1">
            <span className="text-[9.5px] tracking-[0.2em] text-white/60">N</span>
            <svg width="10" height="14" viewBox="0 0 10 14" aria-hidden>
              <path d="M5 0L10 14L5 10.5L0 14Z" fill="white" fillOpacity="0.8" />
            </svg>
          </div>
          <div>
            <div className="mb-1">{bar.km} km</div>
            <div className="h-1.5 border-x border-b border-white/70" style={{ width: bar.px }} />
          </div>
        </div>
        {current && (
          <p className="absolute bottom-[78px] left-5 hidden font-mono text-[10px] text-white/45 sm:left-7 lg:block">
            NASA HLS · {current.imagery.date} · {current.imagery.metersPerPixel} m/px
          </p>
        )}
      </div>
    </div>
  );
}
