# Prompt for Claude Code (run at C:\Dev\Spacethropic-integration)

We are implementing a minimal, defensible global Earth land-cover prefilter for
Spacethropic using real H3 resolution-8 cells. We have a separate regional
prototype in `experiments/global_filter/regional_pilot`; do not silently replace
the existing scripts. The global filter was copied from `data/cleaning` commit
`b073e8d` excluding `.git` and datasets. Target branch:
`feat/global-r8-filter`. Do not create or checkout any branches without first
reporting the current branch and whether files have uncommitted changes.

First read and summarize these actual files, including dependencies and function
names: `experiments/global_filter/README.md`,
`experiments/global_filter/pipeline/README.md`,
`experiments/global_filter/pipeline/AGENTS.md`,
`experiments/global_filter/pipeline/analysis/global_mask.py`,
`experiments/global_filter/pipeline/analysis/global_mask_download.py`.
Find every existing H3 grid script and elevation-r8 script. Run `git status
--short --branch`, inspect relevant test commands, and report reuse/bug risks.
Do not modify unrelated code, copy datasets, download large files, rewrite Git
history, commit, or push without explicit instruction.

Next compare the separate regional prototype with project conventions.
Preserve the old 0.05-degree mask as a reproducible baseline. Run existing tests
and `regional_pilot/tests` unit tests. If a suitable **existing local**
categorical GeoTIFF is available, run the pilot at `--ring 0`/`--ring 1` with
real source metadata to produce partitioned Parquet and a manifest; otherwise
report exactly what local asset is missing and run synthetic-only tests. Never
pretend synthetic land-cover values are observed satellite data.

Scientific rules: mission-specific 80% exclusion is configurable and uncalibrated;
keep all class percentages and unknown coverage, even for excluded cells. Do
not interpret `water` as `ocean` or `snow/ice` as `permanent ice` without an
additional source. Do not split Esri rangeland into shrub/grass without evidence.
Use `review` for incomplete/mixed cells. Do not upscale 500m MODIS into 10m
accuracy or conflate source publication with source observation dates.

After a small pilot passes, propose (do not start) a global tiled processing
architecture using coarse H3 parent partitions, raster COG window processing,
conservative coastal handling, Parquet partitions, provenance, polar/dateline QA,
and checks against Atacama, Haughton, Sudbury, deserts, volcanoes, coastal,
urban, forest and polar controls. No global processing or new downloads now.

Finally report inspected paths, findings, commands/tests and actual pass counts,
any files changed, remaining blockers and the next single highest-value action.
