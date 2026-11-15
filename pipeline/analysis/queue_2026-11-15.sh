#!/usr/bin/env bash
# Run queue (user, 2026-11-15, reordered): Mars (240m, native), then Moon (240m done; native resumes), then Earth 4x -> 2x -> full.
# One job at a time so each gets all RAM. A short smoke test on each body runs first; if it
# fails the queue stops (and says so) instead of launching a broken full run.
set -u
cd "$(dirname "$0")/.."
PY=.venv/Scripts/python.exe
DEM=data/raw/global/planet
LOG=data/out/contours_planet/queue.log
mkdir -p data/out/contours_planet
say() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }

for body in mars moon; do
  f=$DEM/${body}_$([ $body = moon ] && echo lola118 || echo hrsc_mola200).tif
  say "waiting for $f"
  until [ -f "$f" ]; do sleep 30; done
  say "$body: smoke test (3 tiles)"
  if ! $PY -W ignore analysis/contours_planet.py --bodies $body --levels 240m --limit 3 --workers 3 \
        --out data/out/contours_planet/_smoke >> "$LOG" 2>&1; then
    say "QUEUE STOPPED: $body smoke test failed"; exit 1
  fi
  if grep -q "^${body}_" data/out/contours_planet/_smoke/${body}_240m_i20m/errors.txt 2>/dev/null; then
    say "QUEUE STOPPED: $body smoke test had tile errors"; exit 1
  fi
  say "$body: full run 240m,native"
  $PY -W ignore analysis/contours_planet.py --bodies $body --levels 240m,native --workers 15 >> "$LOG" 2>&1
  say "$body: finished (exit $?)"
done

say "earth: 4x,2x,full"
$PY -W ignore analysis/contours_r8.py --levels 4x,2x,full --workers 24 >> data/out/contours_r8_v2/run.log 2>&1
say "earth: finished (exit $?)"
