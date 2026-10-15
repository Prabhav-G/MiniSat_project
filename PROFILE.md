# Baseline profile of `optimized/build/minisat`

## Setup

Build (no source changes; `optimized/` is still identical to `original/`):

```
cd optimized && mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_FLAGS=-g -DCMAKE_POLICY_VERSION_MINIMUM=3.5
make -j minisat_simp        # produces optimized/build/minisat, flags: -g -O3 -DNDEBUG -arch arm64
```

Same configuration as `bin/minisat_baseline` (Release, static) plus `-g`. The binary
reproduces the baseline counters exactly on all four instances (conflicts, decisions,
propagations identical to `baseline_*.csv`).

Instances (slowest per family taken from the 3-repeat medians in `baseline_qg.csv`
and `baseline_bmc.csv`):

| instance | family | vars | clauses (as counted by minisat after parsing) | result | conflicts | propagations | baseline median |
|---|---|---|---|---|---|---|---|
| uuf250-087 | uuf250-1065 | 250 | 1,065 | UNSAT | 1,094,845 | 48.3M | 5.72 s |
| uuf250-077 | uuf250-1065 | 250 | 1,065 | UNSAT | 1,026,579 | 45.4M | 5.30 s |
| qg5-13 | QG | 2,197 | 77,139 (125,464 in the file) | UNSAT | 30,625 | 6.2M | 1.03 s |
| bmc-ibm-12 | bmc | 39,598 | 193,434 (194,778 in the file) | SAT | 6,831 | 6.7M | 0.41 s |

Profiler: `sample` attaches only after the process exists (about 170 ms after launch
with `-wait`) and gave 117 samples for bmc-ibm-12, missing the parse and preprocessing
phases entirely. So all four profiles below come from the Instruments Time Profiler
(1 ms interval, from the first instruction to exit):

```
xcrun xctrace record --template 'Time Profiler' --output X.trace --launch -- \
    optimized/build/minisat -rnd-seed=1 -verb=1 <cnf>
xcrun xctrace export --input X.trace \
    --xpath '/trace-toc/run[@number="1"]/data/table[@schema="time-profile"]' > X.xml
python3 tmp/prof/parse_profile.py X.xml optimized/build/minisat 10
```

`parse_profile.py` re-symbolizes the sampled addresses with `atos` without inline
expansion, so helpers that `-O3` inlined (`vec::operator[]`, `value()`, `Heap::...`)
are counted inside the function they were inlined into. "self" is time with the
function on top of the stack, "incl" is time with it anywhere on the stack. All
names are in namespace `Minisat`, omitted below.

As a cross-check, `sample minisat 120 1 -wait -mayDie` on uuf250-087 (4,628 samples)
gives the same numbers within a point: propagate 73.1 %, analyze 15.2 %, litRedundant
4.5 %, cancelUntil 2.1 %, reduceDB sort 1.8 %, relocAll 1.2 %, pickBranchLit 1.0 %
(the only ranking difference is relocAll and pickBranchLit swapping places).

The hot-line lists below leave out the samples `atos` could not assign to a line
(`Solver.cc:0`): 7.9 % of the run on both uuf250 instances, 7.7 % on qg5-13 and
10.0 % on bmc-ibm-12.

## uuf250-087 (5,645 samples, 5.6 s)

| # | self % | incl % | function |
|---|---|---|---|
| 1 | 73.3 | 73.3 | `Solver::propagate()` |
| 2 | 15.4 | 19.5 | `Solver::analyze(CRef, vec<Lit>&, int&)` |
| 3 | 4.0 | 4.0 | `Solver::litRedundant(Lit)` |
| 4 | 1.9 | 2.2 | `Solver::cancelUntil(int)` |
| 5 | 1.4 | 1.4 | `sort<CRef, reduceDB_lt>` (called from `reduceDB`) |
| 6 | 1.3 | 1.3 | `Solver::pickBranchLit()` |
| 7 | 1.3 | 1.3 | `Solver::relocAll(ClauseAllocator&)` (garbage collection) |
| 8 | 0.3 | 0.3 | `vec<Lit>::growTo(int)` |
| 9 | 0.3 | 0.3 | `Heap<int, VarOrderLt>::insert(int)` |
| 10 | 0.3 | 99.8 | `Solver::search(int)` |

Phases: parse 0.0 %, preprocessing (`SimpSolver::eliminate`) 0.0 %, search 99.8 %
(`reduceDB` 1.7 % of that).

Hottest lines inside `propagate()` (percent of total run time):
`Solver.cc:541` 12.9 (new watch found: `c[1] = c[k]; c[k] = false_lit`, followed by
`watches[~c[1]].push(w)` on 542), `:524` 10.1 (`i->cref`, then `ca[cr]`: first touch of the clause),
`:521` 7.6 (blocker true, copy watcher), `:528` 7.3 (swap `c[0]`/`c[1]`),
`:539` 7.2 and `:540` 4.0 (scan for a non-false literal), `:520` 3.4 (blocker test).

## uuf250-077 (5,339 samples, 5.3 s)

| # | self % | incl % | function |
|---|---|---|---|
| 1 | 73.1 | 73.1 | `Solver::propagate()` |
| 2 | 14.6 | 19.5 | `Solver::analyze(CRef, vec<Lit>&, int&)` |
| 3 | 4.7 | 4.7 | `Solver::litRedundant(Lit)` |
| 4 | 1.9 | 2.3 | `Solver::cancelUntil(int)` |
| 5 | 1.6 | 1.6 | `sort<CRef, reduceDB_lt>` (called from `reduceDB`) |
| 6 | 1.3 | 1.3 | `Solver::pickBranchLit()` |
| 7 | 1.1 | 1.1 | `Solver::relocAll(ClauseAllocator&)` |
| 8 | 0.4 | 99.9 | `Solver::search(int)` |
| 9 | 0.4 | 0.4 | `Heap<int, VarOrderLt>::insert(int)` |
| 10 | 0.3 | 0.3 | `vec<Lit>::growTo(int)` |

Phases: parse 0.0 %, preprocessing 0.0 %, search 99.9 % (`reduceDB` 1.9 %).
Hottest `propagate()` lines: `:541` 12.8, `:524` 10.9, `:521` 7.4, `:528` 7.0,
`:539` 6.7, `:540` 4.0, `:530` 3.2.

## qg5-13 (1,035 samples, 1.0 s)

| # | self % | incl % | function |
|---|---|---|---|
| 1 | 84.6 | 84.6 | `Solver::propagate()` |
| 2 | 5.7 | 8.6 | `Solver::analyze(CRef, vec<Lit>&, int&)` |
| 3 | 2.9 | 2.9 | `Solver::litRedundant(Lit)` |
| 4 | 1.4 | 1.4 | `SimpSolver::backwardSubsumptionCheck(bool)` |
| 5 | 1.3 | 1.6 | `Solver::cancelUntil(int)` |
| 6 | 0.7 | 0.8 | `Solver::removeSatisfied(vec<CRef>&)` |
| 7 | 0.7 | 0.7 | `Solver::pickBranchLit()` |
| 8 | 0.4 | 0.4 | `Heap<int, VarOrderLt>::insert(int)` |
| 9 | 0.3 | 96.9 | `Solver::search(int)` |
| 10 | 0.2 | 1.0 | `parse_DIMACS<SimpSolver>` |

Phases: parse 1.0 %, preprocessing 1.9 %, `Solver::simplify` 0.9 %, search 96.9 %
(no `reduceDB` samples at all).
Hottest `propagate()` lines: `:541` **24.5**, `:524` 11.9, `:528` 9.0, `:540` 5.6,
`:521` 5.4, `:520` 3.4, `:539` 3.1.

## bmc-ibm-12 (409 samples, 0.41 s)

| # | self % | incl % | function |
|---|---|---|---|
| 1 | 48.4 | 48.7 | `Solver::propagate()` |
| 2 | 8.3 | 9.5 | `SimpSolver::backwardSubsumptionCheck(bool)` |
| 3 | 5.9 | 10.8 | `Solver::analyze(CRef, vec<Lit>&, int&)` |
| 4 | 4.9 | 4.9 | `Solver::litRedundant(Lit)` |
| 5 | 3.7 | 3.7 | `Heap<int, SimpSolver::ElimLt>::percolateDown(int)` |
| 6 | 3.7 | 11.2 | `SimpSolver::eliminateVar(int)` |
| 7 | 2.2 | 11.0 | `SimpSolver::addClause_(vec<Lit>&)` |
| 8 | 2.2 | 2.4 | `Solver::cancelUntil(int)` |
| 9 | 2.0 | 2.0 | `Solver::pickBranchLit()` |
| 10 | 1.2 | 1.2 | `_nanov2_free` (libsystem_malloc) |

Just outside the top 10: `_realloc` 1.0 % self / 5.1 % incl (almost all of it `vec`
growth during parsing and clause adding), `parse_DIMACS` 1.0 % self / 10.8 % incl,
`ClauseAllocator::alloc` 1.0 %, `detachClause` 1.0 %, `relocAll` 1.0 %.

Phases: parse 10.8 %, preprocessing (`SimpSolver::eliminate`) 23.2 %,
`Solver::simplify` 1.5 %, search 65.3 %.
Hottest `propagate()` lines: `:524` 11.0, `:521` 5.4, `:520` 4.4, `:541` 2.7,
`:546` 2.7, `:528` 2.2, `:558` 2.0 (`ws.shrink`).

## Where the profiles differ

1. **The two uuf250 instances are the same profile.** Every entry agrees within
   about one point (propagate 73 %, analyze 15 % self / 19.5 % incl, litRedundant
   4-5 %, cancelUntil 2 %, reduceDB sorting 1.5 %, garbage collection 1.2 %). Random
   3-SAT with 250 variables and 1,065 clauses has nothing to parse or preprocess,
   and with a million conflicts the per-conflict work (`analyze`, `litRedundant`,
   `cancelUntil`, the periodic `reduceDB`/`relocAll`) adds up to about a quarter of
   the run. For profiling purposes one of the two is enough.

2. **qg5-13 is propagation-bound even more heavily (85 %), and the cost sits in the
   watch move.** Line 541 alone is 24.5 % of the run (vs 13 % on uuf250), and
   lines 539-541 together are 33 %. The clauses are not long (the file has 32 %
   binary and 68 % ternary clauses, and only 507 of length 10-13), so this is not
   a long scan; it is the cost of moving a watch: the `value(c[k])` lookups in the
   `assigns` array right before, the two stores into the clause, and
   `watches[~c[1]].push(w)` on the next line, which touches a second watch list
   (2,197 variables but 125k clauses in the file, so the watch lists are long and
   the watch and clause arrays are several MB). The sampled instruction is the
   `c[1] = c[k]` store at 541; a sampling profiler cannot tell whether the time
   is really spent there or in the loads just before it, so treat "the watch
   move is expensive" as the finding and the memory-latency explanation as a
   hypothesis to confirm with counters. Conflict analysis is small here (8.6 %
   incl): 30k conflicts versus 1.1M on uuf250. Preprocessing and parsing are 3 %
   together.

3. **bmc-ibm-12 is the only instance where search is not the whole story.** Search
   is 65 % of the run; `SimpSolver::eliminate` (variable elimination plus backward
   subsumption, with its `ElimLt` heap) is 23 % and DIMACS parsing 11 %, of which
   2.4 points are `realloc` from growing `vec`s one clause at a time. Inside
   `propagate` the hot lines are 524/521/520, i.e. walking the watch lists,
   testing blockers and fetching the clause; line 541 is only 2.7 %, because 74 %
   of the clauses are binary and the watch is usually settled by the blocker or by
   `c[0]`. With 40k variables and 190k clauses the data is much larger than on
   the other instances; the cost concentrating on the first touch of each watcher
   and clause (line 524) fits a cache-miss explanation, but that is a hypothesis,
   not something these samples measure. The allocator only matters here: 5.1 % of
   the run is self time in libsystem_malloc (`_realloc`, `nanov2_malloc`,
   `_nanov2_free`, ...), against 0.6 % on qg5-13 and under 0.1 % on uuf250.

4. Consequences for optimization work: anything that speeds up `propagate` (watch
   list layout, blocker hit rate, clause header access on line 524) pays off on
   all four instances; the watch move (539-542) matters most on qg5-13;
   conflict analysis (`analyze` including `litRedundant`) is worth 19.5 % on the
   uuf250 instances, about 9-11 % on the other two; and preprocessing and parsing
   (`eliminate`, `backwardSubsumptionCheck`, `vec` growth in `parse_DIMACS`) only
   register on bmc-ibm-12, where they are a third of a 0.4 s run. These are four
   instances, not the four families; check the other QG and bmc instances before
   generalizing.

Raw data: `tmp/prof/<instance>.trace` (Instruments traces), `tmp/prof/<instance>.x.xml`
(exported sample tables), `tmp/prof/<instance>.top.txt` (summaries),
`tmp/prof/uuf250-087.sample.txt` (the `sample` cross-check).
