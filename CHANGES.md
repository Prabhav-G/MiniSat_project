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

## 2. Candidate 5 follow-up and candidate 1 postmortem

Candidate 5 was a dead end. The idea was an abstract-level fast-fail in
`litRedundant`: counters stayed identical, but the speedups were inside noise
(QG 1.019, bmc 1.003, flat200 1.014, uuf250 0.999), so it was reverted in
commit `dbe9989`. The scratch instrumentation explained why. The reason chains
are already very short, about 1.2 steps on average, so the shortcut almost
never fires early enough to matter.

Candidate 1 is rejected. The first implementation changed the search on
`bmc-ibm-4` even though QG, flat200 and uuf250 still matched: conflicts moved
from 604 to 694 and propagations from 189,973 to 212,960. A later rewrite was
worse and returned wrong verdicts, including UNSAT on SAT instances. Scratch
measurement also showed that only about 4 to 7 percent of watcher visits that
passed the blocker test were satisfied by `first`, so the upside was limited
from the start. The exploratory work is kept on branch `cand1-debug`; `master`
was left untouched. The lesson from this failed attempt is that matching three
families out of four is not enough. Every candidate is now checked on all four
families because one missed family was enough to hide a real bug.

## 3. Build-only PGO experiment

This experiment changed only the build, not the solver source. `optimized/minisat`
was left bit-for-bit identical to baseline commit `f6a0cf5`, and all builds were
made in fresh directories: `optimized/build_pgo_gen`, `optimized/build_pgo_use`
and `optimized/build_pgo_native`.

Training set used for profile generation (`pgo_training_set.txt`): 10 uuf250
instances (`uuf250-010`, `021`, `034`, `045`, `056`, `068`, `079`, `088`,
`093`, `099`), 2 QG instances (`qg5-12`, `qg7-12`), 2 bmc instances
(`bmc-ibm-4`, `bmc-galileo-9`), and 5 flat200 instances (`flat200-10`, `25`,
`40`, `70`, `95`). `uuf250-087`, `uuf250-077`, `qg5-13` and `bmc-ibm-12` were
explicitly excluded from training.

Exact build flags:

- PGO instrumentation build in `optimized/build_pgo_gen`:
  `-DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_FLAGS=-fprofile-instr-generate`
- PGO use build in `optimized/build_pgo_use`:
  `-DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_FLAGS=-fprofile-instr-use=/Users/prabhavgoel/sat-opt/optimized/build_pgo_gen/pgo.profdata`
- PGO plus native CPU build in `optimized/build_pgo_native`:
  `-DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_FLAGS=-fprofile-instr-use=/Users/prabhavgoel/sat-opt/optimized/build_pgo_gen/pgo.profdata -mcpu=native`

The verbose compile lines for both optimized builds contained `-O3 -DNDEBUG` and
no `-g`, `-Ofast` or `-ffast-math`. AppleClang printed no profile-mismatch
warnings. The host CPU for `-mcpu=native` was Apple M3, so that binary is tied
to this machine class.

Correctness first. Both `bin/minisat_pgo` and `bin/minisat_pgo_native` passed
`ab.py` plus `compare.py` on all four training families with 3 repeats per
instance, matching the baseline on result, restarts, conflicts, decisions,
propagations and conflict literals for every instance. They also matched the
baseline on the option-matrix spot checks (`-no-luby`, `-ccmin-mode=1`,
`-phase-saving=0`, and `-rnd-freq=0.1 -rnd-seed=7`) across 10 instances each
from uuf250, QG and bmc. For SAT model validation, `check_model.py` verified the
model file on every SAT instance in `bench/train/`: 123 SAT cases for
`bin/minisat_pgo` and the same 123 for `bin/minisat_pgo_native`, 246 successful
model checks in total and no failures.

Measured speedups stayed at or below the earlier noise floor (about 1.005
overall geomean, with per-instance spread up to about 1.09 on slower cases and
much worse on tiny cases), so this is another neutral result.

| binary | family | all instances | non-training only |
|---|---|---|---|
| `bin/minisat_pgo` | uuf250-1065 | 0.985 | 0.984 |
| `bin/minisat_pgo` | QG | 1.001 | 1.002 |
| `bin/minisat_pgo` | bmc | 0.999 | 1.000 |
| `bin/minisat_pgo` | flat200-479 | 1.006 | 1.006 |
| `bin/minisat_pgo_native` | uuf250-1065 | 0.983 | 0.982 |
| `bin/minisat_pgo_native` | QG | 1.003 | 1.004 |
| `bin/minisat_pgo_native` | bmc | 1.002 | 1.002 |
| `bin/minisat_pgo_native` | flat200-479 | 1.015 | 1.013 |

Slowest-instance speedups were similarly unconvincing. Plain PGO reached 1.021
on `bmc-ibm-12` but lost ground on the slow uuf cases. PGO plus native reached
1.055 on `bmc-ibm-12`, but the whole-family gains were still buried under noise,
and `uuf250` got slightly worse. To check whether the A-then-B order in `ab.py`
was biasing the result, uuf250 was rerun once with plain PGO first and baseline
second. The geomean stayed 0.985, so the slowdown on uuf250 was not just an
ordering artifact.

Raw data for this experiment lives in `results/ab_pgo_*`,
`results/ab_pgo_native_*`, `results/compare_pgo_*`,
`results/compare_pgo_native_*`, `results/option_matrix_results.csv`,
`results/model_check_results.csv` and `results/sat_instances.txt`.

## Held-out evaluation (one shot, pre-declared in HELDOUT_PLAN.txt)
bin/minisat_pgo_native vs baseline on 14 instances (7 SAT, 7 UNSAT; baseline 9.6-135 s), 3 repeats, A/B interleaved. All six counters identical on every instance. Geomean speedup 0.991 (sum of medians 888.0 s vs 889.8 s); per-instance range 0.959-1.030; 10 of 14 slightly slower. Baseline run-to-run spread: median 1.019, max 1.356 (oddball_20_5_ttf, runs ranged 99-134 s, consistent with thermal throttling of a fanless laptop). Conclusion: no measurable speedup; neutral to about 1% slower, matching the uuf250 result (0.983).

SAT model check on held-out set: 14 models (7 instances x 2 binaries), 0 failures (verify_heldout_models.py).

Cross-check vs CaDiCaL (cross_check.py): 64 instances (all QG and bmc, 15 uuf250, 14 held-out). 63 verdicts agree; 1 inconclusive (REGRandom-K3-L3-Seed30: CaDiCaL timed out at 600 s). DRAT proofs verified by drat-trim for 33 of 34 UNSAT instances.
