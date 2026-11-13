#!/usr/bin/env python3
"""finalize.py <run_dir> <set h|ds> -- build <run_dir>/<set>/run.json + summary.txt from what the run left behind.
Works on partial runs (proteus killed, cluster crashed): every field is optional and missing parts are reported.

run.json: build (pipeline, umbrella sha, database/arrow commits, CI job status), cluster, host (hardware, other
postgres load before the run), libarrow layout, data (schema, rows, analyze time), config/GUCs, proteus status +
report_id, and per query: status, seconds, start/end, error, result rows + sha (raw, sorted), plan hash (shape,
costs stripped), resources from qmon (peak RssAnon sum over the query's QEs, per-slice peak/CPU s, read/write bytes,
threads) and sysmon (min MemAvailable, max CPU busy %)."""
import socket, glob, hashlib, json, os, re, sys, time
from collections import defaultdict

R, S = sys.argv[1], sys.argv[2]
O = f"{R}/{S}"; TS = f"tpc-{S}"


def jload(p, d=None):
    try:
        return json.load(open(p))
    except Exception:
        return d


def collector_cost(O, t0, t1):
    """CPU used by our own collectors during this test set (written by run.sh at stop): proof they do not disturb."""
    out = {}
    for l in text(f"{O}/collectors_cpu.txt").splitlines():
        f = l.split()
        if len(f) == 2:
            out[f[0] + "_cpu_s"] = float(f[1])
    if out and t1 and t0 and t1 > t0:
        out["avg_cores"] = round(sum(out.values()) / (t1 - t0), 3)
    return out


def text(p, d=""):
    try:
        return open(p, errors="replace").read()
    except Exception:
        return d


def release_commits(y):
    out = {}
    for m in re.finditer(r"- path: (\S+)\s+commit: (\w+)", y):
        if m.group(1) in ("database", "contrib/apache-arrow/arrow") or "pax" in m.group(1):
            out[m.group(1)] = m.group(2)
    return out


def result_digest(p):
    """rows of every result table in a psql -e output (header/separator/footers dropped)."""
    rows, errs, in_tab = [], [], False
    for l in text(p).splitlines():
        if re.match(r"^-+(\+-+)*$", l.strip()):
            in_tab = True; continue
        if in_tab and re.match(r"^\(\d+ rows?\)$", l.strip()):
            in_tab = False; continue
        if in_tab:
            rows.append(l.rstrip())
        if re.match(r"^(psql:.*)?(ERROR|FATAL|PANIC):", l) or l.startswith("psql:") and "ERROR" in l:
            errs.append(l.strip()[:300])
    h = lambda xs: hashlib.sha256("\n".join(xs).encode()).hexdigest()[:16]
    return dict(rows=len(rows), sha_raw=h(rows) if rows else None, sha_sorted=h(sorted(rows)) if rows else None,
                error=errs[0] if errs else None)


def plan_hash(p):
    t = text(p)
    if not t or "QUERY PLAN" not in t:
        return None, None
    lines = [l for l in t.splitlines() if l.strip() and not l.startswith(("SET", "(")) and "QUERY PLAN" not in l and not set(l.strip()) <= {"-"}]
    shape = [re.sub(r"\(cost=[^)]*\)|\(actual[^)]*\)|\d+(\.\d+)?", "#", l).rstrip() for l in lines]
    return hashlib.sha256("\n".join(shape).encode()).hexdigest()[:16], len(lines)


def concurrency_block(streams, sysm, t0, t1):
    """throughput view of a multi-stream run: per-stream totals, whole-window time, host extremes over all hosts"""
    w = [x for x in sysm if t0 and t1 and t0 <= x[0] <= t1 + 5]
    nq = sum(s["queries"] for s in streams); ok = sum(s["ok"] for s in streams)
    el = (max(s["end"] for s in streams) - min(s["start"] for s in streams)) if streams else None
    return dict(streams=len(streams), per_stream=sorted(streams, key=lambda s: s["stream"]), executions=nq, ok=ok,
                elapsed_s=el, queries_per_hour=round(ok * 3600 / el, 1) if el else None,
                host_min_avail_gb=round(min(x[1] for x in w) / 1024, 1) if w else None,
                host_max_cpu_pct=round(max(x[2] for x in w), 1) if w else None)


def main():
    win = text(f"{O}/window.txt").split()
    t0, t1, prc = (int(win[0]), int(win[1]), int(win[2])) if len(win) == 3 else (None, None, None)
    res = f"{O}/proteus_results/logs"
    build = jload(f"{R}/build.json", {})
    rel = text(f"{R}/release-info.yaml")
    host = jload(f"{R}/host_before.json", {})
    cl = jload(f"{R}/cluster.json", {})
    cname = cl.get("name", "")
    data = jload(f"{O}/data.json", {})
    our_port = f"port{cl.get('port')}"
    busy = host.get("postgres_cores_busy", {})
    # layout of the postmasters that actually ran the queries (proteus restarts the cluster after preflight)
    layout = (text(f"{O}/layout.txt") or text(f"{R}/layout.txt")).strip().splitlines()
    # queries from rollout_sql.log: id|role.qq|tuples|HH:MM:SS|start|end   (tuples -1 = failed)
    def parse_rollout(path):
        rows = []
        for l in text(path).splitlines():
            f = l.split("|")
            if len(f) < 6 or not f[0].isdigit():
                continue
            hh, mm, ss = (int(x) for x in f[3].split(":"))
            rows.append(dict(file_id=int(f[0]), name=f[1], ok=f[2] != "-1", seconds=hh * 3600 + mm * 60 + ss,
                             start=int(f[4]), end=int(f[5])))
        return rows

    def merge(rows, key):
        """several executions of one query (rounds: SINGLE_USER_ITERATIONS, or one per stream) -> one entry: seconds =
        median of the successful ones, raw times in "rounds", start/end of the execution with the median time (its
        sessions are the ones attributed below)"""
        by = {}
        for r in rows:
            by.setdefault(r[key], []).append(r)
        out = []
        for k, rs in by.items():
            okr = [r for r in rs if r["ok"]]
            pick = sorted(okr or rs, key=lambda r: r["seconds"])[(len(okr or rs) - 1) // 2]
            out.append(dict(file_id=rs[0]["file_id"], name=rs[0]["name"], status="OK" if len(okr) == len(rs) else "FAILED",
                            seconds=pick["seconds"], start=pick["start"], end=pick["end"],
                            rounds=[r["seconds"] if r["ok"] else None for r in rs],
                            spread=(max(r["seconds"] for r in okr) - min(r["seconds"] for r in okr)) if okr else None,
                            failed_rounds=len(rs) - len(okr)))
        return out

    multi = sorted(glob.glob(f"{res}/{TS}/rollout_testing_*.log"))
    streams = None
    if multi:
        # concurrent streams (proteus 07_multi_user): per-query resources can not be told apart -> no attribution;
        # each query = median over the streams, plus per-stream totals and the throughput of the whole window
        allrows, streams = [], []
        for mf in multi:
            sid = int(re.search(r"rollout_testing_(\d+)\.log", mf).group(1))
            rs = parse_rollout(mf)
            for r in rs:
                r["stream"] = sid
            allrows += rs
            if rs:
                streams.append(dict(stream=sid, queries=len(rs), ok=sum(r["ok"] for r in rs),
                                    start=min(r["start"] for r in rs), end=max(r["end"] for r in rs),
                                    elapsed_s=max(r["end"] for r in rs) - min(r["start"] for r in rs)))
        for r in allrows:
            r["qkey"] = r["name"].rsplit(".", 1)[-1] if r["name"] else str(r["file_id"])
        queries = merge(allrows, "qkey")
        for q in queries:
            q["start"] = q["end"] = None                  # skip per-query attribution
            q["name"] = f"q.{int(q['name'].rsplit('.', 1)[-1]):02d}"   # "<stream>.<query>" -> one name for all streams
    else:
        queries = merge(parse_rollout(f"{res}/{TS}/rollout_sql.log"), "file_id")
    started = {int(m.group(1)) for m in re.finditer(r"05_sql/(\d+)\.[^ ]+\.sql", text(f"{res}/{TS}/run.log"))}
    done = {q["file_id"] for q in queries}
    for fid in sorted(started - done) if not multi else []:   # started but never logged = killed/crashed mid-query
        queries.append(dict(file_id=fid, name=None, status="NOT_FINISHED", seconds=None, start=None, end=None))
    for q in queries:
        out = glob.glob(f"{res}/{TS}/{q['file_id']}.*.single.result.out")
        if multi:   # failed stream executions: take the error of the first failed one
            out = sorted(glob.glob(f"{res}/{TS}/*.{q['file_id']}.*.multi.result.out"))
            out = [o for o in out if "ERROR" in text(o)][:1] or out[:1]
        q.update(result_digest(out[0]) if out else dict(rows=None, sha_raw=None, sha_sorted=None, error=None))
        pl = glob.glob(f"{O}/plans/{q['file_id']}.*.plan")
        q["plan_shape_hash"], q["plan_lines"] = plan_hash(pl[0]) if pl else (None, None)
    # qmon of every host: qmon.jsonl (coordinator) + qmon.<host>.jsonl (other hosts of a multi-host cluster).
    # Merged into 1s buckets; pids get a per-host offset (pids repeat across hosts); each row carries its own
    # sample time (index 11) so CPU rates use the per-process interval even when a host skipped a bucket.
    qfiles = [f"{R}/qmon.jsonl"] + sorted(glob.glob(f"{R}/qmon.*.jsonl"))
    buckets = {}
    for hi_, qf in enumerate(f for f in qfiles if os.path.exists(f)):
        for l in open(qf):
            try:
                smp = json.loads(l)
            except Exception:
                continue
            b = int(smp["t"] + 0.5)
            ent = buckets.setdefault(b, {"t": float(b), "p": [], "hosts": set()})
            if hi_ in ent["hosts"]:
                continue                                    # one sample per host per bucket
            ent["hosts"].add(hi_)
            for p_ in smp["p"]:
                row = list(p_) + [None] * (11 - len(p_))
                row[0] = row[0] + hi_ * 10_000_000
                ent["p"].append(row[:11] + [smp["t"]])
    samples = [buckets[b] for b in sorted(buckets)]
    hz = os.sysconf("SC_CLK_TCK")
    # sysmon of every host: per-query host memory/CPU extremes over all hosts; per-host network for the run
    sysm, hosts_net = [], {}
    for sf in [f"{R}/sysmon.tsv"] + sorted(glob.glob(f"{R}/sysmon.*.tsv")):
        if not os.path.exists(sf):
            continue
        hname = os.path.basename(sf)[len("sysmon."):-len(".tsv")] or socket.gethostname().split(".")[0]
        rows = [l.rstrip("\n").split("\t") for l in open(sf)]
        hdr = [r for r in rows if r and r[0] == "epoch"]
        if not hdr:
            continue
        hi = {k: i for i, k in enumerate(hdr[0])}
        rx = [i for k, i in hi.items() if k.endswith("_rxMBs")]; tx = [i for k, i in hi.items() if k.endswith("_txMBs")]
        nr = []
        for r in rows:
            if r and r[0] != "epoch" and len(r) == len(hdr[0]):
                t_ = int(r[0])
                sysm.append((t_, float(r[hi["mem_avail_mb"]]), 100 - float(r[hi["cpu_idle"]])))
                if t0 and t1 and t0 <= t_ <= t1:
                    nr.append((sum(float(r[i]) for i in rx), sum(float(r[i]) for i in tx)))
        if nr:
            hosts_net[hname] = dict(rx_avg_MBs=round(sum(x for x, _ in nr) / len(nr), 1), rx_peak_MBs=round(max(x for x, _ in nr), 1),
                                    tx_avg_MBs=round(sum(y for _, y in nr) / len(nr), 1), tx_peak_MBs=round(max(y for _, y in nr), 1))
    # Session -> query attribution.
    # Every query runs in its own psql session (con<N>). con numbers are not per-query sequential and are reused
    # after proteus restarts the cluster, so a session is one *appearance*: a con present in consecutive samples.
    # Its start = earliest fork time of its processes (qmon field 10, ~10ms precision; the QD is forked when psql
    # connects, i.e. right after proteus stamps the query start). proteus stamps start/end in whole seconds, so
    # matching on the start second (not the whole [start, end] window) keeps back-to-back queries apart.
    # Old qmon files without fork times fall back to the first sample time and the whole query window.
    pid_label, apps, cur = {}, [], {}
    for si, s in enumerate(samples):
        cons_now = defaultdict(list)
        for p in s["p"]:
            cons_now[p[1]].append(p)
            if p[4] >= 0:                      # sticky label: last slice the process ran (idle QEs drop it from the title)
                pid_label[p[0]] = f"cmd{p[3]}/slice{p[4]}"
            elif p[2] == -1:
                pid_label.setdefault(p[0], "QD")
        nxt = {}
        for c, ps in cons_now.items():
            a = cur.get(c)
            if a is None:
                a = dict(con=c, t=s["t"], start=None, samples=[]); apps.append(a)
            forks = [p[10] for p in ps if len(p) > 10 and p[10]]
            if forks:
                a["start"] = min(forks + ([a["start"]] if a["start"] else []))
            qe_forks = [p[10] for p in ps if len(p) > 10 and p[10] and p[2] >= 0]     # segment QEs (seg >= 0)
            if qe_forks:
                a["qe_start"] = min(qe_forks + ([a["qe_start"]] if a.get("qe_start") else []))
            a["samples"].append(si); nxt[c] = a
            a["last"] = max([p[11] for p in ps if len(p) > 11 and p[11]] or [s["t"]])   # real sample time, not bucket
        cur = nxt
    precise = any(a["start"] for a in apps)
    for a in apps:
        a["key"] = a["start"] if a["start"] else a["t"]
    apps.sort(key=lambda a: a["key"])
    qs = sorted([q for q in queries if q["start"] is not None], key=lambda q: (q["start"], q["file_id"]))

    END_SLACK = 5.0

    def fits(a, q):
        if precise:
            # proteus stamps start = floor(date) before launching psql -> session forks in [start, start+1) + connect;
            # a session still alive at a sample cannot belong to a query that had already ended (end is floored too)
            # (the session may outlive proteus' end stamp: on the 96-segment 3-host cluster the QD of a 60s / 125s
            # query was still sampled 2s after end -- dispatcher teardown -- so allow END_SLACK, not 1.3s)
            return q["start"] - 0.05 <= a["key"] < q["start"] + 1.3 and a["last"] < q["end"] + END_SLACK
        return q["start"] - 1 <= a["key"] <= q["end"] + 1

    j, assigned, skip = 0, {}, set()
    for i, q in enumerate(qs):
        if q["file_id"] in skip:
            continue
        while j < len(apps) and apps[j]["key"] < q["start"] - (0.05 if precise else 1):
            j += 1                              # sessions that belong to no query (e.g. proteus helper psql)
        if j >= len(apps) or not fits(apps[j], q):
            continue
        nq = qs[i + 1] if i + 1 < len(qs) else None
        if nq and fits(apps[j], nq) and not (j + 1 < len(apps) and fits(apps[j + 1], nq)):
            # two queries started in the same second and only one session was sampled: cannot tell whose it is
            q["resources"] = nq["resources"] = "ambiguous (two queries started in the same second, one session sampled)"
            skip.add(nq["file_id"]); j += 1
            continue
        assigned[q["file_id"]] = apps[j]; j += 1
    for q in queries:
        if q["start"] is None:
            continue
        a = assigned.get(q["file_id"])
        if a is None:
            q.setdefault("resources", "not sampled (query shorter than the 1s sampling interval)")
            continue
        con = a["con"]
        win_s = [samples[si] for si in a["samples"]]
        q0 = a["start"] or q["start"]
        peak, slices, pid_last = 0, defaultdict(lambda: dict(peak_kb=0, qes=set())), {}
        qe_peak, prev_cpu = defaultdict(int), {}          # per QE: peak RssAnon; last cpu ticks (for rates)
        tot_series, slice_rate = [], defaultdict(list)   # (offset, total rss kb); per slice (offset, cores)
        prev_t = None
        for s in win_s:
            tot = 0; per = defaultdict(int); rate = defaultdict(float)
            dt = (s["t"] - prev_t) if prev_t else None
            for p in s["p"]:
                pid, c, seg, cmd, sl, rss, cpu, rb, wb, thr = p[:10]
                if c != con:
                    continue
                tot += rss; key = pid_label.get(pid, "slice?")   # QE never sampled while running a slice (query too short for 1s sampling)
                per[key] += rss; slices[key]["qes"].add(pid)
                pid_last[pid] = (key, cpu, rb, wb, thr)
                qe_peak[pid] = max(qe_peak[pid], rss)
                tp = p[11] if len(p) > 11 and p[11] else s["t"]
                if pid in prev_cpu:
                    pc, pt = prev_cpu[pid]
                    if tp > pt:
                        rate[key] += max(0, cpu - pc) / hz / (tp - pt)
                elif dt:
                    rate[key] += cpu / hz / dt                 # first sight: CPU since fork, within ~one interval
                prev_cpu[pid] = (cpu, tp)
            peak = max(peak, tot)
            off = round(s["t"] - q0, 1)
            tot_series.append((off, tot))
            if dt:
                for k, v in rate.items():
                    slice_rate[k].append((off, v))
            for k, v in per.items():
                slices[k]["peak_kb"] = max(slices[k]["peak_kb"], v)
            prev_t = s["t"]
        cpu_by = defaultdict(float); rb_t = wb_t = thr_max = 0
        qe_cpu = {}
        for pid, (key, cpu, rb, wb, thr) in pid_last.items():
            cpu_by[key] += cpu / hz; rb_t += rb; wb_t += wb; thr_max = max(thr_max, thr)
            qe_cpu[pid] = cpu / hz
        q["con"] = con
        q["session_start_lag_s"] = round(a["start"] - q["start"], 2) if a["start"] else None
        # session start -> first QE forked ~= parse + plan (ORCA) + dispatch; a large value = planning-bound query
        q["plan_dispatch_s"] = round(a["qe_start"] - a["start"], 2) if a.get("qe_start") and a["start"] else None
        q["peak_rss_gb"] = round(peak / 2**20, 2)
        q["cpu_s"] = round(sum(cpu_by.values()), 1)
        q["read_gb"] = round(rb_t / 2**30, 2); q["write_gb"] = round(wb_t / 2**30, 2)
        q["threads_max"] = thr_max
        q["samples"] = len(win_s)
        # query-level CPU: peak cores over 1s samples
        allr = defaultdict(float)
        for k, ser in slice_rate.items():
            for off, v in ser:
                allr[off] += v
        q["cores_peak"] = round(max(allr.values()), 1) if allr else None
        # memory curve shape: when the peak happens (fraction of the session's sampled life) and whether it drops
        # and rises again (sawtooth = spill / batch release) -- hints only, see vec-perf-triage step 4
        if len(tot_series) >= 3 and peak:
            ip = max(range(len(tot_series)), key=lambda i: tot_series[i][1])
            drops = sum(1 for i in range(1, len(tot_series))
                        if tot_series[i][1] < 0.7 * tot_series[i - 1][1] and tot_series[i - 1][1] > 0.3 * peak)
            frac = ip / (len(tot_series) - 1)
            q["mem_shape"] = ("sawtooth" if drops >= 2 else "early_peak" if frac < 0.3 else
                              "late_peak" if frac > 0.8 else "mid_peak")
        sl_out = {}
        for k, v in sorted(slices.items(), key=lambda kv: -kv[1]["peak_kb"]):
            pids = list(v["qes"])
            mp = sorted(qe_peak[p] for p in pids); cp = sorted(qe_cpu.get(p, 0) for p in pids)
            med = lambda xs: xs[len(xs) // 2] if xs else 0
            ser = slice_rate.get(k, [])
            mx = max((r for _, r in ser), default=0)
            busy_offs = [off for off, r in ser if mx > 0 and r >= 0.1 * mx]
            sl_out[k] = dict(
                peak_gb=round(v["peak_kb"] / 2**20, 2), qes=len(pids), cpu_s=round(cpu_by[k], 1),
                qe_peak_gb_max=round(mp[-1] / 2**20, 2) if mp else 0,
                # skew = max / median over the slice's QEs (meaningful only with an absolute gap, see analyze)
                skew_mem=round(mp[-1] / med(mp), 2) if mp and med(mp) else None,
                skew_cpu=round(cp[-1] / med(cp), 2) if cp and med(cp) > 0.05 else None,
                cores_peak=round(mx, 1),
                busy=[busy_offs[0], busy_offs[-1]] if busy_offs else None, busy_s=len(busy_offs))
        q["slices"] = sl_out
        # slice on the critical path (approx.): the one busy for the longest time
        if sl_out:
            q["longest_busy_slice"] = max(sl_out, key=lambda k: (sl_out[k]["busy_s"], sl_out[k]["cpu_s"]))
        sw = [x for x in sysm if q["start"] - 5 <= x[0] <= q["end"] + 5]
        if sw:
            q["host_min_avail_gb"] = round(min(x[1] for x in sw) / 1024, 1)
            q["host_max_cpu_pct"] = round(max(x[2] for x in sw), 1)
    queries.sort(key=lambda q: q["file_id"])
    ok = [q for q in queries if q["status"] == "OK"]
    # cores busy on the host before the run (our cluster is idle then): /proc/stat based since discover fix
    others_busy = host.get("host_busy_cores")
    for hb in glob.glob(f"{R}/host_before.*.json"):           # multi-host: the busiest host counts
        v = jload(hb, {}).get("host_busy_cores")
        if v is not None and (others_busy is None or v > others_busy):
            others_busy = v
    if others_busy is None:
        others_busy = round(sum(v for k, v in busy.items() if k != our_port), 1)
    run = dict(
        run_id=os.path.basename(R), test_set=TS, generated_at=time.strftime("%F %T"),
        window=dict(start=t0, end=t1, proteus_rc=prc), status=text(f"{O}/status").strip() or "UNKNOWN",
        report_id=text(f"{res}/report_id.log").strip() or None, config=text(f"{O}/config_name").strip(),
        build=dict(pipeline=build.get("pipeline"), umbrella_sha=build.get("sha"), title=build.get("title"),
                   created_at=build.get("created_at"), commits=release_commits(rel),
                   gp_version=text(f"{R}/version.txt").strip(), ci_failed_jobs=sorted(
                       k for k, v in build.get("ci_jobs", {}).items() if v == "failed")),
        cluster=cl, data=data,
        host=dict({k: host.get(k) for k in ("hostname", "ip", "arch", "cores", "cpu_model", "mem_gb", "os", "kernel", "thp", "loadavg")},
                  mem_avail_gb_before=host.get("mem_avail_gb"), other_postgres_cores_busy=others_busy),
        layout=dict(summary=layout[-1] if layout else None, bad=[l for l in layout if l.endswith("BAD")]),
        proteus=dict(rev=text(f"{R}/../../../../proteus/.tpcbench_rev").strip(),
                     patches=text(f"{R}/../../../../proteus/.tpcbench_patches").split()),
        totals=dict(queries=len(queries), ok=len(ok), failed=len(queries) - len(ok),
                    seconds_ok=sum(q["seconds"] or 0 for q in ok)),
        collectors=collector_cost(O, t0, t1),
        hosts_net=hosts_net,
        queries=queries,
        rounds=max((len(q.get("rounds") or [1]) for q in queries), default=1) if not multi else 1,
        concurrency=concurrency_block(streams, sysm, t0, t1) if multi else None,
        flags=[f for f in [
            "other_load" if others_busy > 0.1 * (host.get("cores") or 1) else None,
            "layout_bad" if any(l.endswith("BAD") for l in layout) else None,
            "crashed" if os.path.exists(f"{O}/crash_evidence.txt") else None,
            "proteus_failed" if (prc or 0) != 0 else None] if f],
    )
    json.dump(run, open(f"{O}/run.json", "w"), indent=1, ensure_ascii=False)
    with open(f"{O}/summary.txt", "w") as f:
        b = run["build"]
        f.write(f"{TS} run {run['run_id']}  status={run['status']}  report_id={run['report_id']}  flags={','.join(run['flags']) or '-'}\n")
        f.write(f"build {b['pipeline']} umbrella {str(b['umbrella_sha'])[:10]}  {b['gp_version']}\n")
        f.write(f"commits {b['commits']}\n")
        f.write(f"cluster {cname} {len(cl.get('hosts', []))} host(s) x {cl.get('segs_per_host')} segs  data {data.get('schema')} sf{data.get('scale')} {data.get('distribution', '?')}\n")
        f.write(f"host {host.get('hostname')} {host.get('cores')}c {host.get('mem_gb')}GB  other postgres busy before run: {others_busy} cores  layout: {run['layout']['summary']}\n")
        f.write(f"totals: {run['totals']['ok']}/{run['totals']['queries']} ok, {run['totals']['seconds_ok']}s (ok queries)\n\n")
        f.write(f"{'query':<22}{'status':<13}{'sec':>6}{'peakGB':>8}{'cpu_s':>8}{'minAvGB':>9}  rows  sha_sorted        plan              top slice\n")
        for q in queries:
            top = next(iter(q.get("slices", {}).items()), (None, None))
            f.write(f"{(q['name'] or str(q['file_id'])):<22}{q['status']:<13}{str(q['seconds']):>6}{str(q.get('peak_rss_gb', '-')):>8}"
                    f"{str(q.get('cpu_s', '-')):>8}{str(q.get('host_min_avail_gb', '-')):>9}  {str(q['rows']):<5} {str(q['sha_sorted']):<17} "
                    f"{str(q['plan_shape_hash']):<17} {top[0] or ''} {top[1]['peak_gb'] if top[1] else ''}"
                    f"{'  ERR: ' + q['error'] if q['error'] else ''}\n")
    print(open(f"{O}/summary.txt").read())


if __name__ == "__main__":
    main()
