#!/usr/bin/env bash
# Feature queue part 2 (user, 2026-11-15): after weather -> temperature -> sunlight finish,
# FeO and albedo on the Moon and Mars (non-Earth features), then terrain per R8 hexagon.
set -u
cd "$(dirname "$0")/.."
PY=.venv/Scripts/python.exe
LOG=data/interim/global/features_queue.log
say() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }
say "feo/albedo: waiting for sunlight to finish"
until grep -q "sunlight: exit" "$LOG"; do sleep 30; done
for g in feo albedo; do
  say "$g: start"; $PY -W ignore analysis/hex_features.py $g --workers 15 >> "$LOG" 2>&1; say "$g: exit $?"
done
if [ -f analysis/hex_terrain.py ]; then
  say "terrain: start"; $PY -W ignore analysis/hex_terrain.py >> "$LOG" 2>&1; say "terrain: exit $?"
else
  say "terrain: analysis/hex_terrain.py not present yet; skipped"
fi
