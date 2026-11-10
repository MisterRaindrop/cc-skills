#!/usr/bin/env python3
"""Per-slice time curves from sampler.py's series.jsonl.

  plot.py <run_dir> [--top 8]

Always writes <run_dir>/curves.tsv (t, slice, rss_GiB, cpu_cores, threads_running,
host MemAvailable, PSI) so any tool can plot it; also mem.png / cpu.png when
matplotlib is available.  Slices shown = top N by peak memory UNION top N by
peak CPU, so a CPU-heavy slice with little memory is not hidden.
"""
import collections, json, os, sys

run = sys.argv[1]
top = int(sys.argv[sys.argv.index("--top") + 1]) if "--top" in sys.argv else 8
mem, cpu, runq = (collections.defaultdict(dict) for _ in range(3))
host = {}
recs = [json.loads(l) for l in open(os.path.join(run, "series.jsonl"))]
final = {}                                # pid -> last slice it ran, same rule as sampler's summary
for rec in recs:
    for q in rec["qe"]:
        if q["slice"] != "idle" or q["pid"] not in final:
            final[q["pid"]] = (q["cmd"], q["slice"])
for rec in recs:
    t, dt = rec["t"], rec["dt"]                     # per-tick interval, not assumed constant
    host[t] = (rec["avail_kb"] / 2**20, rec.get("psi_mem"), rec.get("psi_cpu"))
    m, c, r = collections.Counter(), collections.Counter(), collections.Counter()
    for q in rec["qe"]:
        s = "{}/{}".format(*final[q["pid"]])
        m[s] += q["rss"]; c[s] += q["dcpu"]; r[s] += q["run"]
    for s in m:
        mem[s][t] = m[s] / 2**20
        cpu[s][t] = c[s] / dt
        runq[s][t] = r[s]

by_mem = sorted(mem, key=lambda s: -max(mem[s].values()))[:top]
by_cpu = sorted(cpu, key=lambda s: -max(cpu[s].values()))[:top]
show = list(dict.fromkeys(by_mem + by_cpu))
with open(os.path.join(run, "curves.tsv"), "w") as f:
    print("t\tslice\trss_GiB\tcpu_cores\tthreads_R\thost_avail_GiB\tpsi_mem10\tpsi_cpu10", file=f)
    for s in show:
        for t in sorted(mem[s]):
            av, pm, pc = host[t]
            print(f"{t}\t{s}\t{mem[s][t]:.2f}\t{cpu[s].get(t, 0):.2f}\t{runq[s].get(t, 0)}"
                  f"\t{av:.1f}\t{pm}\t{pc}", file=f)

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:
    print("matplotlib not available; wrote curves.tsv only")
    sys.exit(0)

for name, data, ylabel, keys in (("mem", mem, "RssAnon, GiB (sum over the slice's QEs)", by_mem),
                                 ("cpu", cpu, "CPU cores (sum over the slice's QEs)", by_cpu)):
    plt.figure(figsize=(10, 5))
    for s in keys:
        ts = sorted(data[s])
        plt.plot(ts, [data[s][t] for t in ts], label=s)
    plt.xlabel("seconds since start"); plt.ylabel(ylabel); plt.legend(fontsize=8); plt.grid(alpha=.3)
    plt.title(f"{os.path.basename(run.rstrip('/'))}: {name} by slice")
    plt.savefig(os.path.join(run, f"{name}.png"), dpi=110, bbox_inches="tight")
print("wrote mem.png cpu.png curves.tsv")
