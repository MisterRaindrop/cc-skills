#!/usr/bin/env python3
"""upload_metrics.py <sysmon.tsv> <report_id> <start_epoch> <end_epoch> <server_label>
Fills the report DB metric tables (cpuusage, memoryusage, net*, diskiousage) for one report from sysmon, in the
units of proteus' Prometheus queries: cpu = busy fraction, mem = used %, net MB/s (sum over NICs), disk = max util %.
30s buckets like Prometheus step=30s. Replaces rows of that report_id only."""
import os, sys, psycopg2


def site_db():
    """libpq conninfo of the report DB from <workdir>/bin/site.env (TPCBENCH_REPORT_DB), copied there by nightly.py"""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site.env")
    for l in open(p):
        if l.startswith("TPCBENCH_REPORT_DB="):
            return l.split("=", 1)[1].strip()
    sys.exit("TPCBENCH_REPORT_DB missing in " + p)
tsv, rid, s, e, server = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
rows = [l.rstrip("\n").split("\t") for l in open(tsv)]
hdr = next(r for r in rows if r and r[0] == "epoch"); hi = {k: i for i, k in enumerate(hdr)}
pts = {}
for r in rows:
    if not r or r[0] == "epoch" or len(r) != len(hdr):
        continue
    t = int(r[0])
    if not (s <= t <= e):
        continue
    g = lambda k: float(r[hi[k]])
    cpu = (100 - g("cpu_idle")) / 100
    mem = (g("mem_total_mb") - g("mem_avail_mb")) / g("mem_total_mb") * 100
    rx = sum(g(k) for k in hdr if k.endswith("_rxMBs")); tx = sum(g(k) for k in hdr if k.endswith("_txMBs"))
    dk = max([g(k) for k in hdr if k.endswith("_util")] or [0])
    pts.setdefault(t - (t - s) % 30, []).append((cpu, mem, rx, tx, dk))
c = psycopg2.connect(site_db() + " connect_timeout=15"); cur = c.cursor()
for t in ["cpuusage", "memoryusage", "netreceivethroughput", "netsendthroughput", "diskiousage"]:
    cur.execute(f"delete from {t} where report_id=%s and server=%s", (rid, server))   # one call per host (multi-host)
for k in sorted(pts):
    v = [sum(x[i] for x in pts[k]) / len(pts[k]) for i in range(5)]
    cur.execute("insert into cpuusage(report_id,server,timestamp,usage_rate) values(%s,%s,%s,%s)", (rid, server, k, v[0]))
    cur.execute("insert into memoryusage(report_id,server,timestamp,usage_rate) values(%s,%s,%s,%s)", (rid, server, k, v[1]))
    cur.execute("insert into netreceivethroughput(server,report_id,timestamp,throughput_mb) values(%s,%s,%s,%s)", (server, rid, k, v[2]))
    cur.execute("insert into netsendthroughput(server,report_id,timestamp,throughput_mb) values(%s,%s,%s,%s)", (server, rid, k, v[3]))
    cur.execute("insert into diskiousage(report_id,server,timestamp,usage_rate) values(%s,%s,%s,%s)", (rid, server, k, round(v[4], 2)))
c.commit(); print(f"report {rid}: {len(pts)} metric buckets")
