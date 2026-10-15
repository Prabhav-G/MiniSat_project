# Changes to `optimized/`

Each entry is one search-preserving change to the solver in `optimized/minisat`.
Every entry was checked with `ab.py` (baseline vs new binary, run back to back,
3 repeats per instance) and `compare.py` (result, restarts, conflicts, decisions,
propagations and conflict literals must be identical) on all four families of
`bench/train/`. The speedups are geometric means of per-instance median times,
baseline over new.

## 1. Fail fast in clause minimization (candidate 5 from CANDIDATES.md)

Binary: `bin/minisat_opt5`. Files: `minisat/core/Solver.cc` (`analyze`,
`litRedundant`), `minisat/core/Solver.h`.

What it does. After a conflict, MiniSat tries to shrink the learnt clause by
dropping every literal that is implied by the others (`litRedundant`). That check
walks the chain of reasons behind a literal and gives up as soon as it reaches a
decision. Before the walk starts, we now record which decision levels occur in the
clause (as a 32-bit mask, one bit per level modulo 32, using the `abstractLevel`
helper that was already in `Solver.h` but unused). A literal whose level is not
in the mask can never be dropped: its reason chain stays inside its own level
until it hits the decision of that level, and nothing in the clause lives there.
So the walk now stops at such a literal immediately instead of following the
chain to the decision. This is the filter MiniSat 2.0 used with its recursive
`litRedundant`; it was lost when the iterative version was introduced.

Why the search is unchanged. The shortcut only returns "not redundant" where the
full walk would return the same answer, so the learnt clause, the backtrack level
and everything after them are identical. The only side effect it skips is a few
`seen_failed` memo marks on intermediate variables, which are cleared at the end of
`analyze` and only ever make later walks shorter, never change their answer.
`compare.py` confirmed every counter, including `conflict literals`, matches the
baseline on all 235 training instances.

Measured effect. Essentially none.

| family | instances | geomean speedup | slowest instance (baseline) | its speedup |
|---|---|---|---|---|
| QG | 22 | 1.019 | qg5-13 (1.06 s) | 1.028 |
| bmc | 13 | 1.003 | bmc-ibm-12 (0.41 s) | 1.006 |
| flat200-479 | 100 | 1.014 | flat200-26 (0.02 s) | 1.018 |
| uuf250-1065 | 100 | 0.999 | uuf250-087 (5.68 s) | 0.998 |

All of these are inside the run-to-run spread of the baseline (median 1.01 on
uuf250, 1.02 on bmc, 1.08 to 1.09 on the sub-10 ms QG and flat200 instances), so
the change is neutral. An instrumented scratch build explains why: on uuf250-087
the 10.4 M `litRedundant` calls take only 1.2 inner steps each on average, and of
the 6.1 M calls that fail, only 176 k (3 %) are caught by the new test before the
old tests (decision reached, or a `seen_failed` mark) would have caught them. The
reason chains on these instances are already too short for a shortcut to matter.
The same holds on qg5-13 (3.9 k of 700 k failures) and bmc-ibm-12 (2.3 k of
219 k). The change is kept because it is sound, free, and removes a wasted walk
on instances with deeper implication chains.

Raw data: `results/ab_opt5_<family>_a.csv` (baseline) and `results/ab_opt5_<family>_b.csv`
(this binary).
