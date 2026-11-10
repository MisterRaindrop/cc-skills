#!/usr/bin/env python3
"""Run one query in a fresh session and sample every QD/QE of that session.

  sampler.py --tag A1 --sql q23.sql [--opts "-c vector.enable_vec_pipeline=on"]
             [--port 5432] [--db postgres] [--out ./runs] [--interval 1]
             [--timeout 1800] [--max-out-mb 200] [--pss] [--allow-write]

Every tick, per process (pid + start time, so a reused pid is a new process):
  rss    RssAnon kB                    hwm   VmHWM kB (kernel peak, catches spikes
  cpu    utime+stime since it started        between ticks; includes shared pages)
  wb/rb  write_bytes/read_bytes since it started (block IO, i.e. spill / scans)
  thr    threads, run = threads in state R, wchan of the main thread
  pss    Pss_Anon from smaps_rollup (only with --pss: slower on big processes)
Host per tick: MemAvailable, PSI (/proc/pressure) cpu/memory/io some avg10.

QEs of a fresh session start after the run starts, so "since it started" is this
run.  A process that existed before the run (should not happen) is baselined at
first sight and counted in reused_qe.

Writes <out>/<tag>/: out.txt err.txt series.jsonl summary.txt result.json
Safety: refuses SQL that writes (DML/DDL/psql \\ commands) unless --allow-write;
adds statement_timeout; cancels the query if out.txt grows beyond --max-out-mb.
Only samples this host (run one sampler per host on a multi-host cluster).
"""
import argparse, collections, hashlib, json, os, re, signal, statistics, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qe_pids  # noqa: E402

WRITE_RX = re.compile(r"\b(insert|update|delete|merge|truncate|drop|alter|create|grant|revoke|"
                      r"vacuum|copy|reindex|cluster|refresh|lock|call|do|comment|security)\b", re.I)

ap = argparse.ArgumentParser()
ap.add_argument("--tag", required=True)
ap.add_argument("--sql", required=True)
ap.add_argument("--opts", default="")
ap.add_argument("--port", default=os.environ.get("PGPORT", "5432"))
ap.add_argument("--db", default=os.environ.get("PGDATABASE", "postgres"))
ap.add_argument("--out", default="./runs")
ap.add_argument("--interval", type=float, default=1.0)
ap.add_argument("--timeout", type=int, default=1800, help="statement_timeout in s, 0 = none")
ap.add_argument("--max-out-mb", type=int, default=200)
ap.add_argument("--pss", action="store_true")
ap.add_argument("--allow-write", action="store_true")
a = ap.parse_args()

sql = open(a.sql).read()
if not a.allow_write:
    bare = re.sub(r"--[^\n]*|/\*.*?\*/|'(?:[^']|'')*'", " ", sql, flags=re.S)
    bad = WRITE_RX.search(bare) or re.search(r"^\s*\\", bare, re.M)
    if bad:
        sys.exit(f"sampler: '{bad.group(0).strip()}' looks like a write or a psql command; "
                 "A/B reruns the file, so writes are refused.  Use --allow-write if intended.")

out = os.path.abspath(os.path.join(a.out, a.tag))
os.makedirs(out, exist_ok=True)
pms = qe_pids.postmasters(a.port, a.db)           # before the run: fail fast, wrong cluster
opts = a.opts + (f" -c statement_timeout={a.timeout}s" if a.timeout else "")
env = dict(os.environ, PGPORT=str(a.port), PGDATABASE=a.db, PGOPTIONS=opts.strip())
TICK = os.sysconf("SC_CLK_TCK")
BTIME = next(int(l.split()[1]) for l in open("/proc/stat") if l.startswith("btime"))

# The session id goes to its own file and \o closes (= flushes) it at once, so
# sampling starts before the first QE exists; the result stays clean in out.txt.
pre = f"\\o {out}/conid\nselect current_setting('gp_session_id');\n\\o\n"
for f in ("conid",):
    try:
        os.remove(f"{out}/{f}")
    except OSError:
        pass
t0_wall, t0 = time.time(), time.monotonic()
proc = subprocess.Popen(["psql", "-XAtq", "-v", "ON_ERROR_STOP=1", "-f", "-"], env=env,
                        stdin=subprocess.PIPE,
                        stdout=open(f"{out}/out.txt", "w"),
                        stderr=open(f"{out}/err.txt", "w"))
proc.stdin.write((pre + sql).encode())
proc.stdin.close()


def read(path, mode="r"):
    try:
        with open(path, mode) as f:
            return f.read()
    except OSError:
        return None


def meminfo_kb(field):
    for line in open("/proc/meminfo"):
        if line.startswith(field):
            return int(line.split()[1])
    return 0


def psi(res):
    t = read(f"/proc/pressure/{res}")
    m = re.search(r"some avg10=([\d.]+)", t or "")
    return float(m.group(1)) if m else None


def kb(text, field):
    m = re.search(rf"^{field}:\s+(\d+)", text or "", re.M)
    return int(m.group(1)) if m else 0


def io(text, field):
    m = re.search(rf"^{field}:\s+(\d+)", text or "", re.M)
    return int(m.group(1)) if m else 0


conid = None
base = {}            # (pid, start) -> baseline [cpu, wb, rb]; zeros for processes born in this run
label = {}           # (pid, start) -> (slice label, cmd)
prev = {}            # (pid, start) -> cpu at the previous tick
reused = set()
status = "OK"
series = open(f"{out}/series.jsonl", "w")
ticks = []           # in memory for the summary: (t, dt, {key: row})
last_t = 0.0


def stop(sig, _):
    proc.send_signal(signal.SIGINT)                  # psql cancels the running query


signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)

while proc.poll() is None:
    t = round(time.monotonic() - t0, 3)
    dt = max(t - last_t, 1e-3); last_t = t
    if conid is None:
        m = re.search(r"\d+", read(f"{out}/conid") or "")
        conid = int(m.group(0)) if m else None
    host = {"avail_kb": meminfo_kb("MemAvailable"), "psi_cpu": psi("cpu"),
            "psi_mem": psi("memory"), "psi_io": psi("io")}
    rows = {}
    if conid is not None:
        for pid, lab, cmd, _ in qe_pids.find(conid, pms):
            try:
                f = qe_pids.stat_fields(pid)
            except OSError:
                continue
            start = int(f[19])                           # field 22 = starttime
            key = (pid, start)
            cpu = (int(f[11]) + int(f[12])) / TICK      # utime + stime
            st, iot = read(f"/proc/{pid}/status"), read(f"/proc/{pid}/io")
            wb, rb = io(iot, "write_bytes"), io(iot, "read_bytes")
            if key not in base:
                born = BTIME + start / TICK
                if born < t0_wall - 1:
                    base[key] = [cpu, wb, rb]; reused.add(key)
                else:
                    base[key] = [0.0, 0, 0]
            # An idle QE's command line has no "cmdN sliceN"; remember the last
            # slice it ran (the summary relabels every tick with it, see below).
            if key not in label or lab != "idle":
                label[key] = (lab, cmd)
            b = base[key]
            nthr = nrun = 0
            try:
                for tid in os.listdir(f"/proc/{pid}/task"):
                    ts = read(f"/proc/{pid}/task/{tid}/stat")
                    if ts:
                        nthr += 1
                        nrun += ts[ts.rfind(")") + 2] == "R"
            except OSError:
                pass
            r = {"pid": pid, "slice": lab, "cmd": cmd,
                 "rss": kb(st, "RssAnon"), "hwm": kb(st, "VmHWM"),
                 "cpu": round(cpu - b[0], 2), "dcpu": round(cpu - prev.get(key, b[0]), 3),
                 "wb": wb - b[1], "rb": rb - b[2], "thr": nthr, "run": nrun,
                 "wchan": (read(f"/proc/{pid}/wchan") or "").strip() or "-"}
            if a.pss:
                r["pss"] = kb(read(f"/proc/{pid}/smaps_rollup"), "Pss_Anon")
            prev[key] = cpu
            rows[key] = r
    series.write(json.dumps({"t": t, "dt": round(dt, 3), **host, "qe": list(rows.values())}) + "\n")
    ticks.append((t, dt, host, rows))
    try:
        if os.path.getsize(f"{out}/out.txt") > a.max_out_mb * 2**20 and status == "OK":
            status = "OUT_TOO_BIG"; proc.send_signal(signal.SIGINT)
    except OSError:
        pass
    wake = time.monotonic() + a.interval             # short naps: elapsed stays accurate to ~20 ms
    while proc.poll() is None and time.monotonic() < wake:
        time.sleep(0.02)

series.close()
rc = proc.returncode
elapsed = time.monotonic() - t0
errs = [l.strip() for l in open(f"{out}/err.txt") if re.search(r"ERROR|FATAL|PANIC", l)]
if status == "OK" and (rc != 0 or errs):
    status = "FAIL"
if status == "OK" and conid is None:
    status = "NO_SAMPLES"

# Result fingerprint: raw (row order matters) and sorted (order-free); full sha256.
h_raw, lines = hashlib.sha256(), []
with open(f"{out}/out.txt", "rb") as f:
    for line in f:
        h_raw.update(line); lines.append(line)
h_sorted = hashlib.sha256(b"".join(sorted(lines))).hexdigest()
nrows = len(lines); del lines

# Per slice: sum over its QEs AT EACH TICK, then the max over time (not the sum
# of per-QE peaks, which happen at different times).
G = 2 ** 20
sl = collections.defaultdict(lambda: {"sum_t": [], "qe": set()})
peak_total, t_peak_total, min_avail = 0, 0.0, None
psi_max = {"psi_cpu": None, "psi_mem": None, "psi_io": None}
for t, dt, host, rows in ticks:
    min_avail = host["avail_kb"] if min_avail is None else min(min_avail, host["avail_kb"])
    for k in psi_max:
        if host[k] is not None:
            psi_max[k] = max(psi_max[k] or 0, host[k])
    tot = sum(r["rss"] for r in rows.values())
    if tot > peak_total:
        peak_total, t_peak_total = tot, t
    per = collections.defaultdict(lambda: [0, 0.0])
    for key, r in rows.items():
        # One label per process for the whole run (its last slice), so a QE that
        # was idle before or after its slice is not split across two rows.
        s = "{1}/{0}".format(*label[key])
        per[s][0] += r["rss"]; per[s][1] += r["dcpu"]
        sl[s]["qe"].add(key)
    for s, (rss, dcpu) in per.items():
        sl[s]["sum_t"].append((t, rss, dcpu / dt))

last = {}                                            # last row seen per process
for t, dt, host, rows in ticks:
    for key, r in rows.items():
        q = last.setdefault(key, dict(r, rss_max=0))
        q.update(r, rss_max=max(q["rss_max"], r["rss"]))

slices = []
for s, d in sl.items():
    qs = [last[k] for k in d["qe"]]
    t_pk, rss_pk, _ = max(d["sum_t"], key=lambda x: x[1])
    cores_pk = max(x[2] for x in d["sum_t"])
    busy = [x[0] for x in d["sum_t"] if cores_pk > 0 and x[2] >= 0.1 * cores_pk]
    med = lambda v: statistics.median(v) if v else 0
    rss_q, cpu_q = [q["rss_max"] for q in qs], [q["cpu"] for q in qs]
    slices.append({
        "slice": s, "n": len(qs), "peak_sum_kb": rss_pk, "t_peak": t_pk,
        "qe_max_kb": max(rss_q), "hwm_max_kb": max(q["hwm"] for q in qs),
        "rss_skew": round(max(rss_q) / med(rss_q), 2) if med(rss_q) else None,
        "cpu_s": round(sum(cpu_q), 1), "cpu_skew": round(max(cpu_q) / med(cpu_q), 2) if med(cpu_q) else None,
        "peak_cores": round(cores_pk, 1), "busy": [busy[0], busy[-1]] if busy else None,
        "wb": sum(q["wb"] for q in qs), "rb": sum(q["rb"] for q in qs),
        "max_threads": max(q["thr"] for q in qs)})
slices.sort(key=lambda x: -x["peak_sum_kb"])

res = {"tag": a.tag, "opts": a.opts, "status": status, "rc": rc, "elapsed_s": round(elapsed, 3),
       "conid": conid, "rows": nrows, "sha_raw": h_raw.hexdigest(), "sha_sorted": h_sorted,
       "errors": errs[:5], "peak_sum_rss_kb": peak_total, "t_peak": t_peak_total,
       "min_avail_kb": min_avail, **{k + "_max": v for k, v in psi_max.items()},
       "reused_qe": len(reused), "samples": len(ticks), "slices": slices}
json.dump(res, open(f"{out}/result.json", "w"), indent=1)

fmt = lambda v: "-" if v is None else v
with open(f"{out}/summary.txt", "w") as f:
    print(f"{a.tag} status={status} rc={rc} elapsed={elapsed:.3f}s rows={nrows} "
          f"sha_sorted={h_sorted[:16]} conid={conid} opts='{a.opts}'", file=f)
    print(f"  peak_sum_RssAnon={peak_total / G:.1f}GiB @t={t_peak_total}s  "
          f"min_MemAvailable={(min_avail or 0) / G:.1f}GiB  PSI10 max cpu/mem/io="
          f"{fmt(psi_max['psi_cpu'])}/{fmt(psi_max['psi_mem'])}/{fmt(psi_max['psi_io'])}  "
          f"samples={len(ticks)} reused_qe={len(reused)}", file=f)
    for e in errs[:3]:
        print("  ERR", e[:200], file=f)
    print(f"  {'cmd/slice':<14}{'n':>4}{'peak_sum':>10}{'@t':>7}{'QE_max':>8}{'HWM_max':>8}"
          f"{'skew':>6}{'cpu_s':>8}{'skew':>6}{'cores':>6}{'busy_s':>12}{'write':>8}{'read':>8}{'thr':>5}",
          file=f)
    for x in slices[:16]:
        busy = f"{x['busy'][0]:.0f}-{x['busy'][1]:.0f}" if x["busy"] else "-"
        print(f"  {x['slice']:<14}{x['n']:>4}{x['peak_sum_kb'] / G:>9.1f}G{x['t_peak']:>7.0f}"
              f"{x['qe_max_kb'] / G:>7.2f}G{x['hwm_max_kb'] / G:>7.2f}G{fmt(x['rss_skew']):>6}"
              f"{x['cpu_s']:>8.0f}{fmt(x['cpu_skew']):>6}{x['peak_cores']:>6}{busy:>12}"
              f"{x['wb'] / 2**30:>7.1f}G{x['rb'] / 2**30:>7.1f}G{x['max_threads']:>5}", file=f)
    print("  (GiB; peak_sum = max over time of the slice's per-tick sum; skew = max/median "
          "over QEs; busy = ticks with >=10% of the slice's peak cores)", file=f)
print(open(f"{out}/summary.txt").read())
sys.exit(0 if status == "OK" else 1)
