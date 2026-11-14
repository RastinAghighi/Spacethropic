"use client";

import dynamic from "next/dynamic";
import { ui, useUi } from "@/lib/ui";
import { Loader } from "./Loader";
import { SearchBar } from "./SearchBar";
import { SiteView } from "./SiteView";
import { SiteRenderer } from "./SiteRenderer";
import { EvidencePanel } from "./EvidencePanel";

const GlobeScene = dynamic(() => import("./globe/GlobeScene"), { ssr: false });

function Chrome() {
  const { landed, mode, searchFrom } = useUi();
  const inSite = mode === "site";
  const onGlobe = mode === "globe" || (mode === "searching" && searchFrom === "globe");
  const fade = {
    opacity: landed ? 1 : 0,
    transition: "opacity 1.6s var(--ease-out-expo) .2s",
  };
  return (
    <>
      <header className="fixed left-5 top-5 z-20 flex items-start gap-3 sm:left-7 sm:top-6" style={fade}>
        <button
          type="button"
          onClick={() => ui.surface()}
          aria-label="Back to Earth"
          tabIndex={inSite ? 0 : -1}
          className="mt-0.5 flex h-8 items-center gap-1.5 overflow-hidden rounded-full border border-white/10 bg-[rgb(10_11_14/0.6)] text-[12px] text-white/75 backdrop-blur-xl transition-[max-width,opacity,padding,margin] duration-500 hover:border-white/25 hover:text-white focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/40"
          style={{
            maxWidth: inSite ? 120 : 0,
            opacity: inSite ? 1 : 0,
            paddingInline: inSite ? 12 : 0,
            marginRight: inSite ? 0 : -12,
            pointerEvents: inSite ? "auto" : "none",
          }}
        >
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden className="shrink-0">
            <path d="M7.5 2.5L4 6l3.5 3.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Earth
        </button>
        {/* Brand steps aside once we're down at a site */}
        <div
          className="pointer-events-none"
          style={{
            opacity: onGlobe ? 1 : 0,
            transform: onGlobe ? "none" : "translateX(-6px)",
            filter: onGlobe ? "none" : "blur(3px)",
            transition: "opacity .5s ease, transform .6s var(--ease-out-expo), filter .5s ease",
          }}
        >
          <p className="text-[13px] font-medium tracking-[-0.01em] text-white/90">Spacethropic</p>
          <p className="mt-0.5 text-[12px] text-white/40">Earth analogs for the Moon &amp; Mars</p>
        </div>
      </header>
      <p
        className="pointer-events-none fixed right-5 top-5 z-10 hidden max-w-xs text-right font-mono text-[10px] leading-relaxed text-white/25 sm:right-7 sm:top-6 md:block"
        style={{ ...fade, opacity: landed && mode === "globe" ? 1 : 0 }}
      >
        NASA Blue Marble NG · VIIRS Black Marble · GEBCO
        <br />
        LRO / SVS CGI Moon Kit · SVS Deep Star Maps 2020 · Hipparcos/Tycho
      </p>
    </>
  );
}

export default function Experience() {
  return (
    <main className="fixed inset-0 bg-black">
      <GlobeScene />
      <SiteRenderer />
      <SiteView />
      <EvidencePanel />
      <Chrome />
      <SearchBar />
      <Loader />
    </main>
  );
}
