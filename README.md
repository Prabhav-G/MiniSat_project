# Search-preserving optimization experiments on MiniSat 2.2, driven by KISS Sorcar

I tried to speed up MiniSat 2.2 without changing its search, using
[KISS Sorcar](https://github.com/ksenxx/kiss_ai) to write and modify the code, and
building my own verification pipeline around it. I had no prior C++ experience.

**Main result:** none of the experiments produced a measurable speedup. The
verification pipeline, which requires bit-identical solver behaviour, did catch one
change that silently altered the search.

Author: [Prabhav Goel], Berkeley CS/Data Science sophomore. [prabhavgoel8@gmail.com] · [[GitHub](https://github.com/Prabhav-G)]

## Baseline

Upstream [niklasso/minisat](https://github.com/niklasso/minisat) at commit
`37dc6c67e2af26379d88ce349eb9c4c6160e8543`, plus `baseline-build-fix.patch`, which
fixes three compile errors with Apple clang (spacing around `PRI` macros in
string literals, a `memUsedPeak` signature mismatch, and a default argument on a
`friend` declaration). The patch does not change solver logic. I use the `minisat`
binary (with simplification), not `minisat_core`. The patched source directory has
git tree hash `6e45a11576833bcc2d87b076812b33fddab9ee2a`, and `reproduce.sh` checks it.

## Verification pipeline

Everything below was written by Sorcar from my prompts and tested by me.

- `harness.py`: runs a solver binary with a fixed seed, records wall time, result,
  and the counters restarts, conflicts, decisions, propagations, conflict literals.
- `ab.py`: runs baseline and variant alternately on each instance and repeat, so
  both see the same machine state (the machine is a fanless laptop and slows down
  when hot).
- `compare.py`: exits 1 unless the result and all five counters are identical to
  the baseline on every instance and every repeat. I tested it in both directions:
  same-binary comparisons pass, and a deliberately corrupted CSV fails.
- Option matrix: for the PGO binaries, the counters also matched the baseline under
  `-no-luby`, `-ccmin-mode=1`, `-phase-saving=0`, and `-rnd-freq=0.1 -rnd-seed=7`
  on 10 instances each from uuf250, QG and bmc.
- Model checks: SAT models verified against the CNF for both PGO binaries on all
  123 SAT training instances (246 models, 0 failures), and for the baseline and
  PGO+native binaries on the 7 SAT held-out instances (14 models, 0 failures).
- Independent cross-check (`cross_check.py`): verdicts compared with
  [CaDiCaL](https://github.com/arminbiere/cadical) on 64 instances (all QG and bmc,
  15 uuf250, all 14 held-out). 63 agree and 1 is inconclusive (CaDiCaL timed out at
  600 s on `REGRandom-K3-L3-Seed30`). DRAT proofs from CaDiCaL verified by
  [drat-trim](https://github.com/marijnheule/drat-trim) for 33 of 34 UNSAT
  instances. This confirms each instance's status; it does not verify MiniSat's own
  reasoning. For the optimized binaries, the evidence is identical counters.
- Noise floor: the same binary against itself gave a geometric-mean "speedup" of
  about 1.005, with per-instance spread up to about 1.09 on multi-second instances.
  On the held-out set the baseline's run-to-run spread had median 1.019 and max
  1.356. Changes under about 2% cannot be distinguished from noise on this machine.

## Profile (baseline)

Instruments Time Profiler, see `PROFILE.md`. `Solver::propagate` is 73% of the time on
uuf250-087, 85% on qg5-13, and 48% on bmc-ibm-12 (where parsing is 11% and
preprocessing 23%). `analyze` plus `litRedundant` is about 19.5% on uuf250.

## Experiments

All speedups are geometric means of 3-repeat A/B runs on the SATLIB training families,
as reported in `CHANGES.md` and `results/`.

| Experiment | Search preserved? | uuf250 | QG | bmc | flat200 |
|---|---|---|---|---|---|
| Abstract-level fast-fail in `litRedundant` | Yes | 0.999 | 1.019 | 1.003 | 1.014 |
| Register-resident watched literals | **No** | rejected | rejected | rejected | rejected |
| Profile-guided optimization (PGO) | Yes | 0.985 | 1.001 | 0.999 | 1.006 |
| PGO + `-mcpu=native` (Apple M3) | Yes | 0.983 | 1.003 | 1.002 | 1.015 |

The QG, bmc and flat200 instances finish in milliseconds, so process start-up
dominates; only uuf250 (about 2 s per instance) is meaningful for timing.

### Held-out evaluation

Run once, with the plan and instance list committed before any optimized binary
touched these files (`HELDOUT_PLAN.txt`, `bench/heldout_manifest.csv`). PGO +
`-mcpu=native` vs baseline on 14 SAT Competition 2025 instances (7 SAT, 7 UNSAT,
9.6 to 135 s on the baseline), 3 repeats, A/B interleaved. Counters were identical on
every instance. Geometric-mean speedup **0.991** (sum of median times 888.0 s vs
889.8 s), per-instance range 0.959 to 1.030, with 10 of 14 instances slightly slower.
This is no measurable speedup, and it may be about 1% slower.

## What didn't work

**Abstract-level shortcut in clause minimization (neutral).** Skip a literal early
if its decision level is not among the levels in the learnt clause. The search was
identical, but a throwaway instrumented build showed the reason chains average only
about 1.2 steps and the shortcut caught 3% of failing calls, so there was almost
nothing to save. Reverted.

**Register-resident watched literals (rejected, changed the search).** The idea was
to keep the two watched literals in registers and skip stores to the clause in
`propagate`. The first attempt matched the baseline on QG, flat200 and uuf250 but not
on bmc: on `bmc-ibm-4`, conflicts went from 604 to 694 and propagations from 189,973
to 212,960. A trace comparison of a second, separate rewrite found a missing
write-back of a watched literal, and a follow-up fix still returned wrong verdicts
(UNSAT instead of SAT). I stopped there. A measurement also showed the clause is
already satisfied by its first watch on only 4 to 7% of watcher visits, so the upside
was limited. The code is not part of this repo; the outcome is recorded in
`CHANGES.md`. The lesson is that identical counters on three of four families still
hid a bug.

**PGO (neutral to slightly negative).** Correct, but no speedup. On uuf250 it was
about 1.5% slower, including with the A/B order swapped. I don't know why; my guess is
that the structured training instances shifted the code layout away from the random
UNSAT workload, but I did not test this.

## Limitations

- One machine (Apple M3, fanless), so timing is noisy. In one held-out baseline run,
  three repeats of the same binary on `oddball_20_5_ttf` took 99, 132 and 134 s;
  I suspect thermal throttling but did not measure it.
- The held-out set is small (14 instances) and biased toward small files. I screened
  smallest files first with a 150 s cap, 3 jobs in parallel, within a 60-minute
  budget: 89 files screened, 13 qualified (5 to 150 s on the baseline), plus 1 found
  in an earlier 60 s screening pass. Files over 100 MB were excluded. Only PGO +
  native was evaluated, chosen before the run.
- `ab.py` always runs the baseline first, then the variant. I checked for an order
  bias once (uuf250, PGO, order swapped: same result), not everywhere.
- PGO was trained on 19 SATLIB instances that are not the instances used for
  per-instance numbers. Results on other workloads are unknown.
- Instances were screened with the baseline only, so the held-out set is biased
  toward instances MiniSat 2.2 can solve.
- Correctness evidence for the optimized binaries is behavioural equivalence
  (identical counters, checked models), not a formal proof.
- SATLIB random 3-SAT files end with a stray `%` line that MiniSat rejects; the
  scripts strip it, and both binaries read the same cleaned files.

## How I used KISS Sorcar



- Sorcar wrote `harness.py`, `compare.py`, `ab.py`, `check_model.py`, the profiling
  scripts and the PGO builds from prompts I wrote. I decided what to measure and what
  counted as correct.
- Sorcar's own tests and a second-model review passed each tool, but I re-ran them
  myself (for example, building a corrupted CSV to confirm the checker fails).
- Sorcar's candidate ranking predicted 1 to 3% gains for the `litRedundant` change
  and for others; a measurement it did itself showed there was almost nothing to
  save.
- Candidate 1's failure: Sorcar's first attempt changed the search; the "fix" it
  tried next was incomplete and returned wrong verdicts; the counters caught both.
- Sorcar's first held-out screening ran 8 jobs in parallel and found only 4
  qualifying instances; I redid it with a smaller script, 3 jobs, and a wider
  window.
- Sorcar was easy to use and retained context when switching between various agents to ensure a seamless workflow.

## Reproducing

    ./reproduce.sh quick     # build baseline + PGO variants, correctness gate on subsets
    ./reproduce.sh full      # all four training families, 3 repeats (not yet tested)
    URI_FILE=<track_main_2025.uri path or URL> ./reproduce.sh heldout   # not yet tested

`quick` was tested from a fresh clone of this repository on an Apple M3 MacBook Air
and took about 3 minutes. It builds the baseline from upstream + the patch (and
checks the patched source against `expected_minisat_tree.txt`), downloads the SATLIB
instances, builds the PGO variants, checks that every counter matches, and compares
a fresh baseline against the recorded CSVs. It fails on any counter mismatch. PGO
needs macOS (`xcrun llvm-profdata`). Only the counters, not the timings, are
expected to reproduce exactly. The held-out instances come from the
[SAT Competition 2025 main track](https://satcompetition.github.io/2025/downloads.html);
`heldout` mode looks them up by hash in the `.uri` file and has not been run.

## Files

- `harness.py`, `ab.py`, `compare.py`: benchmarking and checking
- `check_model.py`, `verify_heldout_models.py`, `cross_check.py`, `screen_heldout.py`: verification and held-out selection
- `CHANGES.md`: chronological experiment log; `PROFILE.md`, `CANDIDATES.md`: profile and candidate analysis
- `results/`: per-run CSVs and logs; `bench/heldout_manifest.csv`, `bench/heldout_screening.csv`: held-out set and screening record
- `baseline-build-fix.patch`, `BASELINE_COMMIT.txt`: how the baseline was built