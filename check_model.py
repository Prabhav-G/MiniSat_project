#!/usr/bin/env python3
"""Check that a MiniSat model satisfies every clause of a DIMACS CNF file."""

import argparse
import sys
from pathlib import Path


def parse_cnf(path):
    """Return (num_vars, clauses) parsed from a DIMACS CNF file."""
    clauses = []
    num_vars = None
    with Path(path).open() as fh:
        current = []
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("c"):
                continue
            if line.startswith("p"):
                parts = line.split()
                if len(parts) != 4 or parts[1] != "cnf":
                    raise ValueError(f"bad problem line: {line}")
                num_vars = int(parts[2])
                continue
            for token in line.split():
                lit = int(token)
                if lit == 0:
                    clauses.append(current)
                    current = []
                else:
                    current.append(lit)
        if current:
            raise ValueError("last clause is missing trailing 0")
    if num_vars is None:
        raise ValueError("missing DIMACS problem line")
    return num_vars, clauses


def parse_model(path):
    """Return variable assignments parsed from a MiniSat result file."""
    values = {}
    saw_sat = False
    with Path(path).open() as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            if line == "SAT":
                saw_sat = True
                continue
            if line in {"UNSAT", "UNSATISFIABLE", "SATISFIABLE"}:
                continue
            if line.startswith("v "):
                tokens = line.split()[1:]
            else:
                tokens = line.split()
            for token in tokens:
                lit = int(token)
                if lit == 0:
                    continue
                values[abs(lit)] = lit > 0
    if not saw_sat and not values:
        raise ValueError("model file does not contain a SAT assignment")
    return values


def clause_satisfied(clause, values):
    """Return True when at least one literal in the clause is satisfied."""
    for lit in clause:
        value = values.get(abs(lit), False)
        if (lit > 0 and value) or (lit < 0 and not value):
            return True
    return False


def main():
    """Parse inputs, verify every clause, and report the first failure if any."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cnf", help="path to the DIMACS CNF file")
    parser.add_argument("model", help="path to MiniSat's model output file")
    args = parser.parse_args()

    num_vars, clauses = parse_cnf(args.cnf)
    values = parse_model(args.model)
    for var in range(1, num_vars + 1):
        values.setdefault(var, False)

    for index, clause in enumerate(clauses, 1):
        if not clause_satisfied(clause, values):
            print(f"UNSAT clause #{index}: {' '.join(map(str, clause))}")
            sys.exit(1)

    print(f"OK: {len(clauses)} clauses satisfied")


if __name__ == "__main__":
    main()
