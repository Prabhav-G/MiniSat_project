import csv, glob, os, subprocess, time

ROOT = os.path.expanduser("~/sat-opt")
CAD = ROOT + "/tools/cadical/build/cadical"
DRAT = ROOT + "/tools/drat-trim/drat-trim"
PROOFS = ROOT + "/tmp/proofs"
OUT = ROOT + "/results/cross_check.csv"
os.makedirs(PROOFS, exist_ok=True)

verdict = {}
for fn in ["results/heldout_base.csv", "baseline_uuf250.csv",
           "baseline_qg.csv", "baseline_bmc.csv"]:
    for r in csv.DictReader(open(os.path.join(ROOT, fn))):
        verdict[os.path.basename(r["instance"])] = r["result"]

def find(pattern, limit=None):
    fs = sorted(glob.glob(os.path.join(ROOT, pattern), recursive=True))
    return fs[:limit] if limit else fs

files = (find("bench/train/QG/**/*.cnf")
         + find("bench/train/bmc/**/*.cnf")
         + find("bench/train/uuf250-1065/**/*.cnf", 15)
         + find("bench/heldout_final/*.cnf"))

done = set()
if os.path.exists(OUT):
    done = {r["instance"] for r in csv.DictReader(open(OUT))}
todo = [f for f in files if os.path.basename(f) not in done]
print(len(files), "instances,", len(done), "already done,", len(todo), "to do", flush=True)

new = not os.path.exists(OUT)
fh = open(OUT, "a", newline="")
w = csv.writer(fh)
if new:
    w.writerow(["instance", "minisat", "cadical", "agree", "drat_trim", "seconds"])

for i, f in enumerate(todo, 1):
    name = os.path.basename(f)
    base = verdict.get(name, "UNKNOWN")
    if base in ("TIMEOUT", "UNKNOWN"):
        continue
    proof = os.path.join(PROOFS, name[:20] + ".drat")
    t = time.time()
    try:
        p = subprocess.run([CAD, "--binary=false", f, proof],
                           capture_output=True, text=True, timeout=600)
        cad = {10: "SATISFIABLE", 20: "UNSATISFIABLE"}.get(p.returncode, "ERROR")
    except subprocess.TimeoutExpired:
        cad = "TIMEOUT"
    drat = "n/a"
    if cad == "UNSATISFIABLE":
        try:
            d = subprocess.run([DRAT, f, proof, "-t", "600"],
                               capture_output=True, text=True, timeout=700)
            drat = "VERIFIED" if "s VERIFIED" in d.stdout else "NOT_VERIFIED"
        except subprocess.TimeoutExpired:
            drat = "TIMEOUT"
    if os.path.exists(proof):
        os.remove(proof)
    row = (name, base, cad, cad == base, drat, round(time.time() - t, 1))
    w.writerow(row)
    fh.flush()
    print("[%d/%d]" % (i, len(todo)), row, flush=True)
fh.close()

rows = list(csv.DictReader(open(OUT)))
unsat = [r for r in rows if r["minisat"] == "UNSATISFIABLE"]
print("instances:", len(rows), "| disagreements:", sum(r["agree"] != "True" for r in rows),
      "| UNSAT proofs verified:", sum(r["drat_trim"] == "VERIFIED" for r in unsat), "of", len(unsat))