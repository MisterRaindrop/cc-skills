#!/usr/bin/env python3
"""sysmon.py <outfile.tsv> [interval_s=5] -- host-level sampler (read-only /proc). Stops when <outfile>.stop exists.
Columns: epoch, CPU % (user, sys, iowait, irq, idle), procs_running, load1, memory MB (total, avail, cached,
dirty, anon, shmem, swap used), majflt/s, ctxt/s, per nvme disk (rMB/s, wMB/s, r/w iops, util %, await ms),
per NIC (rx/tx MB/s)."""
import os, sys, time
out = sys.argv[1]; iv = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
open(out + ".pid", "w").write(str(os.getpid()))


def cpu():
    for l in open("/proc/stat"):
        if l.startswith("cpu "):
            return [int(x) for x in l.split()[1:9]]


def stat_kv():
    d = {}
    for l in open("/proc/stat"):
        f = l.split()
        if f[0] in ("ctxt", "procs_running"):
            d[f[0]] = int(f[1])
    return d


def mem():
    d = {}
    for l in open("/proc/meminfo"):
        k, v = l.split(":"); d[k] = int(v.split()[0]) // 1024
    return d


def vm():
    d = {}
    for l in open("/proc/vmstat"):
        k, v = l.split(); d[k] = int(v)
    return d


def disks():
    d = {}
    for l in open("/proc/diskstats"):
        f = l.split()
        n = f[2]
        if (n.startswith("nvme") and n.endswith("n1")) or (n[:2] in ("sd", "vd") and n[-1].isalpha()):
            d[n] = (int(f[3]), int(f[5]), int(f[6]), int(f[7]), int(f[9]), int(f[10]), int(f[12]))
    return d


def nets():
    d = {}
    for l in open("/proc/net/dev").readlines()[2:]:
        n, rest = l.split(":", 1); f = rest.split(); n = n.strip()
        if n != "lo" and not n.startswith(("veth", "docker", "br-", "virbr", "cni", "flannel")):
            d[n] = (int(f[0]), int(f[8]))
    return d


p = (time.time(), cpu(), stat_kv(), vm(), disks(), nets())
dnames = sorted(p[4]); nnames = None
f = open(out, "a")
while not os.path.exists(out + ".stop"):
    time.sleep(iv)
    c = (time.time(), cpu(), stat_kv(), vm(), disks(), nets())
    dt = c[0] - p[0]
    dc = [a - b for a, b in zip(c[1], p[1])]; tot = sum(dc) or 1
    pc = lambda *i: 100.0 * sum(dc[j] for j in i) / tot
    m = mem()
    if nnames is None:
        nnames = sorted(n for n in c[5] if (c[5][n][0] - p[5].get(n, (0, 0))[0]) > 0 or n.startswith(("bond", "ens", "eth", "enp")))
        hdr = ["epoch", "cpu_user", "cpu_sys", "cpu_iowait", "cpu_irq", "cpu_idle", "procs_running", "load1",
               "mem_total_mb", "mem_avail_mb", "cached_mb", "dirty_mb", "anon_mb", "shmem_mb", "swap_used_mb", "majflt_s", "ctxt_s"]
        for dn in dnames:
            hdr += [dn + x for x in ("_rMBs", "_wMBs", "_riops", "_wiops", "_util", "_await_ms")]
        for nn in nnames:
            hdr += [nn + "_rxMBs", nn + "_txMBs"]
        f.write("\t".join(hdr) + "\n")
    row = ["%d" % c[0], "%.1f" % (pc(0) + pc(1)), "%.1f" % pc(2), "%.1f" % pc(4),
           "%.1f" % (pc(5) + pc(6)), "%.1f" % pc(3), str(c[2]["procs_running"]),
           open("/proc/loadavg").read().split()[0],
           str(m["MemTotal"]), str(m["MemAvailable"]), str(m["Cached"]), str(m["Dirty"]), str(m["AnonPages"]), str(m["Shmem"]),
           str(m["SwapTotal"] - m["SwapFree"]), "%.0f" % ((c[3]["pgmajfault"] - p[3]["pgmajfault"]) / dt),
           "%.0f" % ((c[2]["ctxt"] - p[2]["ctxt"]) / dt)]
    for dn in dnames:
        a, b = c[4].get(dn), p[4].get(dn)
        if not a or not b:
            row += ["0"] * 6; continue
        r, w = a[0] - b[0], a[3] - b[3]
        row += ["%.1f" % ((a[1] - b[1]) * 512 / 1e6 / dt), "%.1f" % ((a[4] - b[4]) * 512 / 1e6 / dt),
                "%.0f" % (r / dt), "%.0f" % (w / dt), "%.1f" % min(100.0, (a[6] - b[6]) / (10.0 * dt)),
                "%.2f" % (((a[2] - b[2]) + (a[5] - b[5])) / float(r + w) if r + w else 0.0)]
    for nn in nnames:
        a, b = c[5].get(nn, (0, 0)), p[5].get(nn, (0, 0))
        row += ["%.1f" % ((a[0] - b[0]) / 1e6 / dt), "%.1f" % ((a[1] - b[1]) / 1e6 / dt)]
    f.write("\t".join(row) + "\n"); f.flush()
    p = c
