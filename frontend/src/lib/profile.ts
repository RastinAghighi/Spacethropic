import { SITES, type CandidateSite } from "./candidates";
import { targetById } from "./catalog";
import type { AnalogQuery, AnalogTarget } from "./search";

// Demo match model for the research loop. Everything here is indicative UI data so the
// refine → re-rank loop behaves sensibly end to end; the backend owns real per-cell
// profiles, similarity and constraint filtering.

export type Geology = "basalt" | "impact" | "sedimentary" | "evaporite" | "sulfate" | "ice";

export const GEOLOGY: Record<Geology, { label: string; short: string; note: string }> = {
  basalt: { label: "Basalt", short: "Basalt", note: "Volcanic flows, like the lunar maria" },
  impact: { label: "Impact breccia", short: "Breccia", note: "Shocked, brecciated crater rock" },
  sedimentary: { label: "Sedimentary", short: "Sediment", note: "Water-laid clays, mudstones, deltas" },
  evaporite: { label: "Evaporite", short: "Salts", note: "Salts left by drying brines" },
  sulfate: { label: "Sulfate · acid", short: "Sulfates", note: "Jarosite and hematite from acid water" },
  ice: { label: "Ground ice", short: "Ice", note: "Permafrost or buried ice" },
};
export const rockList = (gs: Geology[]) => gs.map((g, i) => (i ? GEOLOGY[g].short.toLowerCase() : GEOLOGY[g].short)).join(", ");

/** Left-rail drawers. */
export type Tab = "terrain" | "geology" | "thermal" | "weather" | "access";
/** Scored similarity dimensions, shown in the right pane. */
export type Dim = "terrain" | "geology" | "thermal" | "aridity" | "sun";

/** `metric` is the measured quantity each dimension is scored on, as shown in tables. */
export const DIMS: Record<Dim, { label: string; metric: string; tab: Tab }> = {
  terrain: { label: "Terrain", metric: "Slope", tab: "terrain" },
  geology: { label: "Geology", metric: "Rock", tab: "geology" },
  thermal: { label: "Thermal", metric: "Mean temp", tab: "thermal" },
  aridity: { label: "Aridity", metric: "Rainfall", tab: "weather" },
  sun: { label: "Illumination", metric: "Sunlight", tab: "weather" },
};
export const DIM_ORDER: Dim[] = ["terrain", "geology", "thermal", "aridity", "sun"];

/** Per-site traits the sample set doesn't carry yet. */
interface Traits {
  slope: number;
  roughness: number;
  geology: Geology[];
  roadKm: number;
  protectedArea: boolean;
  access: string;
}

const TRAITS: Record<string, Traits> = {
  "craters-of-the-moon": { slope: 6, roughness: 2.4, geology: ["basalt"], roadKm: 3, protectedArea: true, access: "Year-round; park permit for off-trail work" },
  "lava-beds": { slope: 5, roughness: 1.9, geology: ["basalt", "ice"], roadKm: 2, protectedArea: true, access: "Year-round; cave permits required" },
  lonar: { slope: 12, roughness: 1.6, geology: ["impact", "basalt"], roadKm: 1, protectedArea: true, access: "Oct–Mar; monsoon floods the floor" },
  pinacate: { slope: 9, roughness: 2.1, geology: ["basalt"], roadKm: 12, protectedArea: true, access: "Nov–Apr; summer exceeds 45 °C" },
  "kilbourne-hole": { slope: 8, roughness: 1.2, geology: ["basalt"], roadKm: 15, protectedArea: false, access: "Year-round by dirt road" },
  haughton: { slope: 7, roughness: 1.4, geology: ["impact", "ice"], roadKm: 160, protectedArea: false, access: "Jul–Aug only; charter flight from Resolute" },
  yungay: { slope: 4, roughness: 0.6, geology: ["evaporite", "sedimentary"], roadKm: 20, protectedArea: false, access: "Year-round" },
  "rio-tinto": { slope: 10, roughness: 1.8, geology: ["sulfate"], roadKm: 2, protectedArea: false, access: "Year-round; active mining district" },
  dallol: { slope: 3, roughness: 0.9, geology: ["evaporite", "sulfate"], roadKm: 30, protectedArea: false, access: "Nov–Feb; escort required" },
  dalangtan: { slope: 2, roughness: 0.5, geology: ["evaporite", "sulfate"], roadKm: 40, protectedArea: false, access: "May–Oct; 2,900 m altitude" },
  lut: { slope: 5, roughness: 3, geology: ["sedimentary"], roadKm: 110, protectedArea: true, access: "Oct–Mar; UNESCO site" },
  hanksville: { slope: 6, roughness: 1.5, geology: ["sedimentary"], roadKm: 8, protectedArea: false, access: "Oct–May; MDRS habitat on site" },
  bockfjord: { slope: 18, roughness: 2.8, geology: ["basalt", "ice"], roadKm: 400, protectedArea: true, access: "Jul–Aug by ship" },
};

export const traits = (s: CandidateSite) => TRAITS[s.id];

/** Indicative surface conditions at each Moon/Mars target. */
export interface TargetProfile {
  slope: number;
  geology: Geology[];
  meanTemp: number;
  solar: number;
}

const POLAR_MOON: TargetProfile = { slope: 15, geology: ["impact", "ice"], meanTemp: -150, solar: 1.5 };
const MARE: TargetProfile = { slope: 3, geology: ["basalt", "impact"], meanTemp: -20, solar: 10 };
const ICY_MARS: TargetProfile = { slope: 2, geology: ["ice", "sedimentary"], meanTemp: -70, solar: 2.4 };
const EQ_MARS: TargetProfile = { slope: 3, geology: ["basalt", "sulfate"], meanTemp: -50, solar: 3.2 };

const PROFILES: Record<string, TargetProfile> = {
  shackleton: POLAR_MOON,
  "connecting-ridge": { ...POLAR_MOON, slope: 10, meanTemp: -110, solar: 2.2 },
  "de-gerlache": { ...POLAR_MOON, slope: 12 },
  malapert: { ...POLAR_MOON, slope: 20, meanTemp: -100, solar: 2 },
  "marius-hills-pit": { ...MARE, slope: 5, geology: ["basalt"] },
  "apollo-15": { ...MARE, slope: 6, geology: ["basalt"] },
  "apollo-16": { ...MARE, slope: 8, geology: ["impact"] },
  "apollo-17": { ...MARE, slope: 7 },
  "apollo-11": { ...MARE, slope: 2, geology: ["basalt"] },
  jezero: { slope: 5, geology: ["sedimentary"], meanTemp: -50, solar: 3 },
  gale: { slope: 8, geology: ["sedimentary", "sulfate"], meanTemp: -48, solar: 3.2 },
  arcadia: ICY_MARS,
  phoenix: { ...ICY_MARS, slope: 1, geology: ["ice", "evaporite"], meanTemp: -80, solar: 2 },
  utopia: ICY_MARS,
  meridiani: { slope: 1, geology: ["sulfate", "evaporite"], meanTemp: -45, solar: 3.3 },
  "viking-1": EQ_MARS,
};

/** The searched place: a catalog target, or a dropped pin profiled by latitude. */
export function targetOf(q: AnalogQuery) {
  const t = q.place ? targetById(q.place) : undefined;
  if (t) return { name: t.name, short: t.short, profile: PROFILES[t.id] };
  const lat = Number(q.place?.split(":")[1]?.split(",")[0] ?? 0);
  const profile = q.target === "moon" ? (Math.abs(lat) > 80 ? POLAR_MOON : MARE) : Math.abs(lat) > 40 ? ICY_MARS : EQ_MARS;
  return { name: "Your pin", short: "your pin", profile };
}

// ── Numeric fields: drawer readouts and limit sliders ───────────────────────

export type NumKey = "slope" | "roughness" | "elevation" | "meanTemp" | "coldMin" | "precip" | "humidity" | "wind" | "solar" | "roadKm";

interface Field {
  label: string;
  unit: string;
  min: number;
  max: number;
  step: number;
  digits: number;
  /** sqrt spreads out the many sites bunched near zero */
  scale?: "sqrt";
  get: (s: CandidateSite) => number;
  /** Target-side value, when the target profile has one */
  target?: (p: TargetProfile) => number;
}

export const FIELDS: Record<NumKey, Field> = {
  slope: { label: "Slope", unit: "°", min: 0, max: 30, step: 1, digits: 0, get: (s) => traits(s).slope, target: (p) => p.slope },
  roughness: { label: "Roughness", unit: "m", min: 0, max: 4, step: 0.1, digits: 1, get: (s) => traits(s).roughness },
  elevation: { label: "Elevation", unit: "m", min: 0, max: 3500, step: 50, digits: 0, get: (s) => s.climate.elevationM },
  meanTemp: { label: "Mean temperature", unit: "°C", min: -30, max: 35, step: 1, digits: 1, get: (s) => s.climate.meanTempC, target: (p) => p.meanTemp },
  coldMin: { label: "Coldest-month low", unit: "°C", min: -60, max: 15, step: 1, digits: 1, get: (s) => s.climate.coldestMonthMinC },
  precip: { label: "Rainfall", unit: "mm/yr", min: 0, max: 1000, step: 10, digits: 0, scale: "sqrt", get: (s) => s.climate.precipMmYr, target: () => 0 },
  humidity: { label: "Humidity", unit: "%", min: 0, max: 100, step: 1, digits: 0, get: (s) => s.climate.humidityPct },
  wind: { label: "Wind", unit: "m/s", min: 0, max: 6, step: 0.1, digits: 1, get: (s) => s.climate.windMs },
  solar: { label: "Solar irradiance", unit: "kWh/m²·d", min: 0, max: 11, step: 0.1, digits: 1, get: (s) => s.climate.solarKwhM2Day, target: (p) => p.solar },
  roadKm: { label: "Nearest road", unit: "km", min: 0, max: 500, step: 5, digits: 0, scale: "sqrt", get: (s) => traits(s).roadKm },
};

export function formatField(key: NumKey, v: number) {
  const f = FIELDS[key];
  const n = v.toLocaleString(undefined, { minimumFractionDigits: f.digits, maximumFractionDigits: f.digits });
  return `${n.replace("-", "−")}${f.unit === "°" ? "°" : ` ${f.unit}`}`;
}

// ── Filters ─────────────────────────────────────────────────────────────────

export type Weight = 0 | 1 | 2;

export interface Filters {
  ranges: Partial<Record<NumKey, [number, number]>>;
  /** Require any of these rock types */
  geology: Geology[];
  weights: Record<Dim, Weight>;
  excludeProtected: boolean;
}

export const DEFAULT_FILTERS: Filters = {
  ranges: {},
  geology: [],
  weights: { terrain: 1, geology: 1, thermal: 1, aridity: 1, sun: 1 },
  excludeProtected: false,
};

export function sameFilters(a: Filters, b: Filters) {
  return JSON.stringify(normal(a)) === JSON.stringify(normal(b));
}
function normal(f: Filters) {
  const ranges = Object.fromEntries(Object.entries(f.ranges).sort(([x], [y]) => x.localeCompare(y)));
  return { ...f, ranges, geology: [...f.geology].sort() };
}

/** Which limits a site fails, if any. */
export function failures(s: CandidateSite, f: Filters): (NumKey | "geology" | "protected")[] {
  const out: (NumKey | "geology" | "protected")[] = [];
  for (const [k, r] of Object.entries(f.ranges) as [NumKey, [number, number]][]) {
    const v = FIELDS[k].get(s);
    if (v < r[0] || v > r[1]) out.push(k);
  }
  if (f.geology.length && !f.geology.some((g) => traits(s).geology.includes(g))) out.push("geology");
  if (f.excludeProtected && traits(s).protectedArea) out.push("protected");
  return out;
}
export const passes = (s: CandidateSite, f: Filters) => failures(s, f).length === 0;

/** Count of active limits per drawer, for the rail badges. */
export function limitsIn(tab: Tab, f: Filters) {
  let n = (Object.keys(f.ranges) as NumKey[]).filter((k) => FIELD_TAB[k] === tab).length;
  if (tab === "geology" && f.geology.length) n++;
  if (tab === "access" && f.excludeProtected) n++;
  return n;
}
export const FIELD_TAB: Record<NumKey, Tab> = {
  slope: "terrain",
  roughness: "terrain",
  elevation: "terrain",
  meanTemp: "thermal",
  coldMin: "thermal",
  precip: "weather",
  humidity: "weather",
  wind: "weather",
  solar: "weather",
  roadKm: "access",
};

function describeRange(k: NumKey, r?: [number, number]) {
  const f = FIELDS[k];
  if (!r) return `Any ${f.label.toLowerCase()}`;
  if (r[0] <= f.min) return `${f.label} ≤ ${formatField(k, r[1])}`;
  if (r[1] >= f.max) return `${f.label} ≥ ${formatField(k, r[0])}`;
  return `${f.label} ${formatField(k, r[0])}–${formatField(k, r[1])}`;
}

/** Readable list of everything the filters ask for. */
export function describeFilters(f: Filters) {
  const out = (Object.keys(f.ranges) as NumKey[]).map((k) => describeRange(k, f.ranges[k]));
  if (f.geology.length) out.push(f.geology.map((g) => GEOLOGY[g].label).join(" or "));
  if (f.excludeProtected) out.push("No protected areas");
  for (const d of DIM_ORDER) {
    if (f.weights[d] === 2) out.push(`Prioritise ${DIMS[d].label.toLowerCase()}`);
    if (f.weights[d] === 0) out.push(`Ignore ${DIMS[d].label.toLowerCase()}`);
  }
  return out;
}

/** Short label for a research step: what changed since the previous one. */
export function describeChange(prev: Filters, next: Filters) {
  const before = new Set(describeFilters(prev));
  const added = describeFilters(next).filter((d) => !before.has(d));
  const removed = (Object.keys(prev.ranges) as NumKey[]).filter((k) => !next.ranges[k]).map((k) => describeRange(k));
  const all = [...added, ...removed];
  if (!all.length) return "Refined";
  return all.length > 1 ? `${all[0]} +${all.length - 1}` : all[0];
}

// ── Scoring ─────────────────────────────────────────────────────────────────

const gauss = (d: number, sigma: number) => Math.exp(-((d / sigma) ** 2));

export interface DimMatch {
  dim: Dim;
  score: number;
  earth: string;
  target: string;
  /** Why it falls short, when it does */
  gap?: string;
  /** The same, in a few words */
  brief?: string;
}

/** Below this, a dimension is flagged as falling short. */
export const SHORT = 0.5;

export function matchProfile(s: CandidateSite, q: AnalogQuery): DimMatch[] {
  const { profile: p, short } = targetOf(q);
  const t = traits(s);
  const k = s.climate;
  const geoHit = p.geology.filter((g) => t.geology.includes(g));
  const rock = (gs: Geology[]) => gs.map((g) => GEOLOGY[g].label).join(" · ");
  const deg = (v: number) => `${Math.round(v).toString().replace("-", "−")} °C`;
  const dT = Math.round(k.meanTempC - p.meanTemp);

  const out: DimMatch[] = [
    {
      dim: "terrain",
      score: gauss(t.slope - p.slope, 8),
      earth: formatField("slope", t.slope),
      target: formatField("slope", p.slope),
      gap: t.slope < p.slope ? `Gentler than ${short}: ${t.slope}° slopes against ${p.slope}°.` : `Steeper than ${short}: ${t.slope}° slopes against ${p.slope}°.`,
      brief: t.slope < p.slope ? "slopes too gentle" : "slopes too steep",
    },
    {
      dim: "geology",
      score: Math.max(0.08, geoHit.length / p.geology.length),
      earth: rockList(t.geology),
      target: rockList(p.geology),
      gap: `No ${rock(p.geology.filter((g) => !t.geology.includes(g))).toLowerCase()} here.`,
      brief: `no ${rock(p.geology.filter((g) => !t.geology.includes(g))).toLowerCase()}`,
    },
    {
      dim: "thermal",
      score: gauss(dT, 45),
      earth: deg(k.meanTempC),
      target: deg(p.meanTemp),
      gap: `${Math.abs(dT)} °C ${dT > 0 ? "warmer" : "colder"} on average. Pair field work with a thermal-vacuum test.`,
      brief: `${Math.abs(dT)} °C ${dT > 0 ? "warmer" : "colder"}`,
    },
    {
      dim: "aridity",
      score: Math.exp(-k.precipMmYr / 350),
      earth: `${Math.round(k.precipMmYr)} mm`,
      target: "0 mm",
      gap: `${Math.round(k.precipMmYr)} mm of rain a year weathers the surface; ${short} has none.`,
      brief: `${Math.round(k.precipMmYr)} mm of rain a year`,
    },
    {
      dim: "sun",
      score: gauss(k.solarKwhM2Day - p.solar, 2.4),
      earth: `${k.solarKwhM2Day.toFixed(1)} kWh`,
      target: `${p.solar.toFixed(1)} kWh`,
      gap: k.solarKwhM2Day > p.solar ? "Far more sunlight than the target gets." : "Less sunlight than the target gets.",
      brief: k.solarKwhM2Day > p.solar ? "too much sun" : "too little sun",
    },
  ];
  return out.map((m) => (m.score < SHORT ? m : { ...m, gap: undefined, brief: undefined }));
}

export function overallScore(s: CandidateSite, q: AnalogQuery) {
  const w = (q.filters ?? DEFAULT_FILTERS).weights;
  const m = matchProfile(s, q);
  const total = m.reduce((a, d) => a + w[d.dim], 0);
  return total ? m.reduce((a, d) => a + d.score * w[d.dim], 0) / total : 0;
}

/** Less-studied sample sites, for "Unexplored only". */
const UNEXPLORED = ["lonar", "dalangtan", "lut", "dallol", "kilbourne-hole", "bockfjord", "rio-tinto"];

/** Every candidate the query could return before limits: right body, discovery respected. */
export function poolFor(q: AnalogQuery) {
  return SITES.filter((s) => s.targets.includes(q.target as AnalogTarget) && (!q.discovery || UNEXPLORED.includes(s.id)));
}

/** Demo ranking: physical match, weighted by the researcher's priorities, after hard limits. */
export function rank(q: AnalogQuery) {
  const f = q.filters ?? DEFAULT_FILTERS;
  return poolFor(q)
    .filter((s) => passes(s, f))
    .map((s) => ({ s, score: overallScore(s, q) }))
    .sort((a, b) => b.score - a.score)
    .map((r) => r.s);
}

// ── Suggestions: the tool proposes the next refine ─────────────────────────

export interface Suggestion {
  dim: Dim;
  /** Plain-language move, e.g. "Look for steeper ground" */
  title: string;
  /** Why, in target terms */
  reason: string;
  /** The limit it adds, for the trail */
  limit: string;
  filters: Filters;
  results: CandidateSite[];
  /** Dimension score at the site on screen, then at the new top result */
  before: number;
  after: number;
  /** Ranking value: the gain, less what it costs in overall match */
  value: number;
}

const MOVES: Partial<Record<Dim, { key: NumKey; up: string; down: string; reason: (p: TargetProfile, short: string) => string }>> = {
  terrain: { key: "slope", up: "Look for steeper ground", down: "Look for gentler ground", reason: (p, s) => `${cap(s)} has ~${p.slope}° slopes` },
  thermal: { key: "meanTemp", up: "Look somewhere warmer", down: "Look somewhere colder", reason: (p, s) => `${cap(s)} averages ${formatField("meanTemp", p.meanTemp)}` },
  aridity: { key: "precip", up: "Look somewhere wetter", down: "Look somewhere drier", reason: (_, s) => `${cap(s)} has never seen rain` },
  sun: { key: "solar", up: "Look for stronger sun", down: "Look for lower sun", reason: (p, s) => `${cap(s)} gets ~${formatField("solar", p.solar)}` },
};
const cap = (s: string) => s[0].toUpperCase() + s.slice(1);

/**
 * For each dimension the site on screen falls short on, try the limits that would push
 * toward the target and keep the one that most improves the next top result.
 */
export function suggest(q: AnalogQuery, site: CandidateSite, current: CandidateSite[]): Suggestion[] {
  const base = q.filters ?? DEFAULT_FILTERS;
  const { profile: p, short } = targetOf(q);
  const pool = poolFor(q);
  const now = matchProfile(site, q);
  const overallNow = overallScore(site, q);
  const same = (r: CandidateSite[]) => r.length === current.length && r.every((s, i) => s.id === current[i].id);
  const out: Suggestion[] = [];

  for (const m of now) {
    if (!m.gap || base.weights[m.dim] === 0) continue;
    const tries: { filters: Filters; limit: string; title: string; reason: string }[] = [];

    if (m.dim === "geology") {
      const need = p.geology.filter((g) => !traits(site).geology.includes(g));
      const filters = { ...base, geology: need };
      tries.push({ filters, limit: need.map((g) => GEOLOGY[g].label).join(" or "), title: `Find ${need.map((g) => GEOLOGY[g].label.toLowerCase()).join(" or ")}`, reason: `${cap(short)} is ${p.geology.map((g) => GEOLOGY[g].label.toLowerCase()).join(" and ")}` });
    } else {
      const mv = MOVES[m.dim]!;
      const f = FIELDS[mv.key];
      const v = f.get(site);
      const goal = mv.key === "precip" ? 0 : f.target!(p);
      const up = goal > v;
      // Thresholds at the values of the pool sites lying toward the target.
      const steps = [...new Set(pool.map(f.get).filter((x) => (up ? x > v : x < v)))];
      for (const x of steps) {
        const prev = base.ranges[mv.key] ?? [f.min, f.max];
        const r: [number, number] = up ? [Math.max(prev[0], Math.floor(x / f.step) * f.step), prev[1]] : [prev[0], Math.min(prev[1], Math.ceil(x / f.step) * f.step)];
        const filters = { ...base, ranges: { ...base.ranges, [mv.key]: r } };
        tries.push({ filters, limit: describeRange(mv.key, r[0] <= f.min && r[1] >= f.max ? undefined : r), title: up ? mv.up : mv.down, reason: mv.reason(p, short) });
      }
    }

    let best: Suggestion | null = null;
    for (const t of tries) {
      const nq = { ...q, filters: t.filters };
      const results = rank(nq);
      if (!results.length || same(results)) continue;
      const after = matchProfile(results[0], nq).find((d) => d.dim === m.dim)!.score;
      // The biggest gain for the least overall match given up, leaving a few sites to compare.
      const value = after - m.score + 0.8 * Math.min(0, overallScore(results[0], nq) - overallNow) + Math.min(results.length, 3) * 0.04;
      if (after - m.score > 0.12 && (!best || value > best.value)) {
        best = { dim: m.dim, title: t.title, reason: t.reason, limit: t.limit, filters: t.filters, results, before: m.score, after, value };
      }
    }
    if (best) out.push(best);
  }
  return out.sort((a, b) => b.value - a.value);
}
