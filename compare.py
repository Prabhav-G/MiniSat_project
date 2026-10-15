#!/usr/bin/env python3
"""Compare two harness.py CSV files (a base and a new solver build).

For every instance the result and the restarts / conflicts / decisions /
propagations / conflict literals counters must be identical across all
repeats of both files; every mismatch is listed and makes the script exit
with status 1.  A counter column missing from one of the files (CSVs
written by an older harness.py) is skipped with a warning.  The script
then reports the median-time speedup (base / new) per instance, the
geometric mean speedup, the speedup of the slowest base instance and the
run-to-run spread (max / min of the repeat times) of the base file.
"""

import argparse
import csv
import math
import statistics
import sys
from collections import defaultdict

from harness import COUNTERS

CHECKED = ["result"] + list(COUNTERS)


def load(path):
    """Read a harness CSV into ({instance: [row dict, ...]}, columns) with float times."""
    runs = defaultdict(list)
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            row["time"] = float(row["time"])
            runs[row["instance"]].append(row)
        return runs, list(reader.fieldnames or [])


def signature(row, columns):
    """The tuple of the checked column values of one run."""
    return tuple(row[name] for name in columns)


def find_mismatches(base, new, columns):
    """Return a list of human-readable mismatch descriptions.

    A mismatch is an instance present in only one file, an instance whose
    repeats disagree within one file, or an instance whose signature (the
    values of the given columns) differs between the two files.
    """
    mismatches = []
    for name in sorted(set(base) | set(new)):
        if name not in base or name not in new:
            mismatches.append("%s: missing from %s" % (name, "base" if name not in base else "new"))
            continue
        signatures = {}
        for label, rows in (("base", base[name]), ("new", new[name])):
            distinct = sorted({signature(r, columns) for r in rows})
            if len(distinct) > 1:
                mismatches.append("%s: %s repeats disagree: %s" % (name, label, distinct))
            signatures[label] = distinct[0]
        if signatures["base"] != signatures["new"]:
            mismatches.append("%s: base %s != new %s" % (name, signatures["base"], signatures["new"]))
    return mismatches


def main():
    """Parse arguments, check counters, print the speedup report."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="harness CSV of the base binary")
    parser.add_argument("--new", required=True, help="harness CSV of the new binary")
    parser.add_argument("--exclude-file", help="newline-separated list of instance names or paths to exclude from the speed report")
    args = parser.parse_args()

    excluded = set()
    if args.exclude_file:
        with open(args.exclude_file) as fh:
            for raw in fh:
                text = raw.strip()
                if not text:
                    continue
                excluded.add(text)
                parts = text.split("bench/train/", 1)
                if len(parts) == 2:
                    excluded.add(parts[1])
                path_parts = text.split("/")
                for index, part in enumerate(path_parts):
                    if part.lower().endswith('.cnf'):
                        excluded.add("/".join(path_parts[index:]))

    base, base_columns = load(args.base)
    new, new_columns = load(args.new)
    if not base or not new:
        sys.exit("empty CSV: %s" % (args.base if not base else args.new))

    columns = [c for c in CHECKED if c in base_columns and c in new_columns]
    skipped = [c for c in CHECKED if c not in columns]
    if skipped:
        print("WARNING: not checked (column missing from a CSV): %s" % ", ".join(skipped))
        print()
    print("checked columns: %s" % ", ".join(columns))
    mismatches = find_mismatches(base, new, columns)
    if mismatches:
        print("MISMATCHES (%d):" % len(mismatches))
        for line in mismatches:
            print("  " + line)
        print()

    rows = []
    for name in sorted(set(base) & set(new)):
        base_times = [r["time"] for r in base[name]]
        new_times = [r["time"] for r in new[name]]
        base_median = statistics.median(base_times)
        new_median = statistics.median(new_times)
        speedup = base_median / new_median if new_median > 0 else math.inf
        spread = max(base_times) / min(base_times) if min(base_times) > 0 else math.inf
        rows.append((name, base[name][0]["result"], base_median, new_median, speedup, spread))

    filtered_rows = [row for row in rows if row[0] not in excluded and row[0].split('/')[-1] not in excluded]

    print("%-50s %-14s %10s %10s %8s %12s" % ("instance", "result", "base_med_s", "new_med_s", "speedup", "base_spread"))
    for name, result, base_median, new_median, speedup, spread in filtered_rows:
        print("%-50s %-14s %10.3f %10.3f %8.3f %12.3f" % (name, result, base_median, new_median, speedup, spread))
    print()

    if filtered_rows:
        finite = [r[4] for r in filtered_rows if math.isfinite(r[4]) and r[4] > 0]
        geomean = math.exp(sum(math.log(s) for s in finite) / len(finite)) if finite else math.nan
        slowest = max(filtered_rows, key=lambda r: r[2])
        spreads = [r[5] for r in filtered_rows]
        print("instances compared:            %d" % len(filtered_rows))
        print("sum of base medians:           %.3f s" % sum(r[2] for r in filtered_rows))
        print("sum of new medians:            %.3f s" % sum(r[3] for r in filtered_rows))
        zero_median = len(filtered_rows) - len(finite)
        print("geometric mean speedup:        %.3f%s"
              % (geomean, "  (excluding %d instance(s) with a zero median time)" % zero_median if zero_median else ""))
        print("slowest base instance:         %s (%.3f s) speedup %.3f" % (slowest[0], slowest[2], slowest[4]))
        print("base run-to-run spread:        median %.3f  max %.3f (%s)"
              % (statistics.median(spreads), max(spreads), max(filtered_rows, key=lambda r: r[5])[0]))
        if excluded:
            matched = len(rows) - len(filtered_rows)
            print("instances excluded by file:    %d" % matched)

    if mismatches:
        sys.exit("error: %d mismatch(es) in result or counters" % len(mismatches))


if __name__ == "__main__":
    main()
