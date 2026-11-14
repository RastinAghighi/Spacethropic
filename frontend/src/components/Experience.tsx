"use client";

import dynamic from "next/dynamic";
import { useProgress } from "@react-three/drei";

const GlobeScene = dynamic(() => import("./globe/GlobeScene"), { ssr: false });

function Loader() {
  const { active, progress } = useProgress();
  if (!active && progress >= 100) return null;
  return (
    <div className="pointer-events-none fixed inset-0 z-10 flex flex-col items-center justify-center gap-4 bg-black font-mono text-xs uppercase tracking-[0.3em] text-white/60">
      <span>Loading NASA imagery</span>
      <div className="h-px w-48 bg-white/10">
        <div className="h-px bg-white/70" style={{ width: `${progress}%` }} />
      </div>
    </div>
  );
}

export default function Experience() {
  return (
    <main className="fixed inset-0 bg-black">
      <GlobeScene />
      <Loader />
      <p className="pointer-events-none fixed bottom-3 right-4 z-10 max-w-md text-right font-mono text-[10px] leading-relaxed text-white/35">
        NASA Blue Marble NG · VIIRS Black Marble · GEBCO · LRO / SVS CGI Moon Kit · SVS Deep Star Maps 2020 ·
        Hipparcos/Tycho
      </p>
    </main>
  );
}
