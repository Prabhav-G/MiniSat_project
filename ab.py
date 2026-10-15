#!/usr/bin/env python3
"""A/B benchmark two minisat binaries on every .cnf file under a directory.

For every instance and every repeat the two binaries are run back to back
(A then B), so that both see the same machine state, thermal condition and
background load.  Each binary gets its own CSV in the harness.py format,
which compare.py checks and summarizes:

    python3 ab.py --bin-a bin/minisat_baseline --bin-b optimized/build/minisat \\
        --dir bench/train/QG --repeat 3 --out-a a.csv --out-b b.csv
    python3 compare.py --base a.csv --new b.csv
"""

import argparse
import csv
from pathlib import Path

from harness import CSV_FIELDS, find_instances, print_summary, run_once


def main():
    """Parse arguments, run both binaries alternately, write both CSVs."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bin-a", required=True, help="path to the first minisat binary")
    parser.add_argument("--bin-b", required=True, help="path to the second minisat binary")
    parser.add_argument("--dir", required=True, help="directory searched recursively for .cnf files")
    parser.add_argument("--timeout", type=float, default=120, help="per-run wall-clock limit in seconds")
    parser.add_argument("--repeat", type=int, default=1, help="runs per instance and binary")
    parser.add_argument("--out-a", required=True, help="CSV output path for --bin-a")
    parser.add_argument("--out-b", required=True, help="CSV output path for --bin-b")
    args = parser.parse_args()

    binaries = {"a": str(Path(args.bin_a).resolve()), "b": str(Path(args.bin_b).resolve())}
    outs = {"a": args.out_a, "b": args.out_b}
    root = Path(args.dir)
    instances = find_instances(root)

    rows = {"a": [], "b": []}
    files = {label: open(path, "w", newline="") for label, path in outs.items()}
    writers = {}
    for label, fh in files.items():
        writers[label] = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writers[label].writeheader()
    try:
        for index, cnf in enumerate(instances, 1):
            name = str(cnf.relative_to(root))
            for repeat in range(1, args.repeat + 1):
                for label in ("a", "b"):
                    row = run_once(binaries[label], cnf, args.timeout)
                    row["instance"] = name
                    row["repeat"] = repeat
                    writers[label].writerow(row)
                    files[label].flush()
                    rows[label].append(row)
                    print("[%d/%d] %s run %d %s: %s %.3fs"
                          % (index, len(instances), name, repeat, label.upper(), row["result"], row["time"]))
    finally:
        for fh in files.values():
            fh.close()

    for label in ("a", "b"):
        print()
        print("=== %s: %s ===" % (label.upper(), binaries[label]))
        print_summary(instances, root, rows[label], outs[label])


if __name__ == "__main__":
    main()
