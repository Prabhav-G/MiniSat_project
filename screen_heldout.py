import csv, glob, os, subprocess, time
from concurrent.futures import ThreadPoolExecutor

BIN = os.path.expanduser("~/sat-opt/bin/minisat_baseline")
DIR = os.path.expanduser("~/sat-opt/bench/heldout")
OUT = os.path.expanduser("~/sat-opt/bench/heldout_screening.csv")
TIMEOUT, PARALLEL, BUDGET_S, MAX_BYTES = 150, 3, 3600, 100_000_000

files = sorted(glob.glob(DIR + "/**/*.cnf", recursive=True), key=os.path.getsize)
files = [f for f in files if os.path.getsize(f) <= MAX_BYTES]
done = set()
if os.path.exists(OUT):
    done = {r["filename"] for r in csv.DictReader(open(OUT))}
files = [f for f in files if os.path.basename(f) not in done]
start = time.time()

def run(f):
    if time.time() - start > BUDGET_S:
        return None
    t = time.perf_counter()
    try:
        p = subprocess.run([BIN, "-rnd-seed=1", f], capture_output=True,
                           text=True, timeout=TIMEOUT)
        res = "SAT" if p.returncode == 10 else "UNSAT" if p.returncode == 20 else "ERROR"
    except subprocess.TimeoutExpired:
        res = "TIMEOUT"
    return (os.path.basename(f), os.path.getsize(f), res,
            round(time.perf_counter() - t, 3))

new = not os.path.exists(OUT)
with open(OUT, "a", newline="") as fh:
    w = csv.writer(fh)
    if new:
        w.writerow(["filename", "size_bytes", "result", "time_seconds"])
    with ThreadPoolExecutor(PARALLEL) as ex:
        for row in ex.map(run, files):
            if row:
                w.writerow(row)
                fh.flush()
                print(row, flush=True)