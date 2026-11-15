# DuckDB candidate metadata benchmark

Run from the pilot root using its Windows virtual environment. DuckDB 2.0.0 is
pinned in the existing dependency setup. No raw NASADEM ZIP, eligibility mask,
network data or 3D matcher is used.

## Reproduce

From the repository root:

```powershell
cd research/nasadem_h3_pilot
.\.venv\Scripts\python -m pip install -r requirements-lock.txt
.\.venv\Scripts\python -m pip install --no-deps -e .
.\.venv\Scripts\python -m spacethropic.benchmark `
  --directory benchmarks/my_run_01 `
  --rows 100000 1000000 4000000 `
  --seed 20261114 --repeats 3 --memory 2GB --threads 4
```

Choose a **new directory** each time. The command refuses an existing root. The
default row counts, seed, repeats, memory and threads equal those above. A smaller
smoke run can use `--rows 1000 --repeats 1`. Every requested size is built in its
own database, without carrying smaller datasets forward. The command attempts
later sizes even if a size fails, and returns nonzero if any scale fails. Each
stage has a 900-second subprocess timeout.

All outputs live under the chosen root (ignored by Git):

```text
results.json                 machine/settings, CLI baseline, per-size metrics
baseline/                    fresh real CLI database, exports and command logs
100000/                      independent synthetic database
  terrain.duckdb
  synthetic_cells.csv        generated H3 IDs/centres, not real observations
  candidates.parquet         final export (earlier repeat exports replaced)
  setup.json / query.json / export.json / read.json / verify.json
  *.log                      subprocess stdout/stderr, including failures
  *_temp/                    dedicated DuckDB spill directories
1000000/                     same layout
4000000/                     same layout
```

The existing `local/terrain.duckdb` and `local/candidates_res*.parquet` are never
opened by the benchmark. A failed process may leave partial benchmark artifacts;
retain them for diagnosis and use a new root when rerunning.

## Fresh pilot baseline

The benchmark launches the existing `spacethropic.db_cli` in separate processes
to import both checked-in pairs, list runs, and export each resolution. It checks
12/296 output rows, unique cells, 311,040 samples per run and complete/partial
counts of 1/11 and 220/76. Baseline timings are end-to-end CLI wall time, including
Python startup, connections and JSON output. These tiny baseline timings should
not be directly compared to the internal scale-stage timings.

The equivalent manual commands, from the pilot root, are:

```powershell
$b = 'benchmarks/manual_baseline_01'
New-Item -ItemType Directory -Path $b -ErrorAction Stop
$a = 'outputs/n51w113_drumheller_badlands_h3'
.\.venv\Scripts\python -m spacethropic.db_cli --database "$b/terrain.duckdb" import `
  --pair "$a/h3_res6_cells.csv" "$a/h3_res6_run_summary.json" `
  --pair "$a/h3_res8_cells.csv" "$a/h3_res8_run_summary.json"
.\.venv\Scripts\python -m spacethropic.db_cli --database "$b/terrain.duckdb" list-runs
$r6 = '37242be6a6dc92a78a4eb8000a01b57396bf5348ac0cb7f0094954d4a7dfc1be'
$r8 = '4ee8d757010c811d6a903d11343c47dddf8d26ec158b71430202d7ef970e36d0'
.\.venv\Scripts\python -m spacethropic.db_cli --database "$b/terrain.duckdb" export `
  --run-id $r6 --resolution 6 --output "$b/candidates_res6.parquet"
.\.venv\Scripts\python -m spacethropic.db_cli --database "$b/terrain.duckdb" export `
  --run-id $r8 --resolution 8 --output "$b/candidates_res8.parquet"
```

## Workload and measurement definitions

- **Production path:** `database.candidate_relation()` contains the existing CLI's
  selection SQL. Both the CLI Parquet writer and benchmark use this function.
  There is no new filter interface: full selection includes partial cells. The
  current interface supports no filtered candidate query, so none is reported.
- **Synthetic schema:** the generator calls production `initialize()`, preserving
  tables, types, primary/foreign keys and indexes. It bulk-loads real, unique res-6
  H3 IDs with real centres/pentagon flags, enumerated in sorted base-cell/child
  order. Features, areas, sample counts and source metadata are artificial. The
  seed controls arithmetic pseudorandom features, independent of scan/thread order.
  Twenty percent of rows are complete; the rest have varied partial coverage;
  pixel-centre coverage may exceed one. All synthetic provenance is explicitly
  `SYNTHETIC_BENCHMARK`, with a synthetic source reference. Eligibility stays unknown.
- **Scope:** this is schema and serving-capacity testing. Synthetic areas are not
  geodetically derived, feature columns are correlated and compressible, IDs are
  geographically ordered, and there is one run/source. This does not simulate an
  actual global land distribution or production data entropy. Bulk setup bypasses
  the real CSV importer/validation; it does not establish global ingestion speed.
- **Setup:** separate ID/CSV generation and SQL bulk-load/checkpoint timings. Total
  setup also includes schema creation. Source staging CSVs and final DB sizes are
  recorded. Setup is outside query/export/read measurements.
- **Query:** a new process/connection runs the shared candidate SELECT, including
  joins, provenance and sorting. Every column of every row is fetched into Python
  batches of 4,096 and discarded, bounding client memory. Timing includes binding,
  execution, transfer and Python conversion. It is not a COUNT(*) benchmark.
- **Export:** a separate fresh process uses production `export_parquet()`, including
  run validation, selection, sorting, Zstandard compression and filesystem write.
  Its own previous repeat output is removed outside timing; the final file stays.
  There is no explicit storage-device cache flush/fsync durability measurement.
- **Read:** another fresh process scans every Parquet column, fetching all rows in
  Python batches. It measures decoding/transfer, not just footer metadata.
- **Repeats:** each measured stage runs once, then three repeats on the same
  connection. Reports show first, median of repeats (excluding first), and slowest
  across all four. First means **fresh process**, not cold OS cache. Database setup,
  earlier stages and export writes can populate Windows filesystem caches.
  Connection and subprocess wall times are stored separately. No concurrent scale
  workers are launched.
- **Validation:** a final separate process checks database/export total and unique
  cell counts and performs bidirectional EXCEPT across all 35 original fields plus
  run ID. Counts/EXCEPT are correctness checks outside performance timings.
- **Peak memory:** Windows PSAPI `GetProcessMemoryInfo`, process-lifetime
  `PeakWorkingSetSize` and `PeakPagefileUsage`, in bytes. The former is resident
  working set; the latter is the API's process commit/pagefile-usage high water,
  not measured physical swap traffic. Includes Python, DuckDB and client batches;
  excludes other processes and OS file cache. A 2GB DuckDB memory limit does not
  cap total process memory. Each stage has its own process lifetime.
- **Temporary disk:** dedicated stage spill directory sampled every 100ms by a
  Python thread. Reported peak is a sampled lower bound; short-lived files and
  periods when the sampling thread is delayed may be missed. Zero means no spill
  observed, not proof that none occurred. Temp cap is 8GB per connection. DB,
  staging CSV and Parquet sizes are recorded separately from spill.

## Tests

```powershell
.\.venv\Scripts\python -m pytest tests/test_benchmark.py tests/test_database.py -q
.\.venv\Scripts\python -m pytest -q
```

Tests cover seeded reproducibility, valid unique H3 cells, production-schema
selection, fresh real CLI baseline, every benchmark stage, export content and
directory isolation. Large runs remain explicit commands, not routine tests.

## Measured results

See the checked-in results discussion below; the complete machine-readable data
for the recorded run is in the ignored `benchmarks/terrain_scale_v1/results.json`.

Recorded November 14, 2026 on `feat/terrain-database`, based on commit
`105758f8d2091098c92309275e8ee381598866ef` plus the uncommitted database milestone
and benchmark changes. Windows 11 build 26300, Intel Core i9-13900H (20 logical
processors), 16,791,257,088 bytes RAM (15.64 GiB), about 738 GiB free on C: before
the run. Python 3.12.10, DuckDB 2.0.0, h3-py 4.5.0. Four DuckDB threads, 2GB engine
memory limit, 8GB temporary-disk cap, 4,096-row client batches, Zstandard Parquet.
No OS cache flush or machine-idle guarantee. Scale stages ran sequentially with
no concurrent benchmark/test workers. Storage model and Windows power policy
were not captured, so comparisons should control those separately.

Fresh CLI baseline: both-pair import **1.050 s**, list runs **0.256 s**, res-6
export **0.248 s** (12 rows, 10,949 bytes), res-8 export **0.259 s** (296 rows,
48,608 bytes). Each run had 311,040 samples; complete/partial counts were 1/11
and 220/76 respectively. These are single CLI measurements, not repeat medians.

All three independent sizes completed; no size failed. Exactly 100,000,
1,000,000 and 4,000,000 unique cells were exported, respectively. Both database
and Parquet uniqueness checks passed, with zero bidirectional content differences.

Setup and stored sizes (MiB = 1,048,576 bytes):

| Observations / actual output rows | Setup s | ID generation s | Bulk load/checkpoint s | DB MiB | Staging CSV MiB | Parquet bytes |
|---:|---:|---:|---:|---:|---:|---:|
| 100,000 | 1.011 | 0.249 | 0.757 | 33.01 | 6.22 | 11,693,316 |
| 1,000,000 | 7.605 | 2.467 | 5.132 | 289.01 | 63.63 | 116,029,335 |
| 4,000,000 | 33.987 | 10.493 | 23.473 | 1143.26 | 258.78 | 463,616,767 |

Stage timings in seconds: **first / repeat median / slowest of all four**.

| Rows | Full candidate query + Python fetch | Full Parquet export | Full Parquet read + Python fetch |
|---:|---|---|---|
| 100,000 | 0.425 / 0.430 / 0.466 | 0.268 / 0.270 / 0.282 | 0.358 / 0.353 / 0.358 |
| 1,000,000 | 3.588 / 3.735 / 3.850 | 1.500 / 1.600 / 1.812 | 3.056 / 3.102 / 3.119 |
| 4,000,000 | 25.126 / 24.885 / 25.657 | 15.867 / 18.461 / 19.101 | 12.764 / 12.702 / 12.769 |

PSAPI peak working set, MiB; these are stage-process lifetime peaks, not per-repeat
peaks. Verification is separate from the performance stages.

| Rows | Setup | Query | Export | Read | Verification |
|---:|---:|---:|---:|---:|---:|
| 100,000 | 168.9 | 227.2 | 270.3 | 112.8 | 204.6 |
| 1,000,000 | 567.8 | 1442.2 | 1944.1 | 344.3 | 1421.5 |
| 4,000,000 | 1979.7 | 2065.3 | 2104.0 | 552.5 | 2114.7 |

No spill was observed at 100k or 1M. At 4M, sampled temporary-disk peaks were
**1720.2 MiB query**, **1886.6 MiB export**, and **2278.0 MiB verification**.
No spill was observed during setup or Parquet reading. These are sampled lower
bounds; the machine-readable report also records process commit high water.

At 4M, setup (33.987 s) was the longest single operation, with bulk loading taking
23.473 s. Among serving operations, full candidate retrieval was slowest
(24.885 s repeat median); it includes all-column Python materialization. Query
also took the largest cumulative worker time across its four measurements
(100.877 s including process startup). The 1M-to-4M increase was nonlinear and
coincided with spilling under the configured memory limit. This is evidence of
memory pressure in this workload, not proof that spill alone caused the slowdown.

The three existing `local/` artifacts had identical SHA-256 before and after the
benchmark. They were not used as benchmark inputs. Database regression tests and
small benchmark tests are separate from the measured scale processes.

Final verification: focused database/benchmark tests **16 passed**; full pilot
suite **92 passed, 5 skipped** (26.02 s; unavailable raw-ZIP and optional Rasterio
checks). `git diff --check` passed. The generated root, staging CSVs, DuckDB files,
Parquet exports, logs and JSON measurements are ignored by Git.

## What this does not establish

Once the search engine is connected, measure actual selectivity, candidate
limits/top-k ranking, spatial restrictions, multiple terrain runs/sources,
real eligibility-mask joins, realistic NULLs/feature entropy, and query plans.
Measure the search team's actual client format (Python tuples versus Arrow or
another transport), network/API transfer, concurrent users, cold filesystem
caches, machine power/storage settings, and sustained memory/disk budgets.
Elevation-patch retrieval, normalization, matcher compute and result ranking
remain unmeasured. The current timings are local metadata throughput, not analog
search latency, terrain-processing throughput or global-ingestion throughput.
