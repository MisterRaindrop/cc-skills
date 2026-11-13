#!/usr/bin/env python3
"""nightly.py -- unattended tpc-bench night (runs locally; start with nohup). Phase 1 -> reports 1/2 -> phase 2 for the
top slow queries -> report 3 written by `claude -p` -> all reports to the proteus report server and claude-sync.

  nightly.py --ssh root@IP --workdir W --cluster NAME --scale N [--sets h,ds] [--build latest|PIPELINE]
             [--base auto|RUN_ID] [--tags "extra"] [--allow-load] [--no-deep] [--no-sync]
             [--force-deep set:file_id[,set:file_id]]   (flow test: deep-dive these even if not slow)

Everything is logged to ~/.tpc-bench/nightly/<cluster>/<run_id>/nightly.log, state in state.json there.
Decisions fixed by the user (2026-11-12): top 3 slow queries only; fix = proposal + estimate (no build);
fully automatic overnight; reports uploaded to claude-sync under
<TPCBENCH_VAULT_DIR>/<date>-<cluster>-<run_id>/ (site.env).
"""
import argparse, json, os, re, subprocess, sys, time

S = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, S)
import tpcsite
KEY = tpcsite.get("TPCBENCH_SSH_KEY")
TRIAGE_SRC = os.path.expanduser("~/.claude/plugins/cache/cc-skills-marketplace/vec-perf-triage")
UMBRELLA = tpcsite.get("TPCBENCH_UMBRELLA_DIR")
VAULT_DIR = tpcsite.get("TPCBENCH_VAULT_DIR")
REPORT_SSH = tpcsite.get("TPCBENCH_REPORT_SSH")
REPORT_WEB = tpcsite.get("TPCBENCH_REPORT_WEB")
REPORT_DIR = tpcsite.get("TPCBENCH_REPORT_DIR", "/proteus/perf")
LOG = None


def log(*a):
    line = f"[{time.strftime('%F %T')}] " + " ".join(str(x) for x in a)
    print(line, flush=True)
    if LOG:
        open(LOG, "a").write(line + "\n")


def sh(cmd, timeout=None, check=False):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode:
        raise RuntimeError(f"{cmd[:200]}: rc={r.returncode} {r.stderr.strip()[-600:]}")
    return r


def ssh(a, cmd, timeout=None, check=False):
    return sh(f"ssh -o BatchMode=yes -i {KEY} {a.ssh} {json.dumps(cmd)}", timeout, check)


def ssh_h(h, cmd, timeout=None, check=False):
    return sh(f"ssh -o BatchMode=yes -i {KEY} {h} {json.dumps(cmd)}", timeout, check)


# ---------- idle gate (multi-host: run only when every host is idle; user requirement 2026-11-12) ----------
def idle_snapshot(a, secs=30):
    """idle.py on every host in parallel -> {host: json}"""
    procs = {h: subprocess.Popen(f"ssh -o BatchMode=yes -i {KEY} {h} 'python3 - {secs}' < {S}/remote/idle.py",
                                 shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for h in a.all_ssh}
    out = {}
    for h, p in procs.items():
        o, _ = p.communicate(timeout=secs + 120)
        try:
            out[h] = json.loads(o.strip().splitlines()[-1])
        except Exception:
            out[h] = dict(error=o[-200:])
    return out


def idle_verdict(a, snap):
    why = []
    for h, d in snap.items():
        if "error" in d:
            why.append(f"{h}: 检测失败 {d['error']}"); continue
        if d["busy_cores"] is None or d["busy_cores"] > a.idle_cpu:
            why.append(f"{d['host']}: 整机在忙 {d['busy_cores']} 核（阈值 {a.idle_cpu}），主要是 {d['top'][:3]}")
        if d["foreign_tools"]:
            why.append(f"{d['host']}: 别人的数据工具在跑 {d['foreign_tools'][:2]}")
        if d["mem_avail_gb"] < a.idle_mem_gb:
            why.append(f"{d['host']}: 可用内存 {d['mem_avail_gb']}GB < {a.idle_mem_gb}GB")
    return why


def wait_until_idle(a, st):
    """two idle verdicts 5 min apart; otherwise re-check every 15 min until the deadline. Returns (ok, last reasons)."""
    import datetime
    now = datetime.datetime.now()
    hh, mm = map(int, a.idle_deadline.split(":"))
    deadline = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if deadline <= now:
        deadline += datetime.timedelta(days=1)
    log(f"idle gate: hosts {a.all_ssh}, cpu<{a.idle_cpu} cores, mem>={a.idle_mem_gb}GB, deadline {deadline:%F %H:%M}")
    first_ok_at, why = None, []
    while datetime.datetime.now() < deadline:
        snap = idle_snapshot(a)
        why = idle_verdict(a, snap)
        st.set(phase="idle_gate", idle_last=dict(at=time.strftime("%F %T"), reasons=why,
                                                  busy={d.get("host", h): d.get("busy_cores") for h, d in snap.items()}))
        if not why:
            if first_ok_at and time.time() - first_ok_at >= 290:
                log("idle gate: idle twice (5 min apart) -> go")
                return True, []
            first_ok_at = first_ok_at or time.time()
            log("idle gate: idle, confirming in 5 min")
            time.sleep(300)
        else:
            first_ok_at = None
            log("idle gate: busy ->", "; ".join(why))
            time.sleep(900)
    return False, why


def gp(a, cmd, timeout=None, check=False):
    """run as gpadmin on the coordinator host"""
    return ssh(a, f"su - gpadmin -c {json.dumps(cmd)}", timeout, check)


class State:
    def __init__(self, p):
        self.p, self.d = p, (json.load(open(p)) if os.path.exists(p) else {})

    def set(self, **kw):
        self.d.update(kw, updated=time.strftime("%F %T"))
        json.dump(self.d, open(self.p, "w"), indent=1, ensure_ascii=False)


def sync_scripts(a):
    W = a.workdir
    sh(f"chmod +x {S}/remote/*")
    for h in a.all_ssh:                                  # collectors / perf helpers run on every host
        ssh_h(h, f"mkdir -p {W}/bin && chown gpadmin {W}", check=True)
        sh(f"rsync -a -e 'ssh -i {KEY}' {S}/remote/ {h}:{W}/bin/", check=True)
        sh(f"scp -q -i {KEY} {tpcsite.PATH} {h}:{W}/bin/site.env", check=True)   # remote/upload.sh sources it
        ssh_h(h, f"chmod +x {W}/bin/*; chown -R gpadmin {W}/bin", check=True)
    # proteus (coordinator only): keep the tpc-bench patches current (load.sh refuses an unpatched copy)
    pl = os.path.expanduser("~/.cache/tpc-bench/proteus")
    sh(f"bash {S}/patch_proteus.sh {pl}", check=True)
    sh(f"rsync -a --exclude .git --exclude results -e 'ssh -i {KEY}' {pl}/ {a.ssh}:{W}/proteus/", check=True)
    ssh(a, f"chown -R gpadmin {W}/proteus")
    tri = sorted(d for d in os.listdir(TRIAGE_SRC) if not d.startswith("."))[-1]
    sh(f"rsync -a -e 'ssh -i {KEY}' {TRIAGE_SRC}/{tri}/skills/vec-perf-triage/scripts/ {a.ssh}:{W}/triage/", check=True)
    ssh(a, f"chmod +x {W}/bin/* {W}/triage/*; chown -R gpadmin {W}/bin {W}/triage", check=True)


def resolve(build):
    r = sh(f"python3 {S}/resolve_build.py {build} --arch aarch64", timeout=600)
    if r.returncode:
        raise RuntimeError(f"resolve_build {build}: {r.stderr.strip()[-300:]}")
    return json.loads(r.stdout)


def ensure_build(a, pid):
    """package of pipeline pid downloaded + unpacked on every host (kept for later comparisons/bisects)."""
    W, b, ok = a.workdir, None, True
    for h in a.all_ssh:
        if ssh_h(h, f"test -f {W}/gphome-{pid}/.tpcbench_ok && echo y").stdout.strip() == "y":
            continue
        b = b or resolve(pid)
        tmp = f"/tmp/tpcbench_build_{pid}.json"
        open(tmp, "w").write(json.dumps(b))
        ssh_h(h, f"mkdir -p {W}/pkgs/{pid}")
        sh(f"scp -q -i {KEY} {tmp} {h}:{W}/pkgs/{pid}/build.json", check=True)
        r = ssh_h(h, f"{W}/bin/fetch_deploy.sh {W} {pid} {b['rpm_url']} {b['release_yaml_url']}", timeout=1800)
        log(f"fetch_deploy {pid} on {h}:", (r.stdout + r.stderr).strip().splitlines()[-1:])
        ok = ok and ssh_h(h, f"test -f {W}/gphome-{pid}/.tpcbench_ok && echo y").stdout.strip() == "y"
    return ok


def active_cluster(a):
    """the logical cluster name (e.g. sf10) points at the cluster generation currently in use"""
    r = ssh(a, f"cat {a.workdir}/clusters/{a.logical}.active 2>/dev/null").stdout.strip()
    return r or a.logical


def new_cluster_after_catalog_bump(a, pid):
    """the new build cannot start on the current cluster (catalog version changed): create a new generation with the
    same layout, keep the old one (phase 2 compares old build on old cluster vs new build on new cluster).
    Never deletes anything; stops when the data disks look too small."""
    W, old = a.workdir, a.cluster
    cj = json.loads(ssh(a, f"cat {W}/clusters/{old}/cluster.json", check=True).stdout)
    nseg, hosts, dirs, port = cj["segs_per_host"], cj["hosts"], cj["datadirs"], int(cj["port"])
    name = f"{a.logical}_b{pid}"
    # disk: the new generation needs about what the old one uses, plus generated flat files while loading
    for d in dirs:
        used = int((ssh(a, f"du -sb {d}/tpcbench_{old} 2>/dev/null | cut -f1").stdout.strip() or "0"))
        avail = int(ssh(a, f"df -B1 --output=avail {d} | tail -1").stdout.strip() or "0")
        need = int(used * 2.5)
        log(f"disk {d}: old cluster uses {used/2**30:.0f}GB, need ~{need/2**30:.0f}GB, available {avail/2**30:.0f}GB")
        if avail < need:
            raise RuntimeError(f"catalog bump: new cluster needs ~{need/2**30:.0f}GB on {d}, only {avail/2**30:.0f}GB free; "
                               f"nothing deleted -- decide which cluster generation to drop")
    for k in range(1, 20):
        p = port + k * (nseg + 1)
        r = gp(a, f"{W}/bin/init_cluster.sh {W} {name} {pid} {p} {nseg} {','.join(hosts)} {','.join(dirs)}", timeout=3600)
        log(f"init_cluster {name} port {p}:", (r.stdout + r.stderr).strip().splitlines()[-1:])
        if ssh(a, f"test -f {W}/clusters/{name}/cluster.json && echo y").stdout.strip() == "y":
            break
        if "in use" not in r.stdout + r.stderr:
            raise RuntimeError(f"init_cluster {name} failed: {(r.stdout + r.stderr)[-500:]}")
    else:
        raise RuntimeError("no free port range for the new cluster")
    gp(a, f"cp {W}/clusters/{old}/host.json {W}/clusters/{name}/ 2>/dev/null; echo {name} > {W}/clusters/{a.logical}.active; "
          f"echo {old} > {W}/clusters/{name}.prev", check=True)
    return name


def cluster_build(a):
    return ssh(a, f"cat {a.workdir}/clusters/{a.cluster}/build.cur").stdout.strip()


def wait_state(a, rid, poll=60, limit_h=10):
    p = f"{a.workdir}/clusters/{a.cluster}/runs/{rid}/state.json"
    t0 = time.time()
    while time.time() - t0 < limit_h * 3600:
        r = ssh(a, f"cat {p} 2>/dev/null")
        try:
            st = json.loads(r.stdout)
            if st.get("phase") == "done":
                return st
        except Exception:
            pass
        time.sleep(poll)
    raise RuntimeError(f"run {rid} not done after {limit_h}h")


# ---------- phase 2 ----------
def bisect(a, slow, base_b, cur_b, base_med, cur_med, out, clusters):
    """first pipeline in (base_b, cur_b] where the query is slow. Uses deep.py time (3 runs, clean layout).
    Returns dict with culprit pipeline, its predecessor and the measurements."""
    r = sh(f"python3 {S}/resolve_build.py between:{base_b}:{cur_b} --arch aarch64", timeout=1800)
    pipes = [p for p in json.loads(r.stdout or "[]")] if r.returncode == 0 else []
    avail = [p["pipeline"] for p in pipes if p["artifacts"] or p["pipeline"] == int(cur_b)]
    res = dict(range=[base_b, cur_b], pipelines=[p["pipeline"] for p in pipes], available=avail, steps=[])
    if len(pipes) <= 1:
        res.update(culprit=int(cur_b), prev=int(base_b), note="相邻构建，不需要二分")
        return res
    expired = [p["pipeline"] for p in pipes if not p["artifacts"] and p["pipeline"] != int(cur_b)]
    if expired:
        res["note"] = f"{len(expired)} 个流水线的产物已过期（CI 只保留 7 天），只在可下载的里面二分"
    thr = (base_med + cur_med) / 2
    lo, hi = -1, len(avail) - 1                          # index -1 = base (fast), hi = cur (slow)
    while hi - lo > 1:
        mid = (lo + hi) // 2
        pid = avail[mid]
        if not ensure_build(a, pid):
            res["steps"].append(dict(pipeline=pid, error="deploy failed")); break
        d = f"{out}/bisect"
        gp(a, f"{a.workdir}/bin/deep.sh {a.workdir} {a.cluster} time {a.workdir} {a.cluster} {a.run_id} "
              f"{slow['set'].replace('tpc-', '')} {slow['file_id']} {pid} {d} --rounds 3 --clusters {','.join(clusters)}",
              timeout=4 * 3600)
        t = json.loads(ssh(a, f"cat {d}/time_{pid}.json 2>/dev/null").stdout or "{}")
        slow_here = t.get("median") is not None and t["median"] > thr
        res["steps"].append(dict(pipeline=pid, median=t.get("median"), spread=t.get("spread"),
                                 error=t.get("error"), slow=slow_here))
        log(f"bisect {slow['name']}: pipeline {pid} median {t.get('median')} (threshold {thr:.2f}) -> {'slow' if slow_here else 'fast'}")
        if t.get("error"):
            res["note"] = (res.get("note", "") + f"；{pid} 无法测试：{t['error'][:120]}").strip("；"); break
        if slow_here:
            hi = mid
        else:
            lo = mid
    res["culprit"] = avail[hi]
    res["prev"] = avail[lo] if lo >= 0 else int(base_b)
    return res


def phase2(a, slow_json, od):
    W, rid = a.workdir, a.run_id
    results = []
    todo = slow_json.get("top", [])
    for spec in a.force_deep:
        s, fid = spec.split(":")
        if not any(x["set"] in (s, f"tpc-{s}") and str(x["file_id"]) == fid for x in todo):
            todo.append(dict(set=f"tpc-{s}", name=f"{s}#{fid}", file_id=int(fid), forced=True))
    for x in todo[:3]:
        s = x["set"].replace("tpc-", "")
        info = slow_json["sets"].get(s, {})
        base_b, cur_b = str(info.get("base_build") or info.get("cur_build")), str(info["cur_build"])
        out = f"{W}/clusters/{a.cluster}/runs/{rid}/deep/{s}_{x['file_id']}"
        bcl = info.get("base_cluster") or a.cluster
        sl = (x.get("slice_delta") or "").split(" ")[0] or None
        if not sl or sl == "slice?":             # no per-slice delta: profile the slice that was busy longest this run
            rj = json.loads(ssh(a, f"cat {W}/clusters/{a.cluster}/runs/{rid}/{s}/run.json").stdout or "{}")
            sl = next((q.get("longest_busy_slice") for q in rj.get("queries", []) if q.get("file_id") == x["file_id"]), None)
        log(f"phase2 {x['name']}: base {base_b} vs cur {cur_b} slice {sl}")
        if not ensure_build(a, base_b):
            results.append(dict(query=x, error=f"base build {base_b} package not available")); continue
        extra = " --force-profile" if x.get("forced") else ""
        gp(a, f"{W}/bin/deep.sh {W} {a.cluster} ab {W} {a.cluster} {rid} {s} {x['file_id']} {base_b} {cur_b} {out} "
              f"--rounds 3" + (f" --slice {sl}" if sl else "") + extra +
              (f" --base-cluster {bcl}" if bcl != a.cluster else ""), timeout=6 * 3600)
        summ = json.loads(ssh(a, f"cat {out}/deep_summary.json 2>/dev/null").stdout or "{}")
        item = dict(query=x, deep=f"deep/{s}_{x['file_id']}", verdict=summ.get("verdict"), gap_s=summ.get("gap_s"),
                    gap_pct=summ.get("gap_pct"), error=summ.get("error"))
        log(f"phase2 {x['name']}: verdict {summ.get('verdict')} gap {summ.get('gap_s')}s")
        if summ.get("verdict") == "CONFIRMED" and base_b != cur_b:
            item["bisect"] = bisect(a, x, base_b, cur_b, summ["ab"]["base"]["median"], summ["ab"]["cur"]["median"], out,
                                    [a.cluster] + ([bcl] if bcl != a.cluster else []))
            log(f"phase2 {x['name']}: culprit pipeline {item['bisect'].get('culprit')}")
        results.append(item)
    gp(a, f"{W}/bin/cluster.sh {W} {a.cluster} use {slow_json['sets'][next(iter(slow_json['sets']))]['cur_build']}")
    # bring the deep data home (small: text results, no perf.data)
    sh(f"mkdir -p {od}/deep && rsync -a -e 'ssh -i {KEY}' {a.ssh}:{W}/clusters/{a.cluster}/runs/{rid}/deep/ {od}/deep/")
    json.dump(results, open(f"{od}/phase2.json", "w"), indent=1, ensure_ascii=False)
    return results


def triage_top3(a, od):
    """vec-perf-triage on the 3 slowest successful queries of every test set of this run (user 2026-11-13), on the
    current build: sampler + perf (all QEs, every host) + dwarf call graph of the longest-busy slice + memattr of the
    biggest slice when the query used >= 50GB + EXPLAIN ANALYZE. Data -> <od>/triage/<set>_<file_id>/."""
    W, rid = a.workdir, a.run_id
    res = []
    for s in a.sets.split(","):
        rj = json.loads(ssh(a, f"cat {W}/clusters/{a.cluster}/runs/{rid}/{s}/run.json 2>/dev/null").stdout or "{}")
        ok = [q for q in rj.get("queries", []) if q.get("status") == "OK"]
        for q in sorted(ok, key=lambda q: -(q.get("seconds") or 0))[:3]:
            out = f"{W}/clusters/{a.cluster}/runs/{rid}/triage/{s}_{q['file_id']}"
            args = f" --expect {q['seconds']}"
            if q.get("longest_busy_slice"):
                args += f" --slice {q['longest_busy_slice']}"
            sl = q.get("slices") or {}
            if (q.get("peak_rss_gb") or 0) >= 50 and sl:
                k, v = max(((k, v) for k, v in sl.items() if k != "QD"), key=lambda kv: kv[1].get("peak_gb") or 0)
                b0, b1 = (v.get("busy") or [1.5, 1.5 + q["seconds"]])[:2]
                args += (f" --mem-slice {k} --mem-start {max(1.0, b0)} --mem-secs {int(min(20, max(5, (b1 - b0) / 2)))}"
                         f" --mem-qes {v.get('qes') or 0}")
            log(f"triage {s} {q['name']} ({q['seconds']}s):{args}")
            gp(a, f"{W}/bin/deep.sh {W} {a.cluster} triage {W} {a.cluster} {rid} {s} {q['file_id']} {out}{args}",
               timeout=4 * 3600)
            summ = json.loads(ssh(a, f"cat {out}/triage_summary.json 2>/dev/null").stdout or "{}")
            res.append(dict(set=s, name=q["name"], file_id=q["file_id"], seconds=q["seconds"], dir=f"triage/{s}_{q['file_id']}",
                            run=summ.get("run"), error=summ.get("error")))
    sh(f"mkdir -p {od}/triage && rsync -a -e 'ssh -i {KEY}' {a.ssh}:{W}/clusters/{a.cluster}/runs/{rid}/triage/ {od}/triage/")
    for s in a.sets.split(","):        # triage_html.py reads <od>/<set>/run.json
        sh(f"mkdir -p {od}/{s} && scp -q -i {KEY} {a.ssh}:{W}/clusters/{a.cluster}/runs/{rid}/{s}/run.json {od}/{s}/")
    json.dump(res, open(f"{od}/triage.json", "w"), indent=1, ensure_ascii=False)
    return res


# ---------- report 3 + uploads ----------
def triage_skill_dir():
    tri = sorted(d for d in os.listdir(TRIAGE_SRC) if not d.startswith("."))[-1]
    return f"{TRIAGE_SRC}/{tri}/skills/vec-perf-triage"


def report3_and_sync(a, od, slow_json, phase2_res, report_ids, tri=()):
    date = a.run_id[:8]
    vdir = f"{VAULT_DIR}/{date[:4]}-{date[4:6]}-{date[6:]}-{a.cluster}-{a.run_id}"
    td = triage_skill_dir()
    need3 = bool(phase2_res) or bool(tri)
    prompt = f"""你在无人值守模式下为一次 tpc-bench 夜间测试收尾。工作目录是 umbrella 仓库 {UMBRELLA}（database、arrow 是子模块，可用 git 查提交和代码）。
数据都在 {od}：
- report1_results.md（本次结果）、report2_slow.md（慢查询判定和提交范围）、slow.json
- phase2.json：阶段 2 每条慢查询的复核结论（verdict CONFIRMED/NOISE）、差距、二分结果（bisect.culprit = 第一个变慢的流水线，prev = 它前一个）
- deep/<set>_<file_id>/：deep_summary.json（ABBA 原始耗时）、prof_base|prof_cur.hot.txt（全部 QE 的热点函数）、
  prof_*.cg_top.txt（关键 slice 一个 QE 的调用栈汇总）、explain_*.txt / explain_analyze_*.txt（新旧构建的计划和实际执行）、ab/*/summary.txt（每秒采样汇总）
任务：
"""
    if need3:
        prompt += f"""1. 写报告③ {od}/report3_deep.md（中文）。方法按 vec-perf-triage skill：先读 {td}/SKILL.md 的第 9–11 步和 {td}/references/known-patterns.md。
   - 开头：总体结论（几条确认变慢、合计慢多少、指向哪些提交、修复优先级）。
   - 每条查询一节：现象（数字，引用 deep_summary 的原始耗时）；复核结论；二分定位到的流水线；
     提交：用 git 在 database / database/contrib/apache-arrow/arrow 里查 culprit 流水线和 prev 之间的提交
     （两次构建的 SHA 在 slow.json 的 sets.*.base_commits/cur_commits；中间流水线的 SHA 用 `python3 {S}/resolve_build.py <pipeline>` 拿 umbrella sha 后 `git ls-tree <sha> database`），读相关提交的 diff；
     因果链（热点函数差异 + 计划差异 + 代码改动，必须连得上）；证据至少两条；置信度（已证实/很可能/推测）；
     修复方案（改哪个文件哪个函数、怎么改）；修复后预计耗时和依据（以旧构建实测为上限，标明“估算”）；风险。
   - verdict 为 NOISE 的查询写明“复核未确认，属于波动”，不做归因。
   - 不确定就写不确定，不要编造；没有直接证据的结论标“推测”。
"""
    else:
        prompt += "1. 本次没有确认的慢查询，不写报告③。\n"
    if tri:
        prompt += f"""1b. 报告③ {od}/report3_deep.md 里加一部分“最慢的 3 条 SQL 分析”（每个测试集各 3 条，见 triage.json；没有慢查询时报告③只写这一部分）。
   方法严格按 vec-perf-triage skill（{td}/SKILL.md 第 2–11 步，问题库 {td}/references/known-patterns.md）。每条的数据在 triage/<set>_<file_id>/：
   t1/summary.txt（每个 slice 的 peak_sum、倾斜、busy 区间、CPU）、prof.hot.txt 和 prof.<host>.hot.txt（全部 QE 热点函数）、
   prof.cg_top.txt（最忙 slice 一个 QE 的调用栈汇总）、mem.opattr.txt（内存按算子/函数归因，有就用）、explain.txt、explain_analyze.txt（实际行数）。
   每条一节：现象（耗时、内存、CPU，引用数字）；计划 DAG 与关键路径（哪个 slice 在关键路径上，busy 区间）；资源体检一句话；
   时间/内存花在哪个算子和函数（引用热点和调用栈）；行数估计与实际的偏差；归类（E/F/A/B/C/D）；因果链；至少两条证据；
   置信度（已证实/很可能/推测）；优化方向（改哪里、预计收益，标“估算”）。没有数据支撑的不要写成结论。
1c. 同时把每条的分析写成 {od}/triage_analysis.json（用户认可的页面格式由 {S}/triage_html.py 渲染，字段说明见该文件开头）：
   {{"key_points": [3–5 条最重要的结论，每条一句、带数字，可用 <b> 标重点],
     "queries": {{"<set>:<file_id>": {{"verdict": 一句话结论, "saving": 可省多少（估算）, "advice": 建议, "confidence": "已证实|很可能|推测",
       "dag": 各 slice 做什么和关键路径, "use": 资源体检一句话, "time": 时间花在哪（热点函数）, "memory": 内存花在哪（memattr）,
       "rows": 估计 vs 实际行数, "category": 归类, "chain": 因果链, "evidence": [证据1, 证据2, ...], "cause_short": 主要原因（10 字以内）}}}}}}
   没有数据的字段留空字符串，页面会显示“待 triage 数据”。
"""
    prompt += f"""2. 用 mcp__claude-sync__create_vault_file 把以下文件上传到知识库目录 {vdir}/（文件内容原样上传，不要改写）：
   report1_results.md、report2_slow.md{'、report3_deep.md' if need3 else ''}，再上传一个 index.md：
   一段话写清日期、集群、构建、报告链接（{', '.join(f'{REPORT_WEB}/{r}' for r in report_ids.values() if r)}）、
   有无慢查询和结论要点，并列出三份报告的文件名。
3. 最后只输出一行：OK 或失败原因。
"""
    pf = f"{od}/claude_prompt.txt"
    open(pf, "w").write(prompt)
    tools = ("Read,Grep,Glob,Write,Bash(git:*),Bash(python3:*),Bash(ls:*),Bash(cat:*),Bash(head:*),"
             "Bash(grep:*),Bash(wc:*),mcp__claude-sync__create_vault_file,mcp__claude-sync__get_vault_file")
    log("claude -p: writing report 3 and syncing to claude-sync" if need3 else "claude -p: syncing reports to claude-sync")
    r = sh(f"cd {UMBRELLA} && claude -p \"$(cat {pf})\" --allowedTools '{tools}' --add-dir {od} --add-dir {S} "
           f"--add-dir {td} > {od}/claude_out.txt 2>&1", timeout=3 * 3600)
    out = open(f"{od}/claude_out.txt").read().strip().splitlines()
    log("claude -p:", out[-1] if out else f"rc={r.returncode}")
    if tri:                             # the approved "最慢 3 条 SQL 分析" page (triage_html.py)
        sub = f"{a.cluster} | run {a.run_id} | 构建 {slow_json['sets'][next(iter(slow_json['sets']))].get('cur_build')}"
        sh(f"python3 {S}/triage_html.py {od} {od}/triage.html --analysis {od}/triage_analysis.json --subtitle '{sub}'")
        key = os.path.expanduser("~/.tpc-bench/report_key")
        for rid in [x for x in report_ids.values() if x]:
            sh(f"scp -q -o BatchMode=yes -o StrictHostKeyChecking=no -i {key} {od}/triage.html "
               f"{REPORT_SSH}:{REPORT_DIR}/{rid}/tpcbench/triage.html")
        log(f"triage page: {od}/triage.html")
    if need3 and os.path.exists(f"{od}/report3_deep.md"):
        key = os.path.expanduser("~/.tpc-bench/report_key")
        for rid in [x for x in report_ids.values() if x]:
            sh(f"scp -q -o BatchMode=yes -o StrictHostKeyChecking=no -i {key} {od}/report3_deep.md "
               f"{REPORT_SSH}:{REPORT_DIR}/{rid}/tpcbench/report3_deep.md")
        sh(f"scp -q -i {KEY} {od}/report3_deep.md {a.ssh}:{a.workdir}/clusters/{a.cluster}/runs/{a.run_id}/")
    return vdir


def main():
    global LOG
    ap = argparse.ArgumentParser()
    ap.add_argument("--ssh", required=True); ap.add_argument("--workdir", required=True)
    ap.add_argument("--cluster", required=True); ap.add_argument("--scale", required=True)
    ap.add_argument("--sets", default="h,ds"); ap.add_argument("--build", default="latest")
    ap.add_argument("--base", default="auto"); ap.add_argument("--tags", default="")
    ap.add_argument("--allow-load", action="store_true"); ap.add_argument("--no-deep", action="store_true")
    ap.add_argument("--no-sync", action="store_true")
    ap.add_argument("--no-triage", action="store_true", help="skip vec-perf-triage of the 3 slowest queries per set")
    ap.add_argument("--rounds", type=int, default=3, help="each query N times back to back; times = median (user 2026-11-13)")
    ap.add_argument("--streams", type=int, default=1,
                    help=">1: concurrency test, N concurrent streams (proteus multi-user), separate config/baseline <rid>_c<N>")
    ap.add_argument("--force-deep", default="", help="set:file_id,... deep-dive even if not slow (flow test)")
    ap.add_argument("--run-id", default=None, help="reuse an existing finished run (skip phase 1)")
    ap.add_argument("--pipeline", choices=["off", "on"], default="off",
                    help="vector.enable_vec_pipeline for the timed run; 'on' is a separate config (<rid>_pipe, baselines "
                         "only among pipeline=on runs). Both modes = two nightly runs one after the other")
    ap.add_argument("--hosts", default="", help="other hosts of a multi-host cluster, ssh targets: root@IP,root@IP")
    ap.add_argument("--idle-gate", choices=["auto", "on", "off"], default="auto",
                    help="auto = on for multi-host (run only when every host is idle)")
    ap.add_argument("--idle-cpu", type=float, default=6.0, help="max busy cores per host to count as idle")
    ap.add_argument("--idle-mem-gb", type=int, default=None, help="min MemAvailable per host (default 350 at >=1TB, else 50)")
    ap.add_argument("--idle-deadline", default="03:00", help="give up (skip the night) if not idle by HH:MM")
    a = ap.parse_args()
    a.force_deep = [x for x in a.force_deep.split(",") if x]
    a.logical = a.cluster
    a.all_ssh = [a.ssh] + [h for h in a.hosts.split(",") if h]
    a.idle_mem_gb = a.idle_mem_gb if a.idle_mem_gb is not None else (350 if float(a.scale) >= 1000 else 50)
    a.run_id_given = bool(a.run_id)
    a.run_id = a.run_id or (time.strftime("%Y%m%d_%H%M%S") + (f"_c{a.streams}" if a.streams > 1 else "")
                            + ("_pipe" if a.pipeline == "on" else ""))
    nd = os.path.expanduser(f"~/.tpc-bench/nightly/{a.cluster}/{a.run_id}"); os.makedirs(nd, exist_ok=True)
    LOG = f"{nd}/nightly.log"
    st = State(f"{nd}/state.json")
    st.set(run_id=a.run_id, phase="start", args=vars(a))
    W = a.workdir
    try:
        gate = a.idle_gate == "on" or (a.idle_gate == "auto" and len(a.all_ssh) > 1)
        if gate and not a.run_id_given:
            ok, why = wait_until_idle(a, st)
            if not ok:
                log("idle gate: not idle before the deadline -> skip tonight")
                st.set(phase="done", ok=True, skipped=True, reasons=why)
                if not a.no_sync:
                    skip_sync(a, nd, why)
                return
        sync_scripts(a)
        a.cluster = active_cluster(a)
        st.set(cluster=a.cluster)
        log(f"cluster {a.logical} -> {a.cluster}")
        hj = f"{W}/clusters/{a.cluster}/host.json"
        if ssh(a, f"test -s {hj} && echo y").stdout.strip() != "y":
            # mkconfig.py (hardware fields of the report) needs it; init_cluster.sh does not write it
            tmp = f"/tmp/tpcbench_host_{os.getpid()}.json"
            sh(f"ssh -o BatchMode=yes -i {KEY} {a.ssh} 'python3 -' < {S}/remote/discover.py > {tmp}", check=True)
            json.load(open(tmp))
            sh(f"scp -q -o BatchMode=yes -i {KEY} {tmp} {a.ssh}:{hj} && "
               f"ssh -o BatchMode=yes -i {KEY} {a.ssh} 'chown gpadmin {hj}'; rm -f {tmp}", check=True)
            log(f"wrote {hj} (discover)")
        if not ssh(a, f"test -d {W}/clusters/{a.cluster}/runs/{a.run_id} && echo y").stdout.strip():
            # ---- build ----
            b = resolve(a.build)
            pid = str(b["pipeline"])
            log(f"build {pid} ({b['created_at']}) umbrella {b['sha'][:10]}")
            st.set(phase="deploy", build=pid)
            if not ensure_build(a, pid):
                raise RuntimeError(f"deploy of {pid} failed")
            if cluster_build(a) != pid:
                r = gp(a, f"{W}/bin/cluster.sh {W} {a.cluster} use {pid}", timeout=1800)
                if cluster_build(a) != pid:
                    out = (r.stdout + r.stderr)
                    if "atalog" not in out:
                        raise RuntimeError(f"cluster cannot switch to {pid}: {out[-300:]}")
                    # user decision 2026-11-12: catalog incompatible -> new cluster + reload automatically
                    log(f"catalog version changed at build {pid}: creating a new cluster generation and reloading")
                    st.set(phase="new_cluster", old_cluster=a.cluster)
                    a.cluster = new_cluster_after_catalog_bump(a, pid)
                    a.allow_load = True
                    st.set(cluster=a.cluster)
            # ---- data ----
            for s in a.sets.split(","):
                dj = f"{W}/clusters/{a.cluster}/data_{s}_sf{a.scale}pax.json"
                if ssh(a, f"test -f {dj} && echo y").stdout.strip() != "y":
                    if not a.allow_load:
                        raise RuntimeError(f"no {s} data for sf{a.scale} (hash) and --allow-load not given")
                    st.set(phase=f"load:{s}")
                    log(f"load {s} sf{a.scale}")
                    r = gp(a, f"{W}/bin/load.sh {W} {a.cluster} {s} {a.scale}", timeout=12 * 3600)
                    log("load:", (r.stdout + r.stderr).strip().splitlines()[-1:])
                    if ssh(a, f"test -f {dj} && echo y").stdout.strip() != "y":     # load.sh writes it only on success
                        raise RuntimeError(f"load {s} sf{a.scale} failed: " + (r.stdout + r.stderr)[-600:])
            # ---- phase 1 ----
            hostname = ssh(a, "hostname -s").stdout.strip()
            nhosts = len(json.loads(ssh(a, f"cat {W}/clusters/{a.cluster}/cluster.json").stdout).get("hosts", [1]))
            tags = (f"pax hash vecon pipe{a.pipeline} c{a.streams} r{a.rounds} b{pid} {nhosts}node {hostname} sf{a.scale} "
                    f"nightly {a.tags}").strip()
            st.set(phase="phase1", tags=tags)
            log(f"phase1 run {a.run_id} tags '{tags}'")
            tags = re.sub(r"[^A-Za-z0-9_. -]", "", tags)          # passes through ssh + su quoting unchanged
            gp(a, f"nohup {W}/bin/run.sh {W} {a.cluster} {a.run_id} {a.sets} {a.scale} true '{tags}' --pipeline {a.pipeline} --rounds {a.rounds} --streams {a.streams} > /dev/null 2>&1 &")
            time.sleep(20)
            wait_state(a, a.run_id)
            log("phase1 done")
        # ---- reports 1, 2 ----
        st.set(phase="analyze")
        r = sh(f"python3 {S}/analyze.py --host {a.ssh} --workdir {W} --cluster {a.cluster} --run {a.run_id} "
               f"--set {a.sets} --base {a.base} --upload", timeout=3600)
        od = r.stdout.strip().splitlines()[-1]
        log("reports 1/2:", od, r.stderr.strip()[-300:])
        slow = json.load(open(f"{od}/slow.json"))
        report_ids = {s: v.get("report_id") for s, v in slow["sets"].items()}
        log(f"slow queries: {slow['slow_total']} (top: {[x['name'] for x in slow['top']]})")
        # ---- phase 2 ----
        p2 = []
        if (slow["top"] or a.force_deep) and not a.no_deep:
            st.set(phase="phase2")
            p2 = phase2(a, slow, od)
        tri = []
        if not a.no_triage and a.streams == 1 and not a.run_id.split("_")[-1].startswith("c"):
            st.set(phase="triage")
            tri = triage_top3(a, od)
        # ---- report 3 + sync ----
        if not a.no_sync:
            st.set(phase="report3_sync")
            vdir = report3_and_sync(a, od, slow, p2, report_ids, tri)
            st.set(vault_dir=vdir)
        st.set(phase="done", ok=True, out=od)
        log("nightly done:", od)
    except Exception as e:
        log("ERROR", repr(e))
        st.set(phase="done", ok=False, error=repr(e))
        if not a.no_sync:
            fail_sync(a, nd, st.d, e)
        sys.exit(1)


def skip_sync(a, nd, why):
    """idle gate said no: leave a short note in claude-sync so the morning shows the night was skipped and why."""
    body = (f"# tpc-bench 夜间测试未运行：{a.cluster}（{a.run_id}）\n\n多机测试只在所有机器空闲时运行；"
            f"到截止时间 {a.idle_deadline} 仍不空闲，本晚跳过。\n\n最后一次检测：\n\n" + "\n".join(f"- {w}" for w in why) + "\n")
    open(f"{nd}/report0_skipped.md", "w").write(body)
    date = a.run_id[:8]
    vdir = f"{VAULT_DIR}/{date[:4]}-{date[4:6]}-{date[6:]}-{a.cluster}-{a.run_id}"
    pf = f"{nd}/claude_prompt_skip.txt"
    open(pf, "w").write(f"用 mcp__claude-sync__create_vault_file 把文件 {nd}/report0_skipped.md 原样上传为 {vdir}/index.md，"
                        "然后只输出一行 OK 或失败原因。")
    sh(f"claude -p \"$(cat {pf})\" --allowedTools 'Read,mcp__claude-sync__create_vault_file' --add-dir {nd} "
       f"> {nd}/claude_out_skip.txt 2>&1", timeout=900)
    log("skip note synced:", open(f"{nd}/claude_out_skip.txt").read().strip()[-200:])


def fail_sync(a, nd, state, err):
    """a failed night still leaves a report in claude-sync, so the morning shows why."""
    msg = str(err)
    hint = ""
    if "catalog" in msg.lower():
        hint = ("\n\n**原因：新构建的 catalog 版本和集群不兼容。** 需要用新构建新建集群并重新导数据"
                "（1TB 约 3 小时），旧集群保留用于跨 catalog 的新旧对比。")
    body = (f"# tpc-bench 夜间测试失败：{a.cluster} / {a.run_id}\n\n- 阶段：{state.get('phase')}\n- 构建：{state.get('build')}\n"
            f"- 错误：\n\n```\n{msg[-2000:]}\n```{hint}\n\n日志：本机 {nd}/nightly.log\n")
    open(f"{nd}/report0_failed.md", "w").write(body)
    date = a.run_id[:8]
    vdir = f"{VAULT_DIR}/{date[:4]}-{date[4:6]}-{date[6:]}-{a.cluster}-{a.run_id}"
    pf = f"{nd}/claude_prompt_fail.txt"
    open(pf, "w").write(f"用 mcp__claude-sync__create_vault_file 把文件 {nd}/report0_failed.md 原样上传为 {vdir}/index.md，"
                        "然后只输出一行 OK 或失败原因。")
    sh(f"claude -p \"$(cat {pf})\" --allowedTools 'Read,mcp__claude-sync__create_vault_file' --add-dir {nd} "
       f"> {nd}/claude_out_fail.txt 2>&1", timeout=900)
    log("failure report synced:", open(f"{nd}/claude_out_fail.txt").read().strip()[-200:])


if __name__ == "__main__":
    main()
