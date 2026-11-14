"use client";

import dynamic from "next/dynamic";
import { useUi } from "@/lib/ui";
import { Loader } from "./Loader";
import { SearchBar } from "./SearchBar";

const GlobeScene = dynamic(() => import("./globe/GlobeScene"), { ssr: false });

function Chrome() {
  const { landed } = useUi();
  const fade = {
    opacity: landed ? 1 : 0,
    transition: "opacity 1.6s var(--ease-out-expo) .2s",
  };
  return (
    <>
      <header className="pointer-events-none fixed left-5 top-5 z-10 sm:left-7 sm:top-6" style={fade}>
        <p className="text-[13px] font-medium tracking-[-0.01em] text-white/90">Spacethropic</p>
        <p className="mt-0.5 text-[12px] text-white/40">Earth analogs for the Moon &amp; Mars</p>
      </header>
      <p
        className="pointer-events-none fixed right-5 top-5 z-10 hidden max-w-xs text-right font-mono text-[10px] leading-relaxed text-white/25 sm:right-7 sm:top-6 md:block"
        style={fade}
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
      <Chrome />
      <SearchBar />
      <Loader />
    </main>
  );
}
