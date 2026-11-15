"use client";

import { useEffect, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";

/** GPU ms per frame above which we step resolution down (≈ can't hold 60 fps with headroom). */
const SLOW_MS = 13;
/** GPU ms below which there's room to step back up. */
const FAST_MS = 7;
const STEP = 0.25;
const MIN_DPR = 0.75;
const SAMPLE_EVERY = 20;
const COOLDOWN_MS = 1500;

type TimerExt = { TIME_ELAPSED_EXT: number; GPU_DISJOINT_EXT: number };

/**
 * Keeps the full-resolution render on capable GPUs and only trades pixels for frame
 * rate where the GPU genuinely can't keep up.
 *
 * It measures GPU time with timer queries rather than frame rate, because browsers
 * throttle requestAnimationFrame (battery saver, occluded windows) — a frame-rate
 * monitor would wrongly lower quality on a fast GPU. Where timer queries aren't
 * supported, resolution simply stays at the device ratio.
 */
export function AdaptiveResolution() {
  const gl = useThree((s) => s.gl);
  const setDpr = useThree((s) => s.setDpr);
  const maxDpr = useRef(1);
  const dpr = useRef(1);
  const ext = useRef<TimerExt | null>(null);
  const pending = useRef<WebGLQuery[]>([]);
  const active = useRef<WebGLQuery | null>(null);
  const samples = useRef<number[]>([]);
  const frame = useRef(0);
  const lastChange = useRef(0);

  useEffect(() => {
    const ctx = gl.getContext() as WebGL2RenderingContext;
    ext.current = ctx.getExtension("EXT_disjoint_timer_query_webgl2") as TimerExt | null;
    maxDpr.current = Math.min(window.devicePixelRatio || 1, 2);
    dpr.current = maxDpr.current;
  }, [gl]);

  // Open a query before the composer renders (priority 1)…
  useFrame(() => {
    const e = ext.current;
    if (!e || active.current || frame.current++ % SAMPLE_EVERY !== 0) return;
    const ctx = gl.getContext() as WebGL2RenderingContext;
    const q = ctx.createQuery();
    if (!q) return;
    ctx.beginQuery(e.TIME_ELAPSED_EXT, q);
    active.current = q;
  }, 0.5);

  // …close it after, and harvest finished results.
  useFrame(() => {
    const e = ext.current;
    if (!e) return;
    const ctx = gl.getContext() as WebGL2RenderingContext;
    if (active.current) {
      ctx.endQuery(e.TIME_ELAPSED_EXT);
      pending.current.push(active.current);
      active.current = null;
    }
    const disjoint = ctx.getParameter(e.GPU_DISJOINT_EXT);
    while (pending.current.length && ctx.getQueryParameter(pending.current[0], ctx.QUERY_RESULT_AVAILABLE)) {
      const q = pending.current.shift()!;
      if (!disjoint) samples.current.push(ctx.getQueryParameter(q, ctx.QUERY_RESULT) / 1e6);
      ctx.deleteQuery(q);
    }
    if (samples.current.length < 5) return;

    const sorted = [...samples.current].sort((a, b) => a - b);
    samples.current = [];
    const ms = sorted[sorted.length >> 1];
    const now = performance.now();
    if (now - lastChange.current < COOLDOWN_MS) return;

    let next = dpr.current;
    if (ms > SLOW_MS && dpr.current > MIN_DPR) next = Math.max(MIN_DPR, dpr.current - STEP);
    // Only step up if the higher ratio is predicted to stay under budget (cost ∝ pixels).
    else if (ms < FAST_MS && dpr.current < maxDpr.current) {
      const up = Math.min(maxDpr.current, dpr.current + STEP);
      if (ms * (up / dpr.current) ** 2 < SLOW_MS) next = up;
    }
    if (next !== dpr.current) {
      dpr.current = next;
      lastChange.current = now;
      setDpr(next);
    }
  }, 2);

  return null;
}
