"""Reproducible isolated DuckDB candidate-metadata benchmark (no real mask/matcher)."""

from __future__ import annotations

import argparse
import csv
import ctypes
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

import duckdb
import h3

from .database import FIELD_TYPES, OBS_FIELDS, candidate_relation, export_parquet, initialize

RUN = "synthetic-benchmark-v1"
PILOT = Path(__file__).resolve().parents[2]


def windows_peak_memory():
    """Process-lifetime high water marks, in bytes, from Windows PSAPI."""
    if os.name != "nt":
        return {"unavailable": "Windows PSAPI required"}
    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong)] + [
            (name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize",
            "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
            "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    fn = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
    fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
    counter = Counters()
    counter.cb = ctypes.sizeof(counter)
    if not fn(kernel.GetCurrentProcess(), ctypes.byref(counter), counter.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return {"peak_working_set_bytes": counter.PeakWorkingSetSize,
            "peak_pagefile_usage_bytes": counter.PeakPagefileUsage}


def directory_bytes(path):
    total = 0
    for file in path.rglob("*"):
        try:
            if file.is_file():
                total += file.stat().st_size
        except FileNotFoundError:
            pass  # temporary spill files can disappear between stat calls
    return total


def configured(db, temp, memory, threads, read_only=False):
    conn = duckdb.connect(str(db), read_only=read_only)
    conn.execute("SET memory_limit = ?", [memory])
    conn.execute("SET threads = ?", [threads])
    conn.execute("SET temp_directory = ?", [str(temp)])
    conn.execute("SET max_temp_directory_size = '8GB'")
    return conn


def generate(conn, directory, rows, seed):
    """Use real unique H3 IDs/centres, synthetic features, and production tables/keys.

    Bulk SQL loading intentionally bypasses the pilot's Python CSV validator. This
    measures schema/load and serving capacity, not the production importer at scale.
    """
    initialize(conn)
    ids = directory / "synthetic_cells.csv"
    start = time.perf_counter()
    with ids.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["i", "h3_cell", "centre_lat_deg", "centre_lon_deg", "is_pentagon"])
        i = 0
        for base in sorted(h3.get_res0_cells()):
            for cell in sorted(h3.cell_to_children(base, 6)):
                lat, lon = h3.cell_to_latlng(cell)
                writer.writerow([i, cell, lat, lon, h3.is_pentagon(cell)])
                i += 1
                if i == rows:
                    break
            if i == rows:
                break
    if i != rows:
        raise ValueError("row count exceeds available resolution-6 H3 cells")
    generation = time.perf_counter() - start
    start = time.perf_counter()
    # Stable arithmetic PRNG, independent of SQL scan/thread order. Seed is bounded
    # by the CLI, keeping BIGINT arithmetic safely within range for the global grid.
    conn.execute("""CREATE TEMP TABLE synthetic AS SELECT *,
        ((i * 48271 + ?) % 2147483647) / 2147483647.0 AS u,
        CASE WHEN i % 5=0 THEN 1.0 ELSE 0.1 + (i % 900)/1000.0 END AS coverage,
        30.0 + (i % 1200)/100.0 AS area,
        1000 + i % 59000 AS samples
        FROM read_csv(?, header=true, columns={
            'i':'BIGINT','h3_cell':'VARCHAR','centre_lat_deg':'DOUBLE',
            'centre_lon_deg':'DOUBLE','is_pentagon':'BOOLEAN'})""", [seed, str(ids)])
    metadata = json.dumps({"synthetic": True, "generator": RUN, "seed": seed, "rows": rows,
                           "note": "Not NASADEM observations, not an eligibility mask"})
    digest = hashlib.sha256(metadata.encode()).hexdigest()
    conn.execute("INSERT INTO source_metadata VALUES ('synthetic', 'SYNTHETIC_BENCHMARK', ?, ?)", [digest, metadata])
    conn.execute("INSERT INTO terrain_runs VALUES (?,6,?,?, 'synthetic', 'synthetic', ?)", [RUN, digest, digest, metadata])
    conn.execute("INSERT INTO run_sources VALUES (?, 'synthetic')", [RUN])
    conn.execute("INSERT INTO h3_cells SELECT h3_cell,6,centre_lat_deg,centre_lon_deg,is_pentagon FROM synthetic")
    expressions = {
        "coverage_status": "CASE WHEN coverage=1 THEN 'complete' ELSE 'partial' END",
        "quality_flags": "CASE WHEN coverage=1 THEN '' ELSE 'partial_coverage' END",
        "source_collection": "'SYNTHETIC_BENCHMARK'", "source_granules": "'synthetic://benchmark-v1'",
        "n_samples": "samples", "n_analysis": "samples", "n_excluded_water": "0",
        "n_excluded_void": "0", "n_derivative_missing": "0",
        "coverage_fraction_exact_overlap": "coverage",
        "coverage_fraction_pixel_centre": "coverage * (0.998 + u*0.004)",
        "valid_coverage_fraction": "coverage * (0.998 + u*0.004)",
        "cell_area_km2": "area", "h3_spherical_cell_area_km2": "area*0.997",
        "overlap_area_km2": "coverage*area",
        "sampled_area_km2": "coverage*(0.998+u*0.004)*area",
        "analysis_area_km2": "coverage*(0.998+u*0.004)*area",
        "valid_derivative_area_km2": "coverage*(0.998+u*0.004)*area",
        "elevation_mean_m": "u*4000", "elevation_min_m": "u*4000-100",
        "elevation_max_m": "u*4000+200", "slope_mean_deg": "u*30",
        "slope_p50_deg": "u*25", "slope_p95_deg": "u*45",
        "roughness_tri_mean_m": "u*50", "roughness_detrended_mean_m": "u*3",
    }
    for key in OBS_FIELDS:
        if key.startswith("n_valid_"):
            expressions[key] = "samples"
    conn.execute(f"INSERT INTO terrain_observations (run_id,h3_cell,{','.join(OBS_FIELDS)}) "
                 f"SELECT ?,h3_cell,{','.join(expressions[k] for k in OBS_FIELDS)} FROM synthetic", [RUN])
    conn.execute("DROP TABLE synthetic")
    conn.execute("CHECKPOINT")
    return {"id_generation_seconds": generation, "bulk_load_seconds": time.perf_counter()-start,
            "staging_csv_bytes": ids.stat().st_size}


def drain(conn, query, params=None):
    """Transfer every column/row to Python in bounded batches; no COUNT shortcut."""
    cursor = conn.execute(query, params or [])
    n = 0
    while batch := cursor.fetchmany(4096):
        n += len(batch)
    return n


def worker(args):
    directory = args.directory
    temp = directory / (args.stage + "_temp")
    temp.mkdir()
    stop = threading.Event()
    samples = [0]
    def monitor():
        while not stop.wait(0.1):
            samples[0] = max(samples[0], directory_bytes(temp))
    monitor_thread = threading.Thread(target=monitor, daemon=True)
    monitor_thread.start()
    result = {"stage": args.stage}
    try:
        start = time.perf_counter()
        with configured(directory/"terrain.duckdb", temp, args.memory, args.threads,
                        read_only=args.stage != "setup") as conn:
            result["connect_seconds"] = time.perf_counter()-start
            if args.stage == "setup":
                start = time.perf_counter()
                result.update(generate(conn, directory, args.rows, args.seed))
                result["setup_seconds"] = time.perf_counter()-start
            elif args.stage == "verify":
                # Deliberately outside query/export/read timings. Checks are not
                # primary performance measurements.
                result["database_counts"] = conn.execute("SELECT count(*),count(DISTINCT h3_cell) FROM terrain_observations").fetchall()[0]
                result["export_counts"] = conn.execute("SELECT count(*),count(DISTINCT h3_cell) FROM read_parquet(?)", [str(directory/"candidates.parquet")]).fetchall()[0]
                fields = ",".join(FIELD_TYPES) + ",run_id"
                difference = conn.execute(f"""SELECT count(*) FROM (
                    (SELECT {fields} FROM read_parquet(?) EXCEPT
                     SELECT {fields} FROM terrain_observations JOIN h3_cells USING(h3_cell))
                    UNION ALL
                    (SELECT {fields} FROM terrain_observations JOIN h3_cells USING(h3_cell) EXCEPT
                     SELECT {fields} FROM read_parquet(?)))""",
                    [str(directory/"candidates.parquet")]*2).fetchall()[0][0]
                if list(result["database_counts"]) != [args.rows]*2 or list(result["export_counts"]) != [args.rows]*2 or difference:
                    raise ValueError(f"export uniqueness/content validation failed: {result}, differences={difference}")
                result["content_differences"] = difference
            else:
                timings, counts = [], []
                for _ in range(args.repeats+1):
                    if args.stage == "export":
                        # Only this command's own output, in its exclusive directory.
                        (directory/"candidates.parquet").unlink(missing_ok=True)
                    start = time.perf_counter()
                    if args.stage == "query":
                        relation = candidate_relation(conn, RUN, 6)
                        # DuckDB 2 relations have no fetchmany: execute the exact
                        # shared query with its parameters on the streaming cursor.
                        count = drain(conn, relation.sql_query(), [RUN, 6])
                    elif args.stage == "export":
                        export_parquet(conn, RUN, 6, directory/"candidates.parquet")
                        count = None  # actual rows verified by a separate process
                    else:
                        count = drain(conn, "SELECT * FROM read_parquet(?)", [str(directory/"candidates.parquet")])
                    timings.append(time.perf_counter()-start)
                    counts.append(count)
                result.update(seconds=timings, first_seconds=timings[0],
                              repeat_median_seconds=statistics.median(timings[1:]),
                              slowest_seconds=max(timings), fetched_rows=counts)
                if args.stage != "export" and counts != [args.rows]*(args.repeats+1):
                    raise ValueError(f"incorrect fetched rows: {counts}")
        result["database_bytes"] = (directory/"terrain.duckdb").stat().st_size
        if (directory/"candidates.parquet").exists():
            result["parquet_bytes"] = (directory/"candidates.parquet").stat().st_size
    finally:
        stop.set()
        monitor_thread.join()
        result["sampled_temp_peak_bytes"] = max(samples[0], directory_bytes(temp))
        result["memory"] = windows_peak_memory()
        (directory / f"{args.stage}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


def run_child(command, directory, name, timeout=900):
    start = time.perf_counter()
    proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    elapsed = time.perf_counter()-start
    (directory/f"{name}.log").write_text(proc.stdout+proc.stderr, encoding="utf-8")
    if proc.returncode:
        raise RuntimeError(f"{name} failed ({proc.returncode}): {proc.stderr[-2000:]}")
    return elapsed, proc.stdout


def baseline(root):
    directory = root/"baseline"
    directory.mkdir()
    db = directory/"terrain.duckdb"
    base = [sys.executable, "-m", "spacethropic.db_cli", "--database", str(db)]
    artifacts = PILOT/"outputs/n51w113_drumheller_badlands_h3"
    imp = [*base, "import"]
    for res in (6,8):
        imp += ["--pair", str(artifacts/f"h3_res{res}_cells.csv"), str(artifacts/f"h3_res{res}_run_summary.json")]
    seconds, _ = run_child(imp, directory, "import")
    list_seconds, listing = run_child([*base, "list-runs"], directory, "list")
    runs = json.loads(listing)
    result = {"import_cli_seconds": seconds, "list_cli_seconds": list_seconds, "runs": runs}
    for run in runs:
        res = run["h3_resolution"]
        expected = (12,1,11) if res == 6 else (296,220,76)
        assert (run["n_cells"],run["complete"],run["partial"]) == expected
        assert run["n_samples"] == 311040
        output = directory/f"candidates_res{res}.parquet"
        elapsed, _ = run_child([*base,"export","--run-id",run["run_id"],"--resolution",str(res),"--output",str(output)],directory,f"export{res}")
        with duckdb.connect() as conn:
            got = conn.execute("SELECT count(*),count(DISTINCT h3_cell),sum(n_samples) FROM read_parquet(?)",[str(output)]).fetchall()[0]
            assert got == (expected[0], expected[0], 311040)
        result[f"export{res}"] = {"cli_seconds":elapsed,"bytes":output.stat().st_size,"rows":got[0]}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True, help="NEW exclusive benchmark directory")
    parser.add_argument("--rows", nargs="+", type=int, default=[100000,1000000,4000000])
    parser.add_argument("--seed", type=int, default=20261114)
    parser.add_argument("--repeats", type=int, default=3, help="repeat measurements after first measurement")
    parser.add_argument("--memory", default="2GB")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--stage", choices=["setup","query","export","read","verify"], help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not 0 <= args.seed < 2147483647 or args.repeats < 1 or args.threads < 1 or any(n < 1 or n > h3.get_num_cells(6) for n in args.rows):
        parser.error("require positive rows <= res-6 global cells, repeats/threads >=1, seed in [0,2147483647)")
    args.directory = args.directory.resolve()
    if args.stage:
        if len(args.rows) != 1:
            parser.error("worker requires exactly one row count")
        args.rows = args.rows[0]
        worker(args)
        return 0
    if args.directory.exists():
        parser.error("directory already exists; choose a new isolated benchmark directory")
    args.directory.mkdir(parents=True)
    result = {"settings": vars(args) | {"directory": str(args.directory)},
              "machine": {"platform":platform.platform(),"processor":platform.processor(),
                          "logical_cpus":os.cpu_count(),"python":sys.version,"duckdb":duckdb.__version__,"h3":h3.__version__},
              "sizes": []}
    if os.name == "nt":
        machine = subprocess.run(["powershell", "-NoProfile", "-Command",
            "[pscustomobject]@{cpu=(Get-CimInstance Win32_Processor).Name;ram_bytes=(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory;drive_free=(Get-PSDrive C).Free} | ConvertTo-Json"], capture_output=True,text=True)
        result["machine"]["windows"] = machine.stdout.strip()
    report = args.directory/"results.json"
    try:
        result["baseline"] = baseline(args.directory)
        for rows in args.rows:
            directory = args.directory/str(rows)
            directory.mkdir()
            item = {"rows": rows, "status":"running"}
            result["sizes"].append(item)
            try:
                for stage in ("setup","query","export","read","verify"):
                    command = [sys.executable,"-m","spacethropic.benchmark","--directory",str(directory),
                               "--rows",str(rows),"--seed",str(args.seed),"--repeats",str(args.repeats),
                               "--memory",args.memory,"--threads",str(args.threads),"--stage",stage]
                    elapsed, _ = run_child(command,directory,stage)
                    item[stage] = json.loads((directory/f"{stage}.json").read_text())
                    item[stage]["process_wall_seconds"] = elapsed
                    print(f"{rows}: {stage} completed in {elapsed:.3f}s",flush=True)
                    report.write_text(json.dumps(result,indent=2),encoding="utf-8")
                item["status"] = "passed"
            except (RuntimeError,subprocess.TimeoutExpired) as exc:
                item.update(status="failed",error=str(exc))
                print(f"{rows}: FAILED: {exc}",flush=True)
            report.write_text(json.dumps(result,indent=2),encoding="utf-8")
    finally:
        report.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(f"results: {report}")
    return int(any(s["status"] != "passed" for s in result["sizes"]))


if __name__ == "__main__":
    sys.exit(main())
