#!/usr/bin/env python3
"""deep.py -- phase 2 data collection for ONE slow query (gpadmin, coordinator host, cluster.env sourced; see deep.sh).

  deep.py ab   <W> <cluster> <rid> <set> <file_id> <base_build> <cur_build> <out> [--rounds 3] [--slice cmd7/slice2]
  deep.py time <W> <cluster> <rid> <set> <file_id> <build> <out> [--rounds 3]      (used by bisect)

Runs OUTSIDE the timed benchmark (it restarts / switches the tpc-bench cluster -- never another cluster).
ab:
  1. verify: alternate builds A(base) / B(cur) in ABBAAB order, a warm-up run after every switch, each switch only
     with a clean libarrow layout (restart until layout bad=0, max 5); timing = vec-perf-triage sampler.py (ms,
     result sha, per-slice series). Verdict CONFIRMED when the median gap > 10% and > both builds' spread, else NOISE.
  2. profile (CONFIRMED only), each build: perf hot symbols over all QEs of the query (no call graph, -F 99),
     a dwarf call graph of one QE of the slice that changed most (folded stacks), EXPLAIN VERBOSE, EXPLAIN ANALYZE.
  3. leave the cluster on the current build. Writes <out>/deep_summary.json.
time: median of N runs on one build (after warm-up, clean layout) -> <out>/time_<build>.json

  deep.py triage <W> <cluster> <rid> <set> <file_id> <out> [--slice S] [--expect SEC]
                 [--mem-slice S --mem-start SEC --mem-secs SEC --mem-qes N]
triage (the 3 slowest queries of every run, user 2026-11-13; vec-perf-triage method, current build only, no switch):
  1. sampler.py run: elapsed ms, result sha, per-process/per-slice memory + CPU series (summary.txt, series.jsonl)
  2. profile run: perf hot symbols of all QEs on every host + dwarf call graph of one QE of --slice (the slice that
     was busy longest in the timed run)
  3. memattr (only when --mem-slice is given = the query used a lot of memory): another run, flame.sh memattr on one QE
     of that slice while its memory grows (window from the timed run's busy interval) -> MB per operator / function
  4. EXPLAIN (VERBOSE) and EXPLAIN (ANALYZE, VERBOSE): actual rows per node
  -> <out>/triage_summary.json
"""
import argparse, json, os, re, statistics, subprocess, sys, threading, time

TRIAGE = None   # set in main: <W>/triage (vec-perf-triage scripts, synced by the orchestrator)


def log(*a):
    print(f"[{time.strftime('%F %T')}] deep:", *a, flush=True)


def sh(cmd, check=False, timeout=None):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode:
        raise RuntimeError(f"{cmd}: rc={r.returncode} {r.stderr.strip()[-500:]}")
    return r


class Cluster:
    """one tpc-bench cluster; the old and the new build may live in different clusters after a catalog bump"""
    def __init__(self, w, name):
        self.w, self.name, self.c = w, name, f"{w}/clusters/{name}"
        self.port = str(json.load(open(f"{self.c}/cluster.json")).get("port"))

    def build(self):
        return open(f"{self.c}/build.cur").read().strip()

    def env(self, cmd):
        return f"bash -c 'source {self.c}/cluster.env >/dev/null 2>&1; export TERM=xterm; {cmd}'"

    def layout_bad(self):
        out = sh(self.env(f"{self.w}/bin/layout.sh")).stdout.strip().splitlines()
        m = re.search(r"bad=(\d+)", out[-1] if out else "")
        return int(m.group(1)) if m else -1, out[-1] if out else ""

    def use(self, build):
        """switch (restart) to build, then restart until the libarrow layout is clean (Kunpeng ~30% noise)."""
        sh(f"{self.w}/bin/cluster.sh {self.w} {self.name} start")          # no-op when already running
        if self.build() != str(build):
            log(f"switch cluster {self.name} -> build {build}")
            r = sh(f"{self.w}/bin/cluster.sh {self.w} {self.name} use {build}")
            if self.build() != str(build):
                raise RuntimeError(f"cannot switch to build {build} (catalog incompatible?): {r.stdout[-400:]}{r.stderr[-400:]}")
        for i in range(6):
            bad, summ = self.layout_bad()
            if bad == 0:
                return summ
            if i == 5:
                log(f"layout still bad after 5 restarts ({summ}); continuing, flagged")
                return summ + " (still bad)"
            log(f"layout {summ} -> restart")
            sh(f"{self.w}/bin/cluster.sh {self.w} {self.name} restart", check=True)


def prep_sql(w, cluster, rid, s, fid, out):
    """the archived query file of the run, psql variables replaced (proteus passes them with -v)."""
    qd = f"{w}/clusters/{cluster}/runs/{rid}/{s}/queries"
    f = [x for x in os.listdir(qd) if x.startswith(f"{fid}.")]
    if not f:
        sys.exit(f"query file {fid}.* not in {qd}")
    src = open(os.path.join(qd, f[0])).read()
    cfg = open(f"{w}/clusters/{cluster}/runs/{rid}/{s}/config_name").read().strip()
    pre = ""
    tc = f"{w}/proteus/configs/{cfg}/test.conf"
    if os.path.exists(tc):
        m = re.search(r'^\s*(?:export\s+)?PRE_QUERY_SQL="?(.*?)"?\s*$', open(tc).read(), re.M)
        pre = m.group(1) if m else ""
    if "enable_vec_pipeline" not in pre:
        # runs before 2026-11-13 did not pin the mode; proteus' guc.conf of the LAST run stays in the cluster, so pin it
        # here from the config name (<...>_run_pipe = on), otherwise a replay after a pipeline=on run uses "on"
        pre += f" set vector.enable_vec_pipeline={'on' if cfg.endswith('_pipe') else 'off'};"
    def variant(explain):
        return src.replace(":PRE_QUERY_SQL", pre).replace(":EXPLAIN_ANALYZE", explain)
    paths = {}
    for k, ex in (("q", ""), ("explain", "EXPLAIN (VERBOSE)"), ("explain_analyze", "EXPLAIN (ANALYZE, VERBOSE)")):
        p = os.path.join(out, f"{k}.sql"); open(p, "w").write(variant(ex)); paths[k] = p
    return paths, f[0]


def sampler(sql, tag, out, timeout=1800, port=None):
    port = port or os.environ.get("PGPORT"); db = os.environ.get("PGDATABASE", "gpadmin")
    r = sh(f"python3 {TRIAGE}/sampler.py --tag {tag} --sql {sql} --out {out} --port {port} --db {db} "
           f"--timeout {timeout}", timeout=timeout + 120)
    try:
        res = json.load(open(f"{out}/{tag}/result.json"))
    except Exception:
        res = dict(status="NO_RESULT", stderr=r.stderr[-500:])
    return res


def timed_rounds(order, sql, out, timeout):
    """order = [(Cluster, build), ...]; warm-up after each switch; returns {build: [elapsed...]}, shas, layouts"""
    times, shas, layouts, prev = {}, {}, {}, None
    for i, (cl, b) in enumerate(order):
        if (cl.name, b) != prev:
            layouts.setdefault(b, []).append(f"{cl.name}: " + cl.use(b))
            sampler(sql, f"warm_{b}_{i}", out, timeout, cl.port)
            prev = (cl.name, b)
        res = sampler(sql, f"t_{b}_{i}", out, timeout, cl.port)
        log(f"round {i} build {b}: {res.get('status')} {res.get('elapsed_s')}s")
        if res.get("status") == "OK" or res.get("rc") == 0:
            times.setdefault(b, []).append(res["elapsed_s"])
            shas.setdefault(b, set()).add(res.get("sha_sorted"))
    return times, {k: sorted(v) for k, v in shas.items()}, layouts


def stats(xs):
    return dict(n=len(xs), median=round(statistics.median(xs), 3), min=min(xs), max=max(xs),
                spread=round(max(xs) - min(xs), 3), raw=xs) if xs else dict(n=0)


# ---------- profiling ----------
def our_postmasters(w, name):
    pms = set()
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                a = open(f"/proc/{d}/cmdline").read().split("\0")
            except Exception:
                continue
            if a and a[0].endswith("/postgres") and "-D" in a:
                dd = a[a.index("-D") + 1]
                if f"tpcbench_{name}/" in dd or f"/clusters/{name}/" in dd:
                    pms.add(int(d))
    return pms


def procs_of(pms):
    """pid -> (con, slice-label) for children of our postmasters with a con<N> title"""
    out = {}
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            st = open(f"/proc/{d}/stat").read()
            ppid = int(st[st.rindex(")") + 2:].split()[1])
            if ppid not in pms:
                continue
            cmd = open(f"/proc/{d}/cmdline").read()
        except Exception:
            continue
        m = re.search(r"\bcon(\d+)\b", cmd)
        if m:
            sl = re.search(r"\b(cmd\d+)\s+slice(\d+)", cmd)
            out[int(d)] = (int(m.group(1)), f"{sl.group(1)}/slice{sl.group(2)}" if sl else None)
    return out


def perf_hot_local(w, name, con, secs, prefix):
    """perf hot symbols of the QEs of session con on THIS host (our cluster's postmasters only)."""
    pms = our_postmasters(w, name)
    pids = ",".join(str(p) for p, (c, _) in procs_of(pms).items() if c == con)
    if not pids:
        open(f"{prefix}.hot.txt", "w").write("no QE of this session on this host\n"); return
    sh(f"sudo -n perf record -q -F 99 -p {pids} -o {prefix}.hot.data -- sleep {secs} >/dev/null 2>&1")
    sh(f"sudo -n chown $(id -u) {prefix}.hot.data 2>/dev/null")
    rep = sh(f"perf report -i {prefix}.hot.data --stdio --no-children --sort dso,symbol --percent-limit 0.3 "
             f"2>/dev/null | grep -v '^#' | grep -v '^$' | head -60").stdout
    open(f"{prefix}.hot.txt", "w").write("\n".join(re.sub(r"\s+", " ", l).strip() for l in rep.splitlines()) + "\n")
    if os.path.exists(f"{prefix}.hot.data"):
        os.remove(f"{prefix}.hot.data")


def other_hosts(cl):
    me = os.uname().nodename.split(".")[0]
    return [h for h in json.load(open(f"{cl.c}/cluster.json"))["hosts"] if h.split(".")[0] != me]


def profile_run(cl, sql, tag, out, want_slice, expect_s, timeout):
    """run the query (sampler) and, while it runs, perf the QEs of its session."""
    pms = our_postmasters(cl.w, cl.name)
    before = {c for c, _ in procs_of(pms).values()}
    res_box = {}
    th = threading.Thread(target=lambda: res_box.update(r=sampler(sql, tag, out, timeout, cl.port)))
    th.start()
    con, deadline = None, time.time() + 30
    while time.time() < deadline and th.is_alive():
        ps = procs_of(pms)
        new = {c for c, sl in ps.values() if c not in before and sl}
        if new:
            con = min(new); break
        time.sleep(0.2)
    prof = dict(con=con)
    if con:
        time.sleep(0.5)                                  # let all gangs fork
        ps = {p: sl for p, (c, sl) in procs_of(pms).items() if c == con}
        win = max(3, min(int(expect_s) + 2, 120))
        pids = ",".join(str(p) for p in ps)
        remote = []                                      # multi-host: the same perf on every other host
        for h in other_hosts(cl):
            rp = f"{out}/{tag}.{h}"
            remote.append((h, rp, subprocess.Popen(
                f"ssh -o BatchMode=yes {h} 'mkdir -p {out} && python3 {cl.w}/bin/deep.py perfcon {cl.w} {cl.name} {con} {win} {rp}'",
                shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)))
        prof["remote_hosts"] = [h for h, _, _ in remote]
        hot = f"{out}/{tag}.hot.data"
        sh(f"sudo -n perf record -q -F 99 -p {pids} -o {hot} -- sleep {win} >/dev/null 2>&1 &")
        # dwarf call graph on one QE of the slice of interest (or the first labelled one)
        # match on the slice number only: cmd<N> differs between proteus and a standalone run (extra SET statements)
        want = want_slice.split("/")[-1] if want_slice else None
        cand = [p for p, sl in ps.items() if sl and want and sl.split("/")[-1] == want] or [p for p, sl in ps.items() if sl]
        if cand:
            cg = f"{out}/{tag}.cg.data"
            sh(f"sudo -n perf record -q -F 49 --call-graph dwarf,16384 -p {cand[0]} -o {cg} -- sleep {min(win, 20)}")
            prof["cg_pid"], prof["cg_slice"] = cand[0], ps.get(cand[0])
        prof["pids"] = len(ps)
    th.join()
    for h, rp, pr in (locals().get("remote") or []):
        try:
            pr.wait(timeout=300)
        except Exception:
            pr.kill()
        sh(f"scp -q -o BatchMode=yes {h}:{rp}.hot.txt {rp}.hot.txt")
    time.sleep(1)
    sh(f"sudo -n chown $(id -u) {out}/{tag}.*.data 2>/dev/null")
    if os.path.exists(f"{out}/{tag}.hot.data"):
        rep = sh(f"perf report -i {out}/{tag}.hot.data --stdio --no-children --sort dso,symbol --percent-limit 0.3 "
                 f"2>/dev/null | grep -v '^#' | grep -v '^$' | head -60").stdout
        rep = "\n".join(re.sub(r"\s+", " ", l).strip() for l in rep.splitlines())   # perf pads lines to ~4KB
        open(f"{out}/{tag}.hot.txt", "w").write(rep + "\n")
        prof["hot_top"] = [l[:200] for l in rep.splitlines()[:15]]
    if os.path.exists(f"{out}/{tag}.cg.data"):
        fold(f"{out}/{tag}.cg.data", f"{out}/{tag}.folded")
    for f in ("hot", "cg"):                              # perf.data is large; keep only the text results
        p = f"{out}/{tag}.{f}.data"
        if os.path.exists(p):
            os.remove(p)
    prof["result"] = {k: res_box.get("r", {}).get(k) for k in ("status", "elapsed_s", "sha_sorted", "conid")}
    return prof


def memattr_run(cl, sql, tag, out, want_slice, start, secs, nqe, timeout):
    """run the query and, while the QEs of want_slice grow, flame.sh memattr on one of them (vec-perf-triage 6.3)"""
    pms = our_postmasters(cl.w, cl.name)
    before = {c for c, _ in procs_of(pms).values()}
    box = {}
    th = threading.Thread(target=lambda: box.update(r=sampler(sql, tag, out, timeout, cl.port)))
    th.start(); t0 = time.time()
    con, deadline = None, time.time() + 30
    while time.time() < deadline and th.is_alive():
        new = {c for c, sl in procs_of(pms).values() if c not in before and sl}
        if new:
            con = min(new); break
        time.sleep(0.2)
    res = dict(con=con, slice=want_slice)
    want = want_slice.split("/")[-1]
    pid = None
    while con and th.is_alive() and time.time() - t0 < start + 30:     # the slice's QEs may fork late
        cand = [p for p, (c, sl) in procs_of(pms).items() if c == con and sl and sl.split("/")[-1] == want]
        if cand and time.time() - t0 >= start:
            pid = cand[0]; break
        time.sleep(0.2)
    if pid:
        r = sh(f"SUDO=sudo bash {TRIAGE}/flame.sh memattr {pid} {secs} {out}/{tag} {nqe}", timeout=secs + 900)
        res.update(pid=pid, window=open(f"{out}/{tag}.window").read().strip() if os.path.exists(f"{out}/{tag}.window") else None,
                   err=r.stderr[-300:] if r.returncode else None)
        if os.path.exists(f"{out}/{tag}.perfscript"):
            os.remove(f"{out}/{tag}.perfscript")        # large; opattr.txt keeps the result
    else:
        res["error"] = "no QE of the slice found in time"
    th.join()
    res["result"] = {k: box.get("r", {}).get(k) for k in ("status", "elapsed_s", "sha_sorted")}
    return res


def triage(cl, paths, qfile, s, out, a):
    summ = dict(query=qfile, set=s, cluster=cl.name, build=cl.build(), started=time.strftime("%F %T"))
    try:
        r = sampler(paths["q"], "t1", out, a.timeout, cl.port)
        summ["run"] = {k: r.get(k) for k in ("status", "elapsed_s", "sha_sorted", "rc")}
        log("triage run", summ["run"])
        summ["profile"] = profile_run(cl, paths["q"], "prof", out, a.slice, a.expect, a.timeout)
        if a.mem_slice:
            summ["memattr"] = memattr_run(cl, paths["q"], "mem", out, a.mem_slice, a.mem_start, a.mem_secs, a.mem_qes, a.timeout)
        explain(cl, paths["explain"], f"{out}/explain.txt", a.timeout)
        explain(cl, paths["explain_analyze"], f"{out}/explain_analyze.txt", a.timeout)
    except Exception as e:
        summ["error"] = str(e); log("ERROR", e)
    summ["finished"] = time.strftime("%F %T")
    json.dump(summ, open(f"{out}/triage_summary.json", "w"), indent=1, default=list)


def fold(data, outp):
    """perf script -> folded stacks (leaf last) with counts; top 200 kept."""
    txt = sh(f"perf script -i {data} 2>/dev/null", timeout=900).stdout
    stacks, cur = {}, []
    for l in txt.splitlines():
        if not l.strip():
            if cur:
                k = ";".join(reversed(cur)); stacks[k] = stacks.get(k, 0) + 1; cur = []
            continue
        if l.startswith(("\t", " ")):
            f = l.strip().split(None, 1)
            if len(f) == 2:
                cur.append(re.sub(r"\+0x[0-9a-f]+$", "", f[1].split(" (")[0]))
    if cur:
        k = ";".join(reversed(cur)); stacks[k] = stacks.get(k, 0) + 1
    with open(outp, "w") as f:
        for k, v in sorted(stacks.items(), key=lambda kv: -kv[1])[:200]:
            f.write(f"{k} {v}\n")
    # compact summary for the report writer: inclusive / self share per function (frames de-duplicated per stack)
    tot = sum(stacks.values()) or 1
    inc, slf = {}, {}
    for k, v in stacks.items():
        fr = [x for x in k.split(";") if x != "[unknown]"]
        for fn in set(fr):
            inc[fn] = inc.get(fn, 0) + v
        if fr:
            slf[fr[-1]] = slf.get(fr[-1], 0) + v
    short = lambda fn: re.sub(r"<[^<>]*>", "<>", re.sub(r"<[^<>]*>", "<>", fn))[:160]
    with open(outp.replace(".folded", ".cg_top.txt"), "w") as f:
        f.write(f"samples {tot}\n## inclusive (top 40)\n")
        for fn, v in sorted(inc.items(), key=lambda kv: -kv[1])[:40]:
            f.write(f"{v/tot:6.1%} {short(fn)}\n")
        f.write("## self (top 25)\n")
        for fn, v in sorted(slf.items(), key=lambda kv: -kv[1])[:25]:
            f.write(f"{v/tot:6.1%} {short(fn)}\n")


def explain(cl, sql, outp, timeout=1800):
    r = sh(f"psql -p {cl.port} -XAtq -v ON_ERROR_STOP=1 -c 'set statement_timeout={timeout*1000}' -f {sql}", timeout=timeout + 60)
    open(outp, "w").write(r.stdout + r.stderr)


def main():
    global TRIAGE
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["ab", "time", "perfcon", "triage"])
    ap.add_argument("args", nargs="+")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--slice", default=None)
    ap.add_argument("--base-cluster", default=None, help="ab: cluster of the base build (after a catalog bump)")
    ap.add_argument("--clusters", default=None, help="time: clusters to try in order (the build runs where its catalog fits)")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--force-profile", action="store_true", help="profile even when the verdict is NOISE (flow tests)")
    ap.add_argument("--expect", type=float, default=10)
    ap.add_argument("--mem-slice", default=None); ap.add_argument("--mem-start", type=float, default=1.5)
    ap.add_argument("--mem-secs", type=int, default=15); ap.add_argument("--mem-qes", type=int, default=0)
    a = ap.parse_args()
    if a.mode == "perfcon":                              # on a segment host, called by profile_run over ssh
        w, name, con, secs, prefix = a.args
        perf_hot_local(w, name, int(con), int(secs), prefix)
        return
    if a.mode == "triage":
        w, name, rid, s, fid, out = a.args
        TRIAGE = f"{w}/triage"
        os.makedirs(out, exist_ok=True)
        triage(Cluster(w, name), *prep_sql(w, name, rid, s, fid, out), s, out, a)
        return
    if a.mode == "ab":
        w, name, rid, s, fid, base, cur, out = a.args
    else:
        w, name, rid, s, fid, build, out = a.args
    TRIAGE = f"{w}/triage"
    os.makedirs(out, exist_ok=True)
    cl = Cluster(w, name)
    paths, qfile = prep_sql(w, name, rid, s, fid, out)
    if a.mode == "time":
        res, errs = None, []
        for cn in (a.clusters.split(",") if a.clusters else [name]):
            try:
                c = Cluster(w, cn)
                times, shas, layouts = timed_rounds([(c, build)] * a.rounds, paths["q"], f"{out}/runs", a.timeout)
                res = dict(build=build, cluster=cn, query=qfile, **stats(times.get(build, [])),
                           shas=shas.get(build), layout=layouts.get(build))
                break
            except RuntimeError as e:
                errs.append(f"{cn}: {e}")
        if res is None:
            res = dict(build=build, query=qfile, error=" | ".join(errs)[-800:])
        json.dump(res, open(f"{out}/time_{build}.json", "w"), indent=1)
        log("time", json.dumps(res)[:300])
        return
    bcl = Cluster(w, a.base_cluster) if a.base_cluster else cl
    summary = dict(query=qfile, set=s, base_build=base, cur_build=cur, base_cluster=bcl.name, cur_cluster=cl.name,
                   started=time.strftime("%F %T"))
    try:
        order = []
        for i in range(a.rounds):                       # A B B A A B ...
            order += [(bcl, base), (cl, cur)] if i % 2 == 0 else [(cl, cur), (bcl, base)]
        times, shas, layouts = timed_rounds(order, paths["q"], f"{out}/ab", a.timeout)
        A, B = stats(times.get(base, [])), stats(times.get(cur, []))
        summary.update(ab=dict(order=[f"{c.name}:{b}" for c, b in order], base=A, cur=B, layouts=layouts,
                               sha_equal=shas.get(base) == shas.get(cur), shas=shas))
        if A.get("n") and B.get("n"):
            gap = B["median"] - A["median"]
            confirmed = gap > 0.10 * A["median"] and gap > max(A["spread"], B["spread"])
            summary["verdict"] = "CONFIRMED" if confirmed else "NOISE"
            summary["gap_s"], summary["gap_pct"] = round(gap, 3), round(gap / A["median"], 3)
        else:
            summary["verdict"] = "NO_DATA"
        log("verdict", summary["verdict"], summary.get("gap_s"), summary.get("gap_pct"))
        if summary["verdict"] == "CONFIRMED" or a.force_profile:
            prof = {}
            for tag, c, b in (("base", bcl, base), ("cur", cl, cur)):
                c.use(b)
                sampler(paths["q"], f"pwarm_{tag}", f"{out}/ab", a.timeout, c.port)
                prof[tag] = profile_run(c, paths["q"], f"prof_{tag}", out, a.slice,
                                        (A if tag == "base" else B).get("median", 10), a.timeout)
                explain(c, paths["explain"], f"{out}/explain_{tag}.txt", a.timeout)
                explain(c, paths["explain_analyze"], f"{out}/explain_analyze_{tag}.txt", a.timeout)
            summary["profile"] = prof
    except RuntimeError as e:
        summary["error"] = str(e)
        log("ERROR", e)
    finally:
        try:
            cl.use(cur)
        except Exception as e:
            summary["restore_error"] = str(e)
        summary["finished"] = time.strftime("%F %T")
        json.dump(summary, open(f"{out}/deep_summary.json", "w"), indent=1, default=list)


if __name__ == "__main__":
    main()
