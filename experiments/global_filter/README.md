# Spacethropic

NASA hackathon team repo.

## Layout

| Folder      | What                                   |
|-------------|----------------------------------------|
| `frontend/` | Next.js app (TypeScript, Tailwind, App Router) |
| `pipeline/` | Python data pipeline: analog calibration dataset on an H3 grid |

## Frontend

```bash
cd frontend
npm install
npm run dev   # http://localhost:3000
```

## Data pipeline

The pipeline builds the calibration dataset for the analog searcher. It pairs three historical
Earth analogs (Sudbury, Atacama, Haughton) with Moon/Mars counterparts. It then merges open
Earth, Moon and Mars data around each site into one complete feature table per H3 cell.

```bash
cd pipeline
uv sync
uv run python run.py all all
```

[pipeline/README.md](pipeline/README.md) has every aggregation rule, the data sources, and the
outputs, so the result can be reproduced exactly.
