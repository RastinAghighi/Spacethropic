# Spacethropic

NASA Space Apps 2026 entry: identify Earth analogs for Moon/Mars base and landing sites
([docs/challenge.md](docs/challenge.md)).

| Folder | What | Read first |
|---|---|---|
| `frontend/` | Next.js 16 globe + analog search UI (prototype; uses bundled sample sites) | [frontend/AGENTS.md](frontend/AGENTS.md): this Next.js version differs from training data |
| `pipeline/` | Python calibration dataset: Earth/Moon/Mars features on an H3 grid | [pipeline/AGENTS.md](pipeline/AGENTS.md): state, decisions, open questions, pitfalls |
| `regional_pilot/` | Configurable H3 land-cover pilot (`pilot.py`, default r7) | [regional_pilot/README.md](regional_pilot/README.md): input contract, separate mission policy |
| `global_r7/` | Global r7 geographic filter and optional local DEM contours | [global_r7/README.md](global_r7/README.md); [run report](global_r7/RUN_REPORT.md), MODIS transfer still required |

2026-11-15: `regional_pilot` now takes `--resolution`, default 7; explicit r8 is
supported. The global pipeline preserves the v2 MODIS-only policy, marks uncertainty,
and processed 95 observed regional cells (86 candidates). Public global inputs are
ready; full MODIS/global execution remains pending.

- The user is learning as they build: design decisions are theirs, and their learning notes
  are in `.vibe-wise/`.
- Before changing a recorded decision, ask them.
- Never print or commit `pipeline/.env`.
- After every completed step, update `pipeline/AGENTS.md` and `pipeline/README.md` (user's
  standing rule).
