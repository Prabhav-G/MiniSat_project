# Candidate optimizations for `optimized/minisat/core/Solver.cc`

Based on reading `Solver::propagate` (Solver.cc:506-561), `Solver::analyze` (296-384)
and `Solver::litRedundant` (388-446) against the line-level data in `PROFILE.md`.
Nothing has been changed yet; every candidate below is a proposal.

## Ground rules that every candidate must respect

The harness checks that `conflicts`, `decisions` and `propagations` stay identical,
so the search must be bit-for-bit the same. Concretely, a change must keep:

1. the order in which literals are enqueued on the trail (watch lists are walked
   front to back, surviving watchers keep their relative order, a moved watcher is
   appended at the end of the other list);
2. the clause returned as the conflict, and the literal order inside it when
   `analyze` reads it (`analyze` reads a conflict clause from index 0 and a reason
   clause from index 1, assuming `c[0]` is the implied literal);
3. the order of `varBumpActivity` calls. Each bump does `order_heap.decrease(v)`
   immediately, and the heap layout (hence the tie-break between equal
   activities in `pickBranchLit`) depends on that order. Batching or reordering
   bumps is therefore not allowed even though the activity sums would be the same;
4. the exact floating-point operations on `activity[]` and `var_inc` (no
   `-ffast-math`, no reassociation);
5. the result of clause minimization (`litRedundant` must return the same boolean
   for the same literal; the `conflict literals ... % deleted` line in the solver
   output is a direct check).

What is *not* observable, and can be exploited: the order of the two watched
literals `c[0]`/`c[1]` in memory between two visits of the clause (it is
re-normalized on every visit before anything reads it), the contents of the
`seen_failed`/`seen_removable` memo marks (they are cleared after each `analyze`),
and anything the compiler does to instruction scheduling.

Working-set sizes, which decide what "cache" means per instance (Apple M-series:
128 KB L1d per performance core, L2 in the 12-16 MB range):

| instance | vars | clauses + learnts (peak) | approx. hot data | where it lives |
|---|---|---|---|---|
| uuf250-087 | 250 | 1,065 + ~2,400 (max_learnts starts at 355 and grows 1.1x per adjust) | ~150 KB clause arena + ~55 KB watchers + <10 KB per-variable arrays | L1/L2 boundary |
| qg5-13 | 2,197 | 77k + up to ~30k (no `reduceDB` ever ran) | ~5 MB clauses (learnts average 29 literals) + ~1.7 MB watchers | L2, not L1 |
| bmc-ibm-12 | 39,598 | 193k + 7k | 31 MB "Memory used"; per-variable arrays alone are ~1 MB | L2/DRAM |

So "helps uuf250" means fewer instructions and fewer dependent loads on the hot
path; "helps large instances" means fewer cache misses.

## Ranked candidates

### 1. Keep the two watched literals in registers and skip the swap store when the clause is already satisfied (propagate, lines 527-528, 533-536, 541-542)

**What changes.** Replace

```
if (c[0] == false_lit) c[0] = c[1], c[1] = false_lit;   // 527-528
Lit first = c[0];                                         // 533
...
c[1] = c[k]; c[k] = false_lit; watches[~c[1]].push(w);    // 541-542
```

with: load `c0 = c[0]`, `c1 = c[1]` once; `first = (c0 == false_lit) ? c1 : c0`;
test the blocker/`first` satisfied case *before* writing anything back; when a
new watch `c[k]` is found, write `c[0] = first; c[1] = c[k]; c[k] = false_lit`
(the `c[0]` store only if it changed) and push to `watches[~newlit]` using the
register copy instead of re-reading `c[1]`; in the unit/conflict path write the
normalized order `[first, false_lit]` exactly as today.

**Why it should help.** Lines 528 and 541 are 7.3 % + 12.9 % on uuf250 and
9.0 % + 24.5 % on qg5-13. In the "satisfied by `first`" case the current code
performs two stores to the clause that nothing will read before the next
normalization; dropping them removes dirty lines and store-buffer traffic. On the
new-watch path the `watches[~c[1]]` index currently depends on a store-to-load
forward of the value just written; using the register shortens the dependent
chain feeding the second watch list (header load, data load, store, size store).
A sampling profiler cannot say how much of line 541 is the store itself versus
the `assigns` loads before it, so expect a few percent on uuf250 and more on
qg5-13 where line 541 dominates; measure before claiming more.

**Search order.** Unchanged. The literal order inside a clause is only read by
`analyze`/`litRedundant`/`analyzeFinal`/ccmin-mode-1 on conflict and reason
clauses, and both of those paths still write the normalized `[first, false_lit]`
order. A clause whose two watched literals are left un-swapped is re-normalized
on the next visit through either watch, and the result (`c[1]` = currently false
literal, `c[0]` = the other watched literal) is the same either way. `locked()`
reads `c[0]`, but for a clause that is not a reason the stale `c[0]` is a false
literal, so `locked()` still returns false; `satisfied()`, `removeSatisfied`,
`calcAbstraction` and `relocAll` are order-independent.

**Risk.** Low to medium. The reasoning above has to hold for every reader of
clause literal order; the ones listed are all of them in `core/`, but
`simp/SimpSolver.cc` (`strengthenClause`, `backwardSubsumptionCheck`) must stay
pre-search only, which is the case for the benchmark's single `solve()` call.
Verify with the harness on all four families (counters identical).

**Helps.** uuf250 (in-cache, fewer stores on the hottest lines), qg5-13 (largest
absolute share), bmc-ibm-12 slightly (line 541 is only 2.7 % there).

### 2. Build with profile-guided optimization and the native CPU target (no source change)

**What changes.** Add `-fprofile-instr-generate`, run a training set that is
not the measured instances (for example 10 other uuf250 files plus one QG and
one bmc), `llvm-profdata merge`, rebuild with `-fprofile-instr-use` and
`-mcpu=native`. Keep `-O3`; do not add `-ffast-math`.

**Why it should help.** The propagate loop has three data-dependent branches per
watcher (blocker true at 520, `first` true at 535, the scan at 540), and the
analyze loop two (`seen`, `level`). The compiler currently guesses their layout;
PGO lays out the taken paths straight-line and reduces mispredict and
front-end cost, which is what dominates when the data is in cache. Reports for
CDCL solvers built with PGO are typically in the 5-15 % range; this is the one
candidate whose gain on uuf250 is likely to exceed the 1.09x run-to-run noise
on its own.

**Search order.** Unchanged by construction: PGO only affects code layout and
inlining decisions. The FP semantics are untouched as long as `-ffast-math` and
`-Ofast` stay out.

**Risk.** Low. The build recipe in `optimized/build` becomes two-stage; the
profile must be regenerated after every source change or clang warns and falls
back to the default heuristics (harmless, but the measurement is then of the
wrong binary). The gain must be re-checked across the whole uuf250 set, not one
instance.

**Helps.** All instances; most on uuf250.

### 3. Software prefetch of the clause behind the next watchers (propagate, line 524)

**What changes.** At the top of the watcher loop add
`__builtin_prefetch(ca.lea((i + D)->cref))` for a small distance D (2-4),
guarded by `i + D < end`, and when `qhead + 1 < trail.size()` prefetch the
`vec<Watcher>` header of `watches[trail[qhead + 1]]` before walking the current
list. Optionally skip the prefetch when the watcher's blocker is already true
(it will not be dereferenced), at the cost of one extra `assigns` load.

**Why it should help.** Line 524 (`i->cref` then `ca[cr]`, the first touch of
the clause) is 10-12 % on every instance, and the clause arena of qg5-13
(~5 MB) and bmc-ibm-12 do not fit in L1. The watcher array itself is walked
sequentially and the hardware prefetcher handles it; the clause address is
only known once the watcher is loaded, which is what the software prefetch
covers. The second watch list touched on line 542 cannot be prefetched (its
index is only known after the scan).

**Search order.** Unchanged; a prefetch is a hint with no architectural effect.

**Risk.** Low. On uuf250 the data is already in L1/L2, so the extra
instructions can cost about a percent; keep the distance small and measure on
uuf250 separately. Prefetching past `end` must be avoided (it is harmless on
arm64 but reads uninitialized `cref` values, which would trip ASan).

**Helps.** qg5-13 and bmc-ibm-12 (large instances only); neutral to slightly
negative on uuf250.

### 4. Hoist values that the compiler must reload because of `char` stores (analyze, lines 316-325; propagate, 535/547)

**What changes.** In `analyze`, read `decisionLevel()` (that is
`trail_lim.size()`), `c.size()`, and the base pointers of `seen`, `vardata`,
`activity` and the heap index map into locals before the `for (j ...)` loop,
and use them inside it. In `propagate`, compute `value(first)` once and reuse it
at line 547 instead of a second `assigns` load after the stores on line 541.

**Why it should help.** `seen` is a `VMap<char>`; under C++ aliasing rules a
store through a `char` lvalue may modify any object, so after every
`seen[var(q)] = 1` the compiler has to reload `trail_lim.sz`, the clause header
(for `c.size()`), and every base pointer it needs, from memory. The same holds
for `assigns` (`lbool` wraps a `uint8_t`) after the `Lit` stores at 541. On
uuf250, `analyze` is 15 % self time with ~17 literals per conflict and 1.1 M
conflicts, so the per-literal body is run ~19 M times; dropping several
reloads per iteration is worth a few percent of that 15 %. Confirm the reloads
in the disassembly (`objdump -d --disassemble-symbols=__ZN7Minisat6Solver7analyzeEjRNS_3vecINS_3LitEiEERi optimized/build/minisat`)
before relying on this; if clang already hoists them the change is a no-op.

**Search order.** Unchanged: the hoisted values are loop invariants (nothing in
the loop pushes to `trail_lim`, resizes `vardata`/`activity`/`seen`, or
changes the clause size). `varBumpActivity` rescales `activity[]` in place
without reallocating, so the base pointer stays valid.

**Risk.** Very low. Purely local, no data-structure change.

**Helps.** uuf250 (analyze is 19.5 % inclusive there, 9-11 % elsewhere).

### 5. Fail fast in `litRedundant` with the abstract-level test (litRedundant, lines 403-412)

**What changes.** In `analyze`, after the first loop, compute
`abstract_levels |= abstractLevel(var(out_learnt[i]))` over `i >= 1`. In
`litRedundant`, extend the "cannot be removed" test on line 405 to
`reason(var(l)) == CRef_Undef || seen[var(l)] == seen_failed || (abstractLevel(var(l)) & abstract_levels) == 0`.
`Solver::abstractLevel` already exists (Solver.h:349) but has been unused since
commit `3ad9f5d` replaced the recursive version with the stack-and-memo version.

**Why it should help.** A literal whose decision level does not appear among the
learnt clause's levels can never be redundant: the reason clause of any literal
at level L > 0 contains another literal at level L (propagation runs to a
fixpoint before each decision, and the asserting literal's reason contains
`out_learnt[1]` at the backtrack level), so a chain of reasons starting at an
"unknown" level never reaches only clause literals and level 0. Today such a
literal is explored to the bottom of its reason chain and only then marked
`seen_failed`. uuf250 minimizes 23 % of the literals, so most `litRedundant`
calls end in failure; litRedundant is 4-5 % self time there.

**Search order.** Unchanged. The test is a sound shortcut: it returns `false`
only where the full exploration would also return `false`, and the only side
effects it skips are `seen_failed` marks on intermediate variables, which are
memo entries cleared at the end of `analyze`. The `conflict literals` and
`% deleted` lines in the solver output must stay identical; that is the check.

**Risk.** Low. The soundness argument depends on the level invariant above, which
is standard CDCL (the pre-3ad9f5d MiniSat used exactly this filter).

**Helps.** uuf250 mostly (1-3 % of the run); qg5-13/bmc less (litRedundant is
3-5 % there but conflicts are few).

### 6. Binary-clause watchers that never touch the clause on the implication path (propagate, lines 524-549; analyze/litRedundant/analyzeFinal/ccmin-1 readers)

**What changes.** Mark binary clauses in the `Watcher` (one spare bit in
`cref`, or a third field). For such a watcher, when the blocker is undefined,
call `uncheckedEnqueue(blocker, cr)` without loading the clause; when it is
false, load the clause, normalize it to `[blocker, false_lit]` and report the
conflict as today. Because the clause is no longer normalized on the
implication path, every reader of a *reason* clause (`analyze` line 316,
`litRedundant` line 400, `analyzeFinal`, the ccmin-mode-1 loop at 352) must
skip the implied literal by comparing it with `p` instead of assuming it is at
index 0, and `removeClause`'s `locked(c)` test must find a binary reason even
when `c[0]` is the false literal.

**Why it should help.** 74 % of bmc-ibm-12's clauses and 32 % of qg5-13's are
binary. On those, line 524 (the clause load) is the top line of propagate
(11-12 %), and the load is pure overhead: the blocker already is the other
literal, so the clause carries no information the watcher does not have.

**Search order.** Unchanged if done carefully: the enqueued literal, its
reason reference, the surviving watcher (`Watcher(cr, first)` with `first ==
blocker` for binaries) and the conflict clause are all the same; the readers
listed above visit the same literal in the same order because for non-binary
reasons `c[0] == p` still holds (normalized at enqueue, untouched while a
reason) and a binary reason has exactly one other literal.

**Risk.** High. Four readers of reason clauses plus `locked()`/`removeClause`
and `relocAll` have to be audited; a miss gives wrong learnt clauses, which the
counters would catch, or a dangling reason after garbage collection, which they
might not. uuf250 gains nothing (3-SAT, learnt clauses average 13 literals).

**Helps.** bmc-ibm-12 (large, binary-heavy) and to a lesser degree qg5-13; not
uuf250.

### 7. `ws.shrink(i - j)` → `ws.shrink_(i - j)` and skip the `dirty` check in `watches.lookup(p)` (propagate, lines 513 and 558)

**What changes.** `vec::shrink` runs a loop calling `~Watcher()` per removed
element; `vec::shrink_` (Vec.h:66) subtracts the count. `watches.lookup(p)`
tests `dirty[p]` on every propagated literal; after `cleanAll()` (which
`removeSatisfied`/`reduceDB` call through `garbageCollect`/`simplify`) the flag
is almost always zero, so a cheaper path is to keep `lookup` but make sure
`clean` is out of line.

**Why it should help.** Line 558 is 2.0 % on bmc-ibm-12 (long watch lists, many
compactions); with -O3 the destructor loop should already fold to one
subtraction, so check the disassembly first. This is a clean-up more than an
optimization.

**Search order.** Unchanged.

**Risk.** None.

**Helps.** bmc-ibm-12 marginally; nothing measurable on uuf250.

## Considered and rejected (would change the search)

- **Separate binary watch lists, or any reordering of watch lists** (sorting by
  size, moving binaries first): changes the enqueue order.
- **Deferring `order_heap.decrease` until the end of `analyze`**: the activity
  sums are identical but the heap layout, and with it the tie-break among equal
  activities in `pickBranchLit`, can differ.
- **Choosing a true literal as the new watch, or updating the blocker to
  another satisfied literal**: changes which clause fires when.
- **Chronological backtracking, LBD-based `reduceDB`, Luby changes**: different
  search altogether.
- **Moving the learnt activity in front of the literals** so `claBumpActivity`
  touches the header line: search-safe but needs `Clause`, `ClauseAllocator`,
  `shrink`, `calcAbstraction` and `strengthen` changes; the gain is confined to
  long learnt clauses on large instances. Keep for later if qg5-13 remains
  `analyze`-bound after candidates 1 and 3.

## Suggested order of work

Implement 4, 5 and 7 first (local, trivially verifiable, give the harness a
chance to catch any counter drift), then 1, then measure 2 on top. Add 3 only
if the QG and bmc families matter for the final metric, and treat 6 as a
separate project with its own review.
