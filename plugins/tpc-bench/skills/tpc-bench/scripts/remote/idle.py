#!/usr/bin/env python3
"""idle.py [seconds=30] -- is this host idle? (read-only /proc; run as root via `ssh host python3 - < idle.py`)
Prints one JSON line: host, cores, busy_cores (whole host, from /proc/stat over the window -- includes short-lived
query processes), iowait_cores, top consumers (postmaster port or command, from processes alive at both ends),
foreign data tools (gpfdist / dbgen / dsdgen not belonging to a tpc-bench cluster), mem_avail_gb, loadavg."""
import json, os, socket, sys, time

WIN = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0


def cpu():
    for l in open("/proc/stat"):
        if l.startswith("cpu "):
            return [int(x) for x in l.split()[1:9]]


def procs():
    d = {}
    for p in os.listdir("/proc"):
        if not p.isdigit():
            continue
        try:
            st = open(f"/proc/{p}/stat").read(); r = st[st.rindex(")") + 2:].split()
            d[int(p)] = (int(r[1]), int(r[11]) + int(r[12]), st[st.index("(") + 1:st.rindex(")")])
        except Exception:
            pass
    return d


def cmdline(pid):
    try:
        return open(f"/proc/{pid}/cmdline").read().split("\0")
    except Exception:
        return []


def postmaster_port(pid, tree):
    for _ in range(4):
        a = cmdline(pid)
        if a and a[0].endswith("postgres") and "-D" in a:
            if "-p" in a:
                return a[a.index("-p") + 1]
            return "pm:" + a[a.index("-D") + 1].rstrip("/").split("/")[-2]
        pid = tree.get(pid, (0,))[0]
        if not pid:
            return None
    return None


c0, p0 = cpu(), procs()
time.sleep(WIN)
c1, p1 = cpu(), procs()
hz, n = os.sysconf("SC_CLK_TCK"), os.cpu_count() or 1
tot = sum(c1) - sum(c0)
busy = (1 - (c1[3] + c1[4] - c0[3] - c0[4]) / tot) * n if tot else None
iow = (c1[4] - c0[4]) / tot * n if tot else None
by = {}
for pid, (pp, c, comm) in p1.items():
    if pid in p0:
        d = (c - p0[pid][1]) / hz / WIN
        if d > 0.05:
            k = postmaster_port(pid, p1) if comm.startswith(("postgres", "arrow")) else None
            k = f"port{k}" if k and not str(k).startswith("pm:") else (k or comm)
            by[k] = by.get(k, 0) + d
tools = []
for pid, (pp, c, comm) in p1.items():
    if comm in ("gpfdist", "dbgen", "dsdgen"):
        a = " ".join(cmdline(pid))
        if "tpcbench_" not in a:
            tools.append(f"{pid} {comm} {a[:120]}")
mem = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo")}
print(json.dumps(dict(
    host=socket.gethostname().split(".")[0], cores=n, window_s=WIN,
    busy_cores=round(busy, 1) if busy is not None else None, iowait_cores=round(iow, 1) if iow is not None else None,
    top=sorted(((k, round(v, 1)) for k, v in by.items()), key=lambda kv: -kv[1])[:6],
    foreign_tools=tools[:10], mem_avail_gb=mem.get("MemAvailable", 0) // 2**20,
    loadavg=open("/proc/loadavg").read().split()[:3]), ensure_ascii=False))
