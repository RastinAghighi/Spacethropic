#!/usr/bin/env bash
# Feature queue (user order, 2026-11-15): weather -> temperature -> sunlight, each on Earth,
# Moon and Mars together. Each group starts once its inputs exist.
set -u
cd "$(dirname "$0")/.."
PY=.venv/Scripts/python.exe
G=data/interim/global
LOG=$G/features_queue.log
say() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }

say "weather: waiting for MERRA-2 climatology"
until [ -f $G/merra2_2023_climate.npz ]; do sleep 20; done
say "weather: start"; $PY -W ignore analysis/hex_features.py weather --workers 15 >> "$LOG" 2>&1; say "weather: exit $?"

say "temperature: waiting for Diviner grid"
until [ -f $G/diviner_temperature_grid.npz ]; do sleep 20; done
say "temperature: start"; $PY -W ignore analysis/hex_features.py temperature --workers 15 >> "$LOG" 2>&1; say "temperature: exit $?"

say "sunlight: start"; $PY -W ignore analysis/hex_features.py insolation --workers 15 >> "$LOG" 2>&1; say "sunlight: exit $?"
