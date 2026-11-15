import type { AnalogTarget } from "./search";

// The Moon and Mars places Mirror search can start from. UI data only: the backend owns the
// real per-cell profiles and scoring.

export const BODY: Record<AnalogTarget, { label: string; long: string; tint: string; texture: string }> = {
  moon: { label: "Moon", long: "the Moon", tint: "#cfd2d8", texture: "/textures/moon_4k.jpg" },
  // Solar System Scope 2k Mars map (CC BY 4.0, from NASA data); credited in Experience.
  mars: { label: "Mars", long: "Mars", tint: "#d9774f", texture: "/textures/mars_2k.jpg" },
};

export interface Target {
  id: string;
  body: AnalogTarget;
  name: string;
  /** Short name for chips */
  short: string;
  lat: number;
  lon: number;
  summary: string;
  source: string;
  /** Picker section */
  group: string;
}

export const TARGETS: Target[] = [
  // Moon: Artemis south pole first, then Apollo and the lava-tube skylight
  { id: "shackleton", body: "moon", name: "Shackleton crater", short: "Shackleton rim", lat: -89.67, lon: 129.78, summary: "21 km polar crater: near-continuous sunlight on the rim beside a permanently shadowed, ice-trapping floor.", source: "USGS Gazetteer of Planetary Nomenclature", group: "South pole · Artemis" },
  { id: "connecting-ridge", body: "moon", name: "Shackleton–de Gerlache ridge", short: "Connecting ridge", lat: -89.45, lon: -137, summary: "Some of the best-lit terrain at the south pole: a candidate for solar power and a long-duration base.", source: "Approximate ridge location", group: "South pole · Artemis" },
  { id: "de-gerlache", body: "moon", name: "de Gerlache crater", short: "de Gerlache rim", lat: -88.5, lon: -87.1, summary: "South-polar crater whose sunlit rim is an Artemis III candidate landing region.", source: "USGS Gazetteer of Planetary Nomenclature", group: "South pole · Artemis" },
  { id: "malapert", body: "moon", name: "Malapert massif", short: "Malapert massif", lat: -86, lon: 2.9, summary: "A ~5 km-high south-polar massif with good illumination and direct view of Earth.", source: "Approximate summit location", group: "South pole · Artemis" },
  { id: "marius-hills-pit", body: "moon", name: "Marius Hills pit", short: "Marius Hills pit", lat: 14.09, lon: -56.76, summary: "A ~65 m skylight in mare basalt, interpreted as an opening into an intact lava tube.", source: "Haruyama et al. 2009", group: "Lava tubes" },
  { id: "apollo-15", body: "moon", name: "Hadley–Apennine (Apollo 15)", short: "Hadley Rille", lat: 26.13, lon: 3.63, summary: "Mare basalt beside the sinuous Hadley Rille lava channel, at the foot of the Apennines.", source: "NASA NSSDCA", group: "Apollo landing sites" },
  { id: "apollo-16", body: "moon", name: "Descartes highlands (Apollo 16)", short: "Descartes highlands", lat: -8.97, lon: 15.5, summary: "Anorthositic, impact-brecciated highland crust; the crew trained at Sudbury.", source: "NASA NSSDCA", group: "Apollo landing sites" },
  { id: "apollo-17", body: "moon", name: "Taurus–Littrow (Apollo 17)", short: "Taurus–Littrow", lat: 20.19, lon: 30.77, summary: "A basalt-floored valley between highland massifs, with dark volcanic glass.", source: "NASA NSSDCA", group: "Apollo landing sites" },
  { id: "apollo-11", body: "moon", name: "Mare Tranquillitatis (Apollo 11)", short: "Tranquillity Base", lat: 0.67, lon: 23.47, summary: "Smooth mare basalt plain, the first crewed landing.", source: "NASA NSSDCA", group: "Apollo landing sites" },
  // Mars: astrobiology and ISRU sites
  { id: "jezero", body: "mars", name: "Jezero crater", short: "Jezero delta", lat: 18.38, lon: 77.58, summary: "An ancient lake delta rich in clays and carbonates; Perseverance's field site.", source: "USGS Gazetteer of Planetary Nomenclature", group: "Rover and lander sites" },
  { id: "gale", body: "mars", name: "Gale crater", short: "Gale crater", lat: -5.4, lon: 137.8, summary: "Lake mudstones and a layered sulfate-and-clay mound; Curiosity's field site.", source: "USGS Gazetteer of Planetary Nomenclature", group: "Rover and lander sites" },
  { id: "meridiani", body: "mars", name: "Meridiani Planum", short: "Meridiani Planum", lat: -1.95, lon: -5.53, summary: "Sulfate-rich sandstone with hematite concretions, recording acidic groundwater.", source: "Squyres et al. 2004", group: "Rover and lander sites" },
  { id: "viking-1", body: "mars", name: "Chryse Planitia (Viking 1)", short: "Chryse Planitia", lat: 22.48, lon: -47.97, summary: "Rocky basaltic plains where Viking's biology experiments found no soil organics.", source: "Published planetographic landing position", group: "Rover and lander sites" },
  { id: "arcadia", body: "mars", name: "Arcadia Planitia", short: "Arcadia Planitia", lat: 47.2, lon: -175.8, summary: "Mid-latitude plains with shallow, widespread excess ice; a leading human-landing candidate.", source: "Representative point in the excess-ice study area", group: "Ice-rich plains" },
  { id: "utopia", body: "mars", name: "Utopia Planitia", short: "Utopia Planitia", lat: 46.7, lon: 117.5, summary: "A vast northern plain with buried water ice and scalloped, polygonal terrain.", source: "Representative point in western Utopia", group: "Ice-rich plains" },
  { id: "phoenix", body: "mars", name: "Vastitas Borealis (Phoenix)", short: "Phoenix site", lat: 68.22, lon: -125.75, summary: "Arctic plains with polygonal ground, ice centimetres down and perchlorate salts.", source: "Smith et al. 2009", group: "Ice-rich plains" },
];

export const targetsFor = (body: AnalogTarget) => TARGETS.filter((t) => t.body === body);
export const targetById = (id: string) => TARGETS.find((t) => t.id === id);

export function formatLatLon(lat: number, lon: number, digits = 1) {
  const f = (v: number, p: string, n: string) => `${Math.abs(v).toFixed(digits)}°${v >= 0 ? p : n}`;
  return `${f(lat, "N", "S")} ${f(lon, "E", "W")}`;
}
