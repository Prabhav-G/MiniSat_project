#!/usr/bin/env python3
"""Benchmark a minisat binary on every .cnf file under a directory.

Each run is executed with -rnd-seed=1, timed with a wall clock, and its
stdout is parsed for the result line and the restarts / conflicts /
decisions / propagations / conflict literals counters.  One CSV row is
written per run and a per-instance median-time summary is printed at the
end.
"""

import argparse
import csv
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

# CSV column -> label of the statistics line in minisat's stdout.
COUNTERS = {
    "restarts": "restarts",
    "conflicts": "conflicts",
    "decisions": "decisions",
    "propagations": "propagations",
    "conflict_literals": "conflict literals",
}
CSV_FIELDS = ["instance", "repeat", "result", "time"] + list(COUNTERS)


def parse_output(stdout):
    """Extract the verdict and the counters from minisat stdout.

    Returns (result, counts): result is "SATISFIABLE", "UNSATISFIABLE" or
    "" when neither verdict is printed; counts maps every COUNTERS column
    to its integer value, or None when the statistics line is missing.
    """
    result = ""
    for line in stdout.splitlines():
        if line.strip() in ("SATISFIABLE", "UNSATISFIABLE"):
            result = line.strip()
    counts = {}
    for column, label in COUNTERS.items():
        match = re.search(r"^%s\s*:\s*(\d+)" % re.escape(label), stdout, re.MULTILINE)
        counts[column] = int(match.group(1)) if match else None
    return result, counts


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
    result, counts = parse_output(stdout)
    if timed_out:
        result = "TIMEOUT"
    elif not result:
        result = "ERROR"
    row = {"result": result, "time": round(elapsed, 4)}
    row.update(counts)
    return row


def find_instances(directory):
    """Return the sorted list of .cnf files under directory, or exit if none."""
    instances = sorted(Path(directory).rglob("*.cnf"))
    if not instances:
        sys.exit("no .cnf files found under %s" % directory)
    return instances


def print_summary(instances, root, rows, out):
    """Print the per-instance median time table and totals for one binary."""
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
    print("CSV written to %s" % out)


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
    instances = find_instances(root)

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

    print_summary(instances, root, rows, args.out)


if __name__ == "__main__":
    main()
