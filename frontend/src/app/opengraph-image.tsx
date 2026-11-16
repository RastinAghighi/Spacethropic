import { ImageResponse } from "next/og";

export const alt =
  "Spacethropic: Earth analogs for the Moon and Mars, matched by terrain shape";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const BG = "#030406";
const MARS = "#d9774f";
const EARTH = "#a9bcc4";

// One wobbly closed contour: a circle of radius r perturbed by a few low harmonics.
function contour(r: number, phase: number, rot: number, cx: number, cy: number): string {
  const pts: string[] = [];
  const n = 72;
  for (let i = 0; i <= n; i++) {
    const t = (i / n) * Math.PI * 2;
    const k =
      1 +
      0.13 * Math.sin(2 * t + phase) +
      0.07 * Math.sin(3 * t + 1.7 * phase) +
      0.035 * Math.cos(5 * t + 0.4);
    const a = t + rot;
    pts.push(`${(cx + r * k * Math.cos(a)).toFixed(1)},${(cy + r * k * Math.sin(a)).toFixed(1)}`);
  }
  return `M${pts.join("L")}Z`;
}

// Elevation disk: nested contours that drift off-centre, like a crater bowl.
function Disk({ tint, rot, label }: { tint: string; rot: number; label: string }) {
  const R = 64;
  const c = R + 2;
  const rings = [0.82, 0.64, 0.47, 0.31, 0.16];
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 16 }}>
      <svg width={c * 2} height={c * 2} viewBox={`0 0 ${c * 2} ${c * 2}`}>
        <circle cx={c} cy={c} r={R} fill={tint} fillOpacity={0.06} stroke={tint} strokeOpacity={0.45} strokeWidth={1.25} />
        {rings.map((f, i) => {
          const dx = Math.cos(rot) * (1 - f) * 10;
          const dy = Math.sin(rot) * (1 - f) * 10;
          return (
            <path
              key={i}
              d={contour(R * f, 0.6 + i * 0.35, rot, c + dx, c + dy)}
              fill="none"
              stroke={tint}
              strokeOpacity={0.25 + i * 0.1}
              strokeWidth={1}
            />
          );
        })}
      </svg>
      <div
        style={{
          display: "flex",
          fontSize: 15,
          letterSpacing: 2.5,
          color: "rgba(255,255,255,0.42)",
          fontFamily: "monospace",
        }}
      >
        {label}
      </div>
    </div>
  );
}

export default function OpengraphImage() {
  // Planet limb: a large body mostly below/right of the frame.
  const PX = 1310;
  const PY = 1300;
  const PR = 960;

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          position: "relative",
          background: BG,
          color: "white",
        }}
      >
        <svg width={1200} height={630} viewBox="0 0 1200 630" style={{ position: "absolute", left: 0, top: 0 }}>
          <defs>
            <linearGradient id="rim" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="#ffffff" stopOpacity={0.7} />
              <stop offset="0.45" stopColor="#ffffff" stopOpacity={0.12} />
              <stop offset="1" stopColor="#ffffff" stopOpacity={0} />
            </linearGradient>
            <radialGradient id="body" cx="0.3" cy="0.2" r="0.9">
              <stop offset="0" stopColor="#0b0d10" />
              <stop offset="0.6" stopColor="#06070a" />
              <stop offset="1" stopColor={BG} />
            </radialGradient>
          </defs>
          <circle cx={PX} cy={PY} r={PR + 14} fill="none" stroke="#ffffff" strokeOpacity={0.035} strokeWidth={22} />
          <circle cx={PX} cy={PY} r={PR} fill="url(#body)" />
          <circle cx={PX} cy={PY} r={PR} fill="none" stroke="url(#rim)" strokeWidth={1.5} />
        </svg>

        <div
          style={{
            position: "absolute",
            left: 88,
            top: 72,
            display: "flex",
            fontSize: 16,
            letterSpacing: 3,
            color: "rgba(255,255,255,0.38)",
            fontFamily: "monospace",
          }}
        >
          NASA SPACE APPS 2026
        </div>

        <div
          style={{
            position: "absolute",
            left: 84,
            top: 196,
            display: "flex",
            flexDirection: "column",
          }}
        >
          <div style={{ display: "flex", fontSize: 96, letterSpacing: -3.5, lineHeight: 1, color: "rgba(255,255,255,0.96)" }}>
            Spacethropic
          </div>
          <div
            style={{
              display: "flex",
              marginTop: 26,
              marginLeft: 4,
              fontSize: 30,
              letterSpacing: -0.3,
              color: "rgba(255,255,255,0.55)",
            }}
          >
            Earth analogs for the Moon and Mars, matched by terrain shape
          </div>
        </div>

        <div
          style={{
            position: "absolute",
            left: 88,
            bottom: 64,
            display: "flex",
            alignItems: "flex-start",
            gap: 28,
          }}
        >
          <Disk tint={MARS} rot={0} label="MARS" />
          <div
            style={{
              display: "flex",
              height: 132,
              alignItems: "center",
              fontSize: 26,
              color: "rgba(255,255,255,0.3)",
            }}
          >
            ≈
          </div>
          <Disk tint={EARTH} rot={0.9} label="EARTH" />
        </div>
      </div>
    ),
    { ...size },
  );
}
