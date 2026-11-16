"use client";

import { useEffect, useState } from "react";
import { useUi } from "@/lib/ui";

/** Brief notice at the top centre, gone after a few seconds. */
export function Toast() {
  const { notice } = useUi();
  const [hidden, setHidden] = useState<number>(0);
  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setHidden(notice.seq), 5000);
    return () => clearTimeout(t);
  }, [notice]);
  const show = !!notice && hidden !== notice.seq;
  return (
    <div aria-live="polite" className="pointer-events-none fixed inset-x-0 top-6 z-40 flex justify-center px-4">
      {notice && (
        <div
          key={notice.seq}
          role="status"
          className="flex items-center gap-2.5 rounded-full border border-white/10 bg-[rgb(10_11_14/0.8)] py-2 pl-3 pr-4 text-[12.5px] text-white/85 shadow-[0_20px_50px_-20px_rgb(0_0_0/0.9)] backdrop-blur-xl"
          style={{
            opacity: show ? 1 : 0,
            transform: show ? "none" : "translateY(-8px)",
            transition: "opacity .4s ease, transform .5s var(--ease-out-expo)",
            animation: "rise-in .5s var(--ease-out-expo) both",
          }}
        >
          <span className="h-1.5 w-1.5 rounded-full bg-[#f3b453]" style={{ boxShadow: "0 0 8px #f3b453" }} />
          {notice.text}
        </div>
      )}
    </div>
  );
}
