#!/usr/bin/env python3
"""qmon.py <outfile.jsonl> <postmaster_port> [interval_s=1] -- per-QE sampler for ONE cluster on this host (read-only /proc).
Finds postmasters of the cluster by port (coordinator + segments listening on this host, discovered from
`postgres -D ... -p PORT` or postmaster.pid), samples their child backends whose title carries 'con<N>'.
Each line: {"t": epoch, "p": [[pid, con, seg, cmd, slice, rss_anon_kb, cpu_ticks, read_bytes, write_bytes, threads,
start_epoch], ...]}  (start_epoch = process fork time, ~10ms precision; lets finalize tie a session to the query start)
(slice = -1 when the title has none, e.g. the QD / an idle QE). Stops when <outfile>.stop exists.
Ports file: <outfile>.ports lists all postmaster ports of the cluster on this host (one per line), written by the caller."""
import os, re, sys, time, json

out = sys.argv[1]; iv = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
open(out + ".pid", "w").write(str(os.getpid()))
ports = set(l.strip() for l in open(out + ".ports") if l.strip())
# QE title: "... con19 seg0 cmd7 slice2 ..."; QD title has no seg: "... con508 cmd1 SELECT" -> seg = -1
TITLE = re.compile(r"\bcon(\d+)(?:\s+seg(-?\d+))?(?:\s+cmd(\d+))?(?:\s+slice(\d+))?")
HZ = os.sysconf("SC_CLK_TCK")
# Process start in wall-clock time = now - (uptime - starttime). Do NOT use /proc/stat btime: it is whole seconds and
# drifts from the wall clock under NTP (measured -0.74s on a host up 108 days), which shifts every session start.
BOOT_WALL = 0.0


def read(p):
    try:
        with open(p) as f:
            return f.read()
    except Exception:
        return None


def postmasters():
    pms = set()
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        cmd = read(f"/proc/{d}/cmdline")
        if not cmd or "postgres" not in cmd.split("\0")[0]:
            continue
        a = cmd.split("\0")
        if "-D" not in a:
            continue
        port = None
        if "-p" in a:
            port = a[a.index("-p") + 1]
        else:
            pf = read(os.path.join(a[a.index("-D") + 1], "postmaster.pid"))
            if pf and len(pf.splitlines()) > 3:
                port = pf.splitlines()[3].strip()
        if port in ports:
            pms.add(int(d))
    return pms


def sample(pms):
    rows = []
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        st = read(f"/proc/{d}/stat")
        if not st:
            continue
        rest = st[st.rindex(")") + 2:].split()
        if int(rest[1]) not in pms:
            continue
        cmd = read(f"/proc/{d}/cmdline") or ""
        m = TITLE.search(cmd)
        if not m:
            continue
        status = read(f"/proc/{d}/status") or ""
        rss = re.search(r"RssAnon:\s+(\d+)", status); thr = re.search(r"Threads:\s+(\d+)", status)
        io = read(f"/proc/{d}/io") or ""
        rb = re.search(r"read_bytes:\s+(\d+)", io); wb = re.search(r"^write_bytes:\s+(\d+)", io, re.M)
        rows.append([int(d), int(m.group(1)), int(m.group(2) or -1), int(m.group(3) or -1), int(m.group(4) or -1),
                     int(rss.group(1)) if rss else 0, int(rest[11]) + int(rest[12]),
                     int(rb.group(1)) if rb else 0, int(wb.group(1)) if wb else 0, int(thr.group(1)) if thr else 0,
                     round(BOOT_WALL + int(rest[19]) / HZ, 3)])   # process start (epoch): when the session/QE was forked
    return rows


pms = postmasters(); last_pm = time.time()
with open(out, "a") as f:
    while not os.path.exists(out + ".stop"):
        t0 = time.time()
        BOOT_WALL = t0 - float(open("/proc/uptime").read().split()[0])
        # proteus restarts the cluster (gpstop -air) when it applies guc.conf: re-discover as soon as a cached
        # postmaster is gone, otherwise up to 30s of samples are lost.
        if t0 - last_pm > 30 or not pms or not all(os.path.exists(f"/proc/{p}") for p in pms):
            pms = postmasters(); last_pm = t0
        f.write(json.dumps({"t": round(t0, 2), "p": sample(pms)}, separators=(",", ":")) + "\n"); f.flush()
        time.sleep(max(0.0, iv - (time.time() - t0)))
