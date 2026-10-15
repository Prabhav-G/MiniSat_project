import csv, os, subprocess

ROOT = os.path.expanduser("~/sat-opt")
BINS = {"baseline": ROOT + "/bin/minisat_baseline",
        "pgo_native": ROOT + "/bin/minisat_pgo_native"}
DIR = ROOT + "/bench/heldout_final"
TMP = ROOT + "/tmp/models"
os.makedirs(TMP, exist_ok=True)

def read_cnf(path):
    clauses, cur = [], []
    with open(path) as f:
        for line in f:
            if line[:1] == "%":
                break
            if line[:1] in ("c", "p"):
                continue
            for tok in line.split():
                v = int(tok)
                if v == 0:
                    clauses.append(cur)
                    cur = []
                else:
                    cur.append(v)
    return clauses

def read_model(path):
    lines = open(path).read().split("\n")
    if not lines or lines[0].strip() != "SAT":
        return None
    return [int(x) for x in " ".join(lines[1:]).split() if x != "0"]

def unsatisfied(clauses, model):
    val = {abs(l): l > 0 for l in model}
    return sum(1 for c in clauses if not any(val.get(abs(l)) == (l > 0) for l in c))

sat = [r["instance"] for r in csv.DictReader(open(ROOT + "/results/heldout_base.csv"))
       if r["result"] == "SATISFIABLE"]
sat = sorted(set(os.path.basename(s) for s in sat))
print(len(sat), "SAT instances")

checked, failures = 0, 0
for name in sat:
    cnf = os.path.join(DIR, name)
    clauses = read_cnf(cnf)
    for label, binary in BINS.items():
        out = os.path.join(TMP, label + "_" + name[:12] + ".model")
        subprocess.run([binary, "-rnd-seed=1", cnf, out],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=400)
        model = read_model(out) if os.path.exists(out) else None
        bad = None if model is None else unsatisfied(clauses, model)
        ok = bad == 0
        checked += 1
        failures += 0 if ok else 1
        print(label, name[:40], "OK" if ok else "FAIL (unsatisfied clauses: %s)" % bad, flush=True)

print("models checked:", checked, "| failures:", failures)