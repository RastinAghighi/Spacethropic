"use client";

import { useEffect, useRef, useState } from "react";
import type { AnalogTarget } from "@/lib/search";
import { BODY, type Target } from "@/lib/catalog";

// A small orthographic globe of the Moon or Mars, drawn with one fragment shader. The view is
// the lat/lon at the centre of the disc; hotspots are DOM buttons placed with the same projection.

const VERT = `attribute vec2 p; varying vec2 v; void main(){ v = p; gl_Position = vec4(p, 0., 1.); }`;
const FRAG = `
precision highp float;
varying vec2 v;
uniform sampler2D uTex;
uniform vec2 uView;   // centre lat, lon (radians)
uniform vec3 uSun;
uniform vec3 uTint;
uniform float uPx;    // one pixel in disc units
uniform float uAtmo;
void main() {
  vec2 p = v * 1.08;  // leave room for the halo
  float r = length(p);
  if (r > 1.0) {
    float g = exp(-(r - 1.0) * 26.0) * uAtmo;
    gl_FragColor = vec4(uTint * g, g);
    return;
  }
  vec3 n = vec3(p, sqrt(1.0 - r * r));
  float c = cos(uView.x), s = sin(uView.x);
  float y1 = n.y * c + n.z * s;
  float z1 = -n.y * s + n.z * c;
  float cl = cos(uView.y), sl = sin(uView.y);
  float x0 = n.x * cl + z1 * sl;
  float z0 = -n.x * sl + z1 * cl;
  float lat = asin(clamp(y1, -1.0, 1.0));
  float lon = atan(x0, z0);
  vec3 col = texture2D(uTex, vec2(lon / 6.2831853 + 0.5, 0.5 - lat / 3.1415927)).rgb;
  float lam = max(dot(n, uSun), 0.0);
  col *= 0.16 + 1.05 * pow(lam, 0.75);
  col += uTint * pow(1.0 - n.z, 4.0) * uAtmo * 0.55;
  float a = 1.0 - smoothstep(1.0 - uPx * 1.5, 1.0, r);
  gl_FragColor = vec4(col * a, a);
}`;

const SUN = (() => {
  const v = [-0.55, 0.42, 0.72];
  const l = Math.hypot(...v);
  return v.map((x) => x / l);
})();

export interface View {
  lat: number;
  lon: number;
}

const D = Math.PI / 180;

/** Screen position (unit disc, y up) of a lat/lon, or null when it's on the far side. */
export function project(view: View, lat: number, lon: number) {
  const φ = lat * D;
  const λ = lon * D;
  const x = Math.cos(φ) * Math.sin(λ);
  const y = Math.sin(φ);
  const z = Math.cos(φ) * Math.cos(λ);
  const cl = Math.cos(view.lon * D);
  const sl = Math.sin(view.lon * D);
  const x1 = x * cl - z * sl;
  const z1 = x * sl + z * cl;
  const c = Math.cos(view.lat * D);
  const s = Math.sin(view.lat * D);
  const y2 = y * c - z1 * s;
  const z2 = y * s + z1 * c;
  return { x: x1, y: y2, z: z2 };
}

/** Inverse of project for a point on the visible disc. */
export function unproject(view: View, px: number, py: number) {
  const r2 = px * px + py * py;
  if (r2 > 1) return null;
  const nz = Math.sqrt(1 - r2);
  const c = Math.cos(view.lat * D);
  const s = Math.sin(view.lat * D);
  const y1 = py * c + nz * s;
  const z1 = -py * s + nz * c;
  const cl = Math.cos(view.lon * D);
  const sl = Math.sin(view.lon * D);
  const x0 = px * cl + z1 * sl;
  const z0 = -px * sl + z1 * cl;
  return { lat: Math.asin(Math.max(-1, Math.min(1, y1))) / D, lon: Math.atan2(x0, z0) / D };
}

const textures = new Map<string, Promise<HTMLCanvasElement>>();

/** Downsampled copy of the body map: no mipmaps needed (they'd smear the ±180° seam). */
function loadMap(url: string) {
  let p = textures.get(url);
  if (!p) {
    p = new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => {
        const c = document.createElement("canvas");
        c.width = 1536;
        c.height = 768;
        c.getContext("2d")!.drawImage(img, 0, 0, c.width, c.height);
        resolve(c);
      };
      img.onerror = reject;
      img.src = url;
    });
    textures.set(url, p);
  }
  return p;
}

const hex = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
const easeOutExpo = (t: number) => (t >= 1 ? 1 : 1 - 2 ** (-10 * t));

export function MirrorLens({
  body,
  sites,
  selected,
  pin,
  spinning,
  onSelect,
  onPin,
  size = 208,
}: {
  body: AnalogTarget;
  sites: Target[];
  selected: string;
  pin: View | null;
  spinning: boolean;
  onSelect: (id: string) => void;
  onPin: (p: View) => void;
  size?: number;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const spots = useRef<Map<string, HTMLElement>>(new Map());
  const pinEl = useRef<HTMLDivElement>(null);
  const view = useRef<View>({ lat: 0, lon: 0 });
  const goal = useRef<{ from: View; to: View; t0: number } | null>(null);
  const drag = useRef<{ x: number; y: number; moved: boolean; view: View } | null>(null);
  const kick = useRef<() => void>(() => {});
  const props = useRef({ spinning, pin });
  const [grabbing, setGrabbing] = useState(false);
  useEffect(() => {
    props.current = { spinning, pin };
  }, [spinning, pin]);

  // Renderer: one context per lens, redrawn only while something moves.
  useEffect(() => {
    const el = canvas.current!;
    const gl = el.getContext("webgl", { premultipliedAlpha: true, alpha: true, antialias: false })!;
    if (!gl) return;
    const sh = (type: number, src: string) => {
      const s = gl.createShader(type)!;
      gl.shaderSource(s, src);
      gl.compileShader(s);
      return s;
    };
    const prog = gl.createProgram()!;
    gl.attachShader(prog, sh(gl.VERTEX_SHADER, VERT));
    gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FRAG));
    gl.linkProgram(prog);
    gl.useProgram(prog);
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, "p");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    const u = (n: string) => gl.getUniformLocation(prog, n);
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.uniform3fv(u("uSun"), SUN);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);

    let raf = 0;
    let last = performance.now();
    let ready = false;
    let alive = true;

    const place = () => {
      const half = size / 2;
      const r = half / 1.08;
      const v = view.current;
      spots.current.forEach((node, key) => {
        const [lat, lon] = key.split(",").slice(1).map(Number);
        const q = project(v, lat, lon);
        const on = q.z > 0.04;
        node.style.transform = `translate(${half + q.x * r}px, ${half - q.y * r}px)`;
        node.style.opacity = on ? String(Math.min(1, q.z * 4)) : "0";
        node.style.pointerEvents = on ? "auto" : "none";
      });
      const pp = props.current.pin;
      if (pinEl.current) {
        const q = pp ? project(v, pp.lat, pp.lon) : null;
        pinEl.current.style.opacity = q && q.z > 0 ? "1" : "0";
        if (q) pinEl.current.style.transform = `translate(${half + q.x * r}px, ${half - q.y * r}px)`;
      }
    };

    const frame = (now: number) => {
      raf = 0;
      if (!alive) return;
      const dt = Math.min((now - last) / 1000, 0.1);
      last = now;
      let moving = false;
      if (goal.current) {
        const { from, to, t0 } = goal.current;
        const t = easeOutExpo((now - t0) / 1100);
        let dl = to.lon - from.lon;
        dl = ((dl + 540) % 360) - 180;
        view.current = { lat: from.lat + (to.lat - from.lat) * t, lon: from.lon + dl * t };
        if (t >= 1) goal.current = null;
        moving = true;
      } else if (props.current.spinning && !drag.current) {
        view.current = { ...view.current, lon: view.current.lon + dt * 9 };
        moving = true;
      }
      if (ready) {
        gl.uniform2f(u("uView"), view.current.lat * D, view.current.lon * D);
        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      }
      place();
      if (moving || drag.current) raf = requestAnimationFrame(frame);
    };
    kick.current = () => {
      if (!raf) {
        last = performance.now();
        raf = requestAnimationFrame(frame);
      }
    };

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    el.width = el.height = Math.round(size * dpr);
    gl.viewport(0, 0, el.width, el.height);
    gl.uniform1f(u("uPx"), 2 / (size * dpr));

    const tint = hex(BODY[body].tint);
    gl.uniform3fv(u("uTint"), tint);
    gl.uniform1f(u("uAtmo"), body === "mars" ? 0.75 : 0.22);
    el.style.opacity = "0";
    loadMap(BODY[body].texture).then((img) => {
      if (!alive) return;
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, img);
      ready = true;
      el.style.opacity = "1";
      kick.current();
    });
    kick.current();

    return () => {
      alive = false;
      cancelAnimationFrame(raf);
      // Free GPU objects but keep the context: a canvas only ever gets one, and effects can re-run.
      gl.deleteTexture(tex);
      gl.deleteBuffer(buf);
      gl.deleteProgram(prog);
    };
  }, [body, size]);

  // Turn to the selected site.
  useEffect(() => {
    const s = sites.find((x) => x.id === selected);
    const to = s ? { lat: s.lat, lon: s.lon } : pin;
    if (!to) return;
    goal.current = { from: { ...view.current }, to: { lat: Math.max(-80, Math.min(80, to.lat)), lon: to.lon }, t0: performance.now() };
    kick.current();
  }, [selected, sites, pin]);

  useEffect(() => {
    if (spinning) kick.current();
  }, [spinning]);

  const toDisc = (e: React.PointerEvent) => {
    const r = canvas.current!.getBoundingClientRect();
    return { x: (((e.clientX - r.left) / r.width) * 2 - 1) * 1.08, y: -(((e.clientY - r.top) / r.height) * 2 - 1) * 1.08 };
  };

  return (
    <div className="relative shrink-0 select-none" style={{ width: size, height: size }}>
      <canvas
        ref={canvas}
        className="absolute inset-0 h-full w-full touch-none"
        style={{ cursor: grabbing ? "grabbing" : "grab", transition: "opacity .7s ease" }}
        aria-label={`${BODY[body].label} globe: drag to turn, click to drop a pin`}
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId);
          goal.current = null;
          drag.current = { x: e.clientX, y: e.clientY, moved: false, view: { ...view.current } };
          kick.current();
        }}
        onPointerMove={(e) => {
          const d = drag.current;
          if (!d) return;
          const dx = e.clientX - d.x;
          const dy = e.clientY - d.y;
          if (!d.moved && Math.hypot(dx, dy) > 3) {
            d.moved = true;
            setGrabbing(true);
          }
          const k = 180 / Math.PI / (size / 2 / 1.08);
          view.current = { lat: Math.max(-89, Math.min(89, d.view.lat + dy * k)), lon: d.view.lon - dx * k };
        }}
        onPointerUp={(e) => {
          const d = drag.current;
          drag.current = null;
          setGrabbing(false);
          if (d && !d.moved) {
            const p = toDisc(e);
            const ll = unproject(view.current, p.x, p.y);
            if (ll) onPin(ll);
          }
        }}
      />
      {sites.map((s) => {
        const on = s.id === selected;
        return (
          <button
            key={`${s.id},${s.lat},${s.lon}`}
            ref={(el) => {
              const k = `${s.id},${s.lat},${s.lon}`;
              if (el) spots.current.set(k, el);
              else spots.current.delete(k);
            }}
            type="button"
            onClick={() => onSelect(s.id)}
            aria-label={s.name}
            title={s.name}
            className="group absolute left-0 top-0 -ml-3 -mt-3 flex h-6 w-6 items-center justify-center focus-visible:outline-none"
            style={{ opacity: 0, transition: "opacity .25s" }}
          >
            <span className="absolute h-3 w-3 rounded-full border border-white/70" style={{ animation: on ? "ping-ring 1.8s var(--ease-out-expo) infinite" : undefined }} />
            <span
              className={`relative rounded-full bg-white shadow-[0_0_8px_rgb(255_255_255/0.8)] transition-all duration-300 group-hover:scale-150 group-focus-visible:scale-150 ${on ? "h-2 w-2" : "h-[5px] w-[5px] opacity-80"}`}
            />
          </button>
        );
      })}
      <div ref={pinEl} className="pointer-events-none absolute left-0 top-0" style={{ opacity: 0 }}>
        <svg width="18" height="24" viewBox="0 0 18 24" className="-ml-[9px] -mt-[22px] drop-shadow-[0_2px_6px_rgb(0_0_0/0.6)]" aria-hidden>
          <path d="M9 23s7-8.2 7-13.5A7 7 0 002 9.5C2 14.8 9 23 9 23z" fill="white" />
          <circle cx="9" cy="9.5" r="2.6" fill={BODY[body].tint} />
        </svg>
      </div>
    </div>
  );
}
