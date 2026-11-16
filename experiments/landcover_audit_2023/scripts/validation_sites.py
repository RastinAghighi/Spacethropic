"""Validation sites for the prefilter check (task: does the filter keep analogs and drop non-analogs?).

Pure data, no imports, so both the audit venv (05, 06) and the regional-pilot venv (07) can load it.

Mission profiles (the global 0.05 deg filter is mission-agnostic; these say what each site is FOR):
  MARS_DRY   Mars dry surface: rover traverse, sedimentary / aeolian geology, hyperarid soils,
             crewed surface operations. Needs bare or sparsely vegetated ground, no ice cover.
  MARS_ICE   Mars cold-arid / ground-ice / brine: polar desert, permafrost, ice-cemented soil.
             Needs ice-free or ice-cored ground in a cold desert; vegetated tundra is not an analog.
  MOON_SURF  Lunar surface: regolith, basalt / tephra, impact terrain, rover mobility, ISRU.
             Needs bare ground.
  FIELD_GEO  Crew field-geology training or subsurface targets (impact structures, lava tubes)
             where surface vegetation does not stop the use (Apollo crews trained at Sudbury).
             A terrain prefilter that removes these is defensible for terrain matching but loses
             the site for this profile.

group:  analog    documented or team-chosen analog site
        negative  must be removed for every profile (forest, cropland, urban, ocean)
        probe     land the v2 rule keeps by design (grassland, savanna, tundra, ice sheet); tests
                  whether false positives reach the H3 database
region: radius_km around the point (default 10 km), or an explicit lat/lon box.
"""

R_DEFAULT_KM = 10.0

SITES = [
    # --- analogs named in the brief -------------------------------------------------------------
    dict(id="drumheller", group="analog", name="Drumheller badlands, Red Deer River valley, Alberta",
         lat=51.4714, lon=-112.72, box=(-112.80, 51.40, -112.60, 51.52),
         coord_source="Repo: regional_pilot README example point; region = NASADEM pilot study box "
                      "(research/nasadem_h3_pilot, W -112.80 S 51.40 E -112.60 N 51.52)",
         use="Team-chosen badlands terrain test area (NASADEM H3 pilot). The repo does not cite a "
             "NASA/CSA analog campaign here.",
         profiles=("MARS_DRY",)),
    dict(id="atacama_yungay", group="analog", name="Yungay, Atacama hyper-arid core, Chile",
         lat=-24.0638, lon=-69.8805,
         coord_source="pipeline/sites.yaml: Navarro-Gonzalez et al. 2003 study site (24 03'49.6\"S 69 52'49.8\"W)",
         use="Viking-style soil experiments; hyperarid Mars soil and life-detection analog",
         profiles=("MARS_DRY",)),
    dict(id="hanksville_mdrs", group="analog", name="Mars Desert Research Station, Hanksville, Utah",
         lat=38.4065, lon=-110.7919,
         coord_source="MDRS station (Atlas Obscura / Wikipedia 38.4065, -110.7919); frontend sample uses 38.41, -110.79",
         use="Crewed Mars surface-operations simulation; Morrison/Mancos sedimentary terrain",
         profiles=("MARS_DRY",)),
    dict(id="mauna_kea_summit", group="analog", name="Mauna Kea summit plateau, Hawaii",
         lat=19.8207, lon=-155.4681,
         coord_source="Mauna Kea summit (Wikipedia/GNIS 19 49'14.4\"N 155 28'05\"W, 4,205 m)",
         use="Lunar regolith / tephra analog; PISCES lunar ISRU field tests on Mauna Kea "
             "(Apollo Valley, ~12,000 ft, evaluated for the 2012 test)",
         profiles=("MOON_SURF",)),
    dict(id="mauna_kea_hale_pohaku", group="analog", name="Mauna Kea, Hale Pohaku (9,200 ft)",
         lat=19.7614, lon=-155.4561,
         coord_source="Onizuka Center / Visitor Information Station (Wikipedia 19 45'41\"N 155 27'22\"W, 2,800 m)",
         use="Elevation band of the 2010 ILSO-ISRU field test (~9,000 ft on Mauna Kea's slopes, "
             "Aerospace America 2010); exact test-site coordinates not published",
         profiles=("MOON_SURF",)),
    dict(id="mcmurdo_beacon", group="analog", name="Beacon Valley, McMurdo Dry Valleys, Antarctica",
         lat=-77.817, lon=160.650,
         coord_source="Beacon Valley (Wikipedia/GNIS 77 49'S 160 39'E)",
         use="Mars ground-ice and cold-desert analog (massive ground ice 10-60 cm below surface)",
         profiles=("MARS_ICE",)),
    dict(id="mcmurdo_don_juan", group="analog", name="Don Juan Pond, Wright Valley, McMurdo Dry Valleys",
         lat=-77.5644, lon=161.1722,
         coord_source="Don Juan Pond (Wikipedia 77 33'52\"S 161 10'20\"E; Toner et al. 2017)",
         use="Mars brine analog (perennially liquid CaCl2 pond); RSL slope-streak analog",
         profiles=("MARS_ICE",)),
    # --- analogs already in the repo (pipeline/sites.yaml, cited there) -------------------------
    dict(id="haughton", group="analog", name="Haughton impact crater, Devon Island",
         lat=75.383, lon=-89.667, coord_source="pipeline/sites.yaml (75 23'N 89 40'W)",
         use="Haughton-Mars Project: polar-desert impact crater, Moon/Mars", profiles=("MARS_ICE", "FIELD_GEO")),
    dict(id="black_point", group="analog", name="Black Point Lava Flow, Arizona (Desert RATS)",
         lat=35.6835, lon=-111.4786, coord_source="pipeline/sites.yaml (AZGS / NASA)",
         use="NASA Desert RATS simulated lunar missions on basalt", profiles=("MOON_SURF",)),
    dict(id="dumont", group="analog", name="Dumont Dunes, California",
         lat=35.6786, lon=-116.2316, coord_source="pipeline/sites.yaml (USGS GNIS)",
         use="Curiosity 'Scarecrow' rover mobility tests on dunes", profiles=("MARS_DRY",)),
    dict(id="sudbury", group="analog", name="Sudbury impact structure, Ontario",
         lat=46.600, lon=-81.183, coord_source="pipeline/sites.yaml (Earth Impact Database)",
         use="Apollo 16 crew impact-breccia training", profiles=("FIELD_GEO",)),
    # --- analogs from the frontend sample set (coordinates approximate, no citation in repo) ----
    dict(id="craters_of_the_moon", group="analog", name="Craters of the Moon, Idaho",
         lat=43.42, lon=-113.55, coord_source="frontend/src/data/candidates.json (approximate)",
         use="Basalt lava fields, Apollo 14 geology training; lava tubes", profiles=("MOON_SURF",)),
    dict(id="kilbourne_hole", group="analog", name="Kilbourne Hole maar, New Mexico",
         lat=31.97, lon=-106.97, coord_source="frontend/src/data/candidates.json (approximate)",
         use="Apollo astronaut training maar crater", profiles=("MOON_SURF",)),
    dict(id="pinacate", group="analog", name="Pinacate volcanic field, Sonora",
         lat=31.8, lon=-113.5, coord_source="frontend/src/data/candidates.json (approximate)",
         use="Apollo astronaut training, cinder cones and maars", profiles=("MOON_SURF",)),
    dict(id="lut", group="analog", name="Lut Desert yardangs, Iran",
         lat=30.4, lon=58.4, coord_source="frontend/src/data/candidates.json (approximate)",
         use="Aeolian yardang terrain", profiles=("MARS_DRY",)),
    dict(id="dalangtan", group="analog", name="Dalangtan playa, Qaidam Basin",
         lat=38.45, lon=91.9, coord_source="frontend/src/data/candidates.json (approximate)",
         use="Hyperarid cold salt playa, sulfates", profiles=("MARS_DRY",)),
    dict(id="dallol", group="analog", name="Dallol, Danakil Depression",
         lat=14.24, lon=40.3, coord_source="frontend/src/data/candidates.json (approximate)",
         use="Hydrothermal acid brines and evaporites", profiles=("MARS_DRY",)),
    dict(id="bockfjord", group="analog", name="Bockfjord volcanic complex, Svalbard",
         lat=79.45, lon=13.3, coord_source="frontend/src/data/candidates.json (approximate)",
         use="AMASE: Mars carbonate/volcanic analog in a polar setting", profiles=("MARS_ICE",)),
    dict(id="lava_beds", group="analog", name="Lava Beds National Monument, California",
         lat=41.71, lon=-121.51, coord_source="frontend/src/data/candidates.json (approximate)",
         use="Lava tubes (subsurface robotics)", profiles=("FIELD_GEO",)),
    dict(id="lonar", group="analog", name="Lonar crater, Maharashtra",
         lat=19.977, lon=76.508, coord_source="frontend/src/data/candidates.json (approximate)",
         use="Impact crater in basalt (lunar mare analog)", profiles=("FIELD_GEO",)),
    dict(id="rio_tinto", group="analog", name="Rio Tinto, Andalusia",
         lat=37.7, lon=-6.58, coord_source="frontend/src/data/candidates.json (approximate)",
         use="Acidic iron-sulfate river, jarosite (Mars aqueous mineralogy)", profiles=("FIELD_GEO",)),
    # --- negative controls: must be removed for every profile -----------------------------------
    dict(id="neg_amazon_forest", group="negative", name="Amazon rainforest, Brazil",
         lat=-4.6278, lon=-60.2194, coord_source="pipeline/sites.yaml rand_amazon (seeded random land point)",
         use="Dense evergreen broadleaf forest", profiles=()),
    dict(id="neg_iowa_cropland", group="negative", name="US Corn Belt, Iowa",
         lat=42.0, lon=-93.5, coord_source="Audit reference point (scripts/03_class_areas.py)",
         use="Cropland", profiles=()),
    dict(id="neg_urban_phoenix", group="negative", name="Downtown Phoenix, Arizona",
         lat=33.4484, lon=-112.0740, coord_source="Phoenix city centre (Wikipedia, approximate)",
         use="Urban area inside a desert", profiles=()),
    dict(id="neg_urban_cairo", group="negative", name="Central Cairo, Egypt",
         lat=30.0444, lon=31.2357, coord_source="Cairo city centre (Wikipedia, approximate)",
         use="Urban area on a desert margin", profiles=()),
    dict(id="neg_ocean_pacific", group="negative", name="Open Pacific Ocean",
         lat=0.0, lon=-150.0, coord_source="Audit reference point (scripts/03_class_areas.py)",
         use="Ocean", profiles=()),
    # --- probes: kept by the v2 class list by design --------------------------------------------
    dict(id="probe_konza_grassland", group="probe", name="Konza Prairie, Kansas",
         lat=39.083, lon=-96.583, coord_source="Konza Prairie Biological Station (Wikipedia 39 05'N 96 35'W)",
         use="Tallgrass prairie, grazed; not a Moon/Mars analog", profiles=()),
    dict(id="probe_serengeti_savanna", group="probe", name="Serengeti plains near Seronera, Tanzania",
         lat=-2.43, lon=34.82, coord_source="Seronera, Serengeti NP (approximate)",
         use="Savanna grassland; not a Moon/Mars analog", profiles=()),
    dict(id="probe_toolik_tundra", group="probe", name="Toolik Field Station, Alaska North Slope",
         lat=68.627, lon=-149.594, coord_source="Toolik Field Station (Wikipedia 68 38'N 149 36'W)",
         use="Vegetated Arctic tundra; not a terrain analog", profiles=()),
    dict(id="probe_concordia_ice", group="probe", name="Concordia Station, Dome C, East Antarctica",
         lat=-75.100, lon=123.333, coord_source="Concordia Station (Wikipedia 75 06'S 123 20'E)",
         use="Ice-sheet interior. ESA uses it as a crew-isolation analog, not a surface/terrain analog",
         profiles=()),
]

PROFILE_TEXT = {
    "MARS_DRY": "Mars dry surface (rover traverse, sedimentary/aeolian, hyperarid soil, crew ops)",
    "MARS_ICE": "Mars cold-arid / ground ice / brine",
    "MOON_SURF": "Lunar surface (regolith, basalt/tephra, rover mobility, ISRU)",
    "FIELD_GEO": "Field-geology training or subsurface target (vegetation tolerated)",
}
