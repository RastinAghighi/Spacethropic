# Spacethropic

NASA Space Apps 2026 entry: identify Earth analogs for Moon/Mars base and landing sites
([docs/challenge.md](docs/challenge.md)).

| Folder | What | Read first |
|---|---|---|
| `frontend/` | Next.js 16 globe + analog search UI (prototype; uses bundled sample sites) | [frontend/AGENTS.md](frontend/AGENTS.md): this Next.js version differs from training data |
| `pipeline/` | Python calibration dataset: Earth/Moon/Mars features on an H3 grid | [pipeline/AGENTS.md](pipeline/AGENTS.md): state, decisions, open questions, pitfalls |

- The user is learning as they build: design decisions are theirs, and their learning notes
  are in `.vibe-wise/`.
- Before changing a recorded decision, ask them.
- Never print or commit `pipeline/.env`.
- After every completed step, update `pipeline/AGENTS.md` and `pipeline/README.md` (user's
  standing rule).
