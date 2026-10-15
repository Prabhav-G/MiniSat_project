#!/usr/bin/env python3
"""Benchmark a minisat binary on every .cnf file under a directory.

Each run is executed with -rnd-seed=1, timed with a wall clock, and its
stdout is parsed for the result line and the conflicts / decisions /
propagations counters.  One CSV row is written per run and a per-instance
median-time summary is printed at the end.
"""

import argparse
import csv
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

CSV_FIELDS = ["instance", "repeat", "result", "time", "conflicts", "decisions", "propagations"]


def parse_output(stdout):
    """Extract (result, conflicts, decisions, propagations) from minisat stdout.

    result is "SATISFIABLE", "UNSATISFIABLE" or "" when neither verdict is
    printed; the counters are None when their statistics line is missing.
    """
    result = ""
    for line in stdout.splitlines():
        if line.strip() in ("SATISFIABLE", "UNSATISFIABLE"):
            result = line.strip()
    counts = {}
    for name in ("conflicts", "decisions", "propagations"):
        match = re.search(r"^%s\s*:\s*(\d+)" % name, stdout, re.MULTILINE)
        counts[name] = int(match.group(1)) if match else None
    return result, counts["conflicts"], counts["decisions"], counts["propagations"]


def run_once(binary, cnf, timeout):
    """Run the solver on one instance and return a CSV row dict."""
    cmd = [binary, "-rnd-seed=1", "-verb=1", str(cnf)]
    start = time.perf_counter()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        elapsed = time.perf_counter() - start
        stdout = proc.stdout
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        elapsed = time.perf_counter() - start
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        timed_out = True
    result, conflicts, decisions, propagations = parse_output(stdout)
    if timed_out:
        result = "TIMEOUT"
    elif not result:
        result = "ERROR"
    return {
        "result": result,
        "time": round(elapsed, 4),
        "conflicts": conflicts,
        "decisions": decisions,
        "propagations": propagations,
    }


def main():
    """Parse arguments, run every instance, write the CSV and print the summary."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bin", required=True, help="path to a minisat binary")
    parser.add_argument("--dir", required=True, help="directory searched recursively for .cnf files")
    parser.add_argument("--timeout", type=float, default=120, help="per-run wall-clock limit in seconds")
    parser.add_argument("--repeat", type=int, default=1, help="runs per instance")
    parser.add_argument("--out", required=True, help="CSV output path")
    args = parser.parse_args()

    binary = str(Path(args.bin).resolve())
    root = Path(args.dir)
    instances = sorted(root.rglob("*.cnf"))
    if not instances:
        sys.exit("no .cnf files found under %s" % root)

    rows = []
    with open(args.out, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for index, cnf in enumerate(instances, 1):
            name = str(cnf.relative_to(root))
            for repeat in range(1, args.repeat + 1):
                row = run_once(binary, cnf, args.timeout)
                row["instance"] = name
                row["repeat"] = repeat
                writer.writerow(row)
                fh.flush()
                rows.append(row)
                print("[%d/%d] %s run %d: %s %.3fs" % (index, len(instances), name, repeat, row["result"], row["time"]))

    print()
    print("%-50s %-14s %10s" % ("instance", "result", "median_s"))
    total_median = 0.0
    for cnf in instances:
        name = str(cnf.relative_to(root))
        times = [r["time"] for r in rows if r["instance"] == name]
        results = sorted({r["result"] for r in rows if r["instance"] == name})
        median = statistics.median(times)
        total_median += median
        print("%-50s %-14s %10.3f" % (name, "/".join(results), median))
    total_wall = sum(r["time"] for r in rows)
    print()
    print("instances: %d  runs: %d" % (len(instances), len(rows)))
    print("sum of per-instance median times: %.3f s" % total_median)
    print("total wall time of all runs:      %.3f s" % total_wall)
    print("CSV written to %s" % args.out)


if __name__ == "__main__":
    main()
