#!/usr/bin/env bash
# Reproduces the MiniSat experiments (see README.md).
# Usage: ./reproduce.sh [quick|full|heldout]
#   quick   : build baseline + PGO variants, correctness gate on small subsets
#   full    : all four training families, 3 repeats
#   heldout : 14 SAT Competition 2025 instances; needs URI_FILE (see README)
# Requires: git, cmake, make, python3, curl, tar. PGO needs macOS (xcrun llvm-profdata).
set -euo pipefail

MODE="${1:-quick}"
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
UPSTREAM=37dc6c67e2af26379d88ce349eb9c4c6160e8543
JOBS=4
FAIL=0

for t in git cmake make python3 curl tar; do
  command -v "$t" >/dev/null || { echo "missing tool: $t"; exit 1; }
done
mkdir -p bin out work bench/train

echo "== 1. baseline source: upstream $UPSTREAM + baseline-build-fix.patch =="
[ -d work/minisat/.git ] || git clone -q https://github.com/niklasso/minisat work/minisat
( cd work/minisat
  git reset -q --hard "$UPSTREAM"
  git apply "$ROOT/baseline-build-fix.patch"
  git add -A minisat
  SUB=$(git rev-parse "$(git write-tree):minisat")
  if [ -f "$ROOT/expected_minisat_tree.txt" ]; then
    [ "$SUB" = "$(cat "$ROOT/expected_minisat_tree.txt")" ] || { echo "ERROR: patched source differs from the measured source"; exit 1; }
    echo "patched source matches the measured source (tree $SUB)"
  else
    echo "WARNING: expected_minisat_tree.txt missing; source not verified"
  fi )

build() { # build_dir [extra cmake flags]
  local d="$1"; shift
  cmake -S work/minisat -B "work/$d" -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_POLICY_VERSION_MINIMUM=3.5 "$@" >/dev/null
  cmake --build "work/$d" --target minisat_simp -j"$JOBS" >/dev/null
  [ -x "work/$d/minisat" ] || { echo "build failed: work/$d/minisat not found"; exit 1; }
}

echo "== 2. build baseline =="
build build_base
cp work/build_base/minisat bin/minisat_baseline

echo "== 3. training benchmarks (SATLIB) =="
B=https://www.cs.ubc.ca/~hoos/SATLIB/Benchmarks/SAT
fetch() { # url name
  if [ ! -d "bench/train/$2" ]; then
    curl -fsSL -o "bench/train/$2.tar.gz" "$1"
    mkdir -p "bench/train/$2"
    tar xzf "bench/train/$2.tar.gz" -C "bench/train/$2"
  fi
}
fetch "$B/RND3SAT/uuf250-1065.tar.gz" uuf250-1065
fetch "$B/GCP/flat200-479.tar.gz" flat200-479
fetch "$B/BMC/bmc.tar.gz" bmc
fetch "$B/QG/QG.tar.gz" QG
if [ ! -f bench/train/.cleaned ]; then
  # SATLIB random-3-SAT files end with a stray '%' line that MiniSat's parser rejects
  find bench/train -name '*.cnf' -print0 | while IFS= read -r -d '' f; do
    awk '/^%/{exit} {print}' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
  done
  touch bench/train/.cleaned
fi

echo "== 4. PGO builds (training set: results/pgo_training_set_relative.txt) =="
if command -v xcrun >/dev/null && xcrun --find llvm-profdata >/dev/null 2>&1; then
  build build_gen "-DCMAKE_CXX_FLAGS=-fprofile-instr-generate"
  rm -rf work/profraw; mkdir -p work/profraw
  while IFS= read -r rel || [ -n "$rel" ]; do
    [ -n "$rel" ] || continue
    LLVM_PROFILE_FILE="$ROOT/work/profraw/%p.profraw" \
      work/build_gen/minisat -rnd-seed=1 "bench/train/$rel" >/dev/null 2>&1 || true
  done < results/pgo_training_set_relative.txt
  xcrun llvm-profdata merge -output=work/pgo.profdata work/profraw/*.profraw
  build build_pgo "-DCMAKE_CXX_FLAGS=-fprofile-instr-use=$ROOT/work/pgo.profdata"
  cp work/build_pgo/minisat bin/minisat_pgo
  build build_pgo_native "-DCMAKE_CXX_FLAGS=-fprofile-instr-use=$ROOT/work/pgo.profdata -mcpu=native"
  cp work/build_pgo_native/minisat bin/minisat_pgo_native
else
  echo "WARNING: xcrun/llvm-profdata not found; skipping PGO variants"
fi

echo "== 5. correctness gate + timing (mode: $MODE) =="
variants=""
for v in pgo pgo_native; do [ -x "bin/minisat_$v" ] && variants="$variants $v"; done
[ -n "$variants" ] || { echo "no variants were built"; exit 1; }
FIRST=${variants# }; FIRST=${FIRST%% *}

run_family() { # label dir repeat timeout
  local label="$1" dir="$2" rep="$3" to="$4" v
  for v in $variants; do
    python3 ab.py --bin-a bin/minisat_baseline --bin-b "bin/minisat_$v" --dir "$dir" \
      --repeat "$rep" --timeout "$to" \
      --out-a "out/${label}_$v.base.csv" --out-b "out/${label}_$v.new.csv" > "out/${label}_$v.log"
    if python3 compare.py --base "out/${label}_$v.base.csv" --new "out/${label}_$v.new.csv" \
         > "out/${label}_$v.compare.txt"; then
      echo "[$label / $v] counters identical.  $(grep -E 'geometric mean' "out/${label}_$v.compare.txt" || true)"
    else
      echo "[$label / $v] MISMATCH, see out/${label}_$v.compare.txt"; FAIL=1
    fi
  done
}

check_recorded() { # label recorded_csv
  [ -f "$2" ] || { echo "[$1] (no recorded baseline $2; skipped)"; return; }
  if python3 compare.py --base "$2" --new "out/${1}_${FIRST}.base.csv" \
       > "out/${1}_recorded.compare.txt"; then
    echo "[$1] fresh baseline counters match the recorded baseline ($2)"
  else
    echo "[$1] fresh baseline DIFFERS from the recorded one, see out/${1}_recorded.compare.txt"; FAIL=1
  fi
}

case "$MODE" in
  quick)
    mkdir -p bench/quick_uuf250
    find bench/train/uuf250-1065 -name '*.cnf' | sort | head -10 | while IFS= read -r f; do
      ln -sf "$ROOT/$f" "bench/quick_uuf250/$(basename "$f")"
    done
    run_family qg bench/train/QG 1 120;                check_recorded qg baseline_qg.csv
    run_family bmc bench/train/bmc 1 120;              check_recorded bmc baseline_bmc.csv
    run_family flat200 bench/train/flat200-479 1 120;  check_recorded flat200 baseline_flat200.csv
    run_family uuf250_subset bench/quick_uuf250 1 120
    ;;
  full)
    run_family qg bench/train/QG 3 120;                check_recorded qg baseline_qg.csv
    run_family bmc bench/train/bmc 3 120;              check_recorded bmc baseline_bmc.csv
    run_family flat200 bench/train/flat200-479 3 120;  check_recorded flat200 baseline_flat200.csv
    run_family uuf250 bench/train/uuf250-1065 3 120;   check_recorded uuf250 baseline_uuf250.csv
    ;;
  heldout)
    : "${URI_FILE:?set URI_FILE to the SAT Competition 2025 track_main_2025.uri path or URL (see README)}"
    python3 - "$URI_FILE" <<'PY'
import csv, os, subprocess, sys, urllib.request
src = sys.argv[1]
text = (urllib.request.urlopen(src).read().decode()
        if src.startswith("http") else open(src).read())
urls = text.split()
os.makedirs("bench/heldout_final", exist_ok=True)
bad = 0
for row in csv.DictReader(open("bench/heldout_manifest.csv")):
    name, size = row["filename"], int(row["size_bytes"])
    dest = os.path.join("bench/heldout_final", name)
    if os.path.exists(dest) and os.path.getsize(dest) == size:
        continue
    h = name.split("-")[0]
    cand = [u for u in urls if h in u]
    if len(cand) != 1:
        print("cannot find a unique URL for", name, cand); bad += 1; continue
    tmp = dest + ".download"
    urllib.request.urlretrieve(cand[0], tmp)
    if subprocess.run(["xz", "-t", tmp], capture_output=True).returncode == 0:
        with open(dest, "wb") as out:
            subprocess.run(["xz", "-dc", tmp], stdout=out, check=True)
        os.remove(tmp)
    else:
        os.replace(tmp, dest)
    if os.path.getsize(dest) != size:
        print("size mismatch for", name); bad += 1
sys.exit(1 if bad else 0)
PY
    [ -x bin/minisat_pgo_native ] || { echo "pgo_native was not built"; exit 1; }
    variants="pgo_native"
    run_family heldout bench/heldout_final 3 300
    ;;
  *) echo "usage: $0 [quick|full|heldout]"; exit 1 ;;
esac

echo
if [ "$FAIL" -eq 0 ]; then
  echo "ALL CHECKS PASSED: every counter identical. Speedups near 1.0 are expected (see README)."
else
  echo "FAILED: see out/*.compare.txt"; exit 1
fi