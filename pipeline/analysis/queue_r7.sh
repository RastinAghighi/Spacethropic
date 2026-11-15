#!/usr/bin/env bash
# R7 queue (user, 2026-11-15): the same jobs as R8, at H3 r7 hexagon size (Earth's mean r7 cell,
# 5.16 km^2, applied 1:1 to the Moon and Mars), for Earth 8x, Moon 240m and Mars 240m only.
# Starts after the R8 zip queue finishes. One body at a time per job (user order). Each job stops
# the queue if it fails; contours must reach status "complete" before any feature runs on them.
set -u
cd "$(dirname "$0")/.."
export HEX_RES=7
PY=.venv/Scripts/python.exe
LOG=data/interim/global/queue_r7.log
MIN_FREE_GB=15   # feature scripts have no disk guard of their own
say() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }
free_gb() { df -BG --output=avail /c | tail -1 | tr -dc 0-9; }
need_disk() { [ "$(free_gb)" -ge $MIN_FREE_GB ] || { say "STOP before $1: only $(free_gb) GB free (need $MIN_FREE_GB)"; exit 1; }; }
step() { local name=$1; shift; need_disk "$name"; say "$name: start"; "$@" >> "$LOG" 2>&1; local rc=$?; say "$name: exit $rc; $(free_gb) GB free"; [ $rc -eq 0 ] || exit $rc; }
complete() { $PY -c "import json,sys; sys.exit(json.load(open('$1/manifest.json'))['status'] != 'complete')" || { say "STOP: $1 not complete (paused for disk?); rerun the contour step"; exit 1; }; }

say "waiting for the R8 zip queue to finish"
until grep -q "zip queue: finished" data/export/zip_single.log; do sleep 60; done

E=data/out/contours_r7_v2/8x_i20m; M=data/out/contours_planet_r7/moon_240m_i20m; R=data/out/contours_planet_r7/mars_240m_i20m
step "contours earth" $PY -W ignore analysis/contours_r8.py --levels 8x --workers 8;            complete $E
step "contours moon"  $PY -W ignore analysis/contours_planet.py --bodies moon --levels 240m;   complete $M
step "contours mars"  $PY -W ignore analysis/contours_planet.py --bodies mars --levels 240m;   complete $R

for g in weather temperature insolation; do
  for b in earth moon mars; do step "$g $b" $PY -W ignore analysis/hex_features.py $g --bodies $b --workers 12; done
done
for b in moon mars; do step "albedo $b" $PY -W ignore analysis/hex_features.py albedo --bodies $b --workers 12; done
for b in earth moon mars; do step "terrain $b" $PY -W ignore analysis/hex_terrain.py --bodies $b --workers 14; done
$PY -c "import os; assert os.path.exists('data/interim/global/extras/grids.json')" || step "extras build" $PY -W ignore analysis/hex_extras.py build
for b in earth moon mars; do step "extras $b" $PY -W ignore analysis/hex_extras.py run --bodies $b --workers 12; done

for d in $E $M $R; do step "zip $(basename $d)" $PY analysis/zip_single.py $d --prefix r7_; done
say "R7 queue: finished"
