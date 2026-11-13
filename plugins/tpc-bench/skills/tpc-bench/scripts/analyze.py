#!/usr/bin/env python3
"""analyze.py -- turn one tpc-bench run into an analysis report (analysis.md).

Runs on the local machine (needs the umbrella git repo for commit ranges).

  analyze.py --host <ssh target> --workdir <W> --cluster <name> --run <run_id>
             [--set h|ds|h,ds] [--base <run_id>|auto|none] [--umbrella <local umbrella checkout>]
             [--out DIR] [--upload]

What it does, per test set:
  1. self check  : slowest queries and their share of total time, memory / CPU heavy queries and slices,
                   parallel efficiency (cpu_s / (seconds * cores)), spill, failures by class, environment flags.
  2. vs baseline : baseline = previous run of the same cluster + test set (auto) or --base.
                   Comparability check (data schema/distribution/scale, build, flags). Per query: time change
                   (>10% and >2s), plan hash change, result fingerprint change (possible wrong result), peak memory
                   change (>25% and >0.5GB), top-slice change.
  3. commits     : when builds differ, umbrella / database / arrow commit ranges, each commit tagged
                   optimizer / executor-vec / storage / other by changed paths, so a plan change points to
                   optimizer commits and a same-plan slowdown points to executor/storage commits.
Output: <out>/<cluster>/<run_id>/analysis.md (local) + copied to the run dir on the host; with --upload
also to /proteus/perf/<report_id>/tpcbench/analysis_<set>.md on the report server.
"""
import argparse, json, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tpcsite

SSH_KEY = tpcsite.get("TPCBENCH_SSH_KEY")
REPORT_HOST = tpcsite.get("TPCBENCH_REPORT_SSH")
REPORT_WEB = tpcsite.get("TPCBENCH_REPORT_WEB")
REPORT_DIR = tpcsite.get("TPCBENCH_REPORT_DIR", "/proteus/perf")
REPORT_KEY = os.path.expanduser("~/.cache/tpc-bench/proteus/tools/report_key")
SUBMODULES = {"database": "database", "contrib/apache-arrow/arrow": "database/contrib/apache-arrow/arrow"}
T_PCT, T_ABS = 0.10, 2.0          # time change threshold
M_PCT, M_ABS = 0.25, 0.5          # memory change threshold (GB)


def sh(cmd, check=False, cwd=None):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
    if check and r.returncode:
        raise RuntimeError(f"{cmd}: {r.stderr.strip()}")
    return r.stdout


def ssh(host, cmd):
    return sh(f"ssh -o BatchMode=yes -i {SSH_KEY} {host} {json.dumps(cmd)}")


def load_run(host, w, cluster, rid, s):
    t = ssh(host, f"cat {w}/clusters/{cluster}/runs/{rid}/{s}/run.json 2>/dev/null")
    if not t.strip():
        return None
    r = json.loads(t)
    for q in r["queries"]:            # queries without resource samples (finalize sets "resources": reason)
        q["sampled"] = "cpu_s" in q
        for k in ("cpu_s", "peak_rss_gb", "read_gb", "write_gb", "host_min_avail_gb"):
            q.setdefault(k, None)
        q.setdefault("slices", {})
    return r


def n(v, fmt="{}"):
    return "-" if v is None else fmt.format(v)


def list_runs(host, w, cluster):
    return sorted(ssh(host, f"ls {w}/clusters/{cluster}/runs 2>/dev/null").split())


def dist_of(run):
    d = run.get("data") or {}
    if d.get("distribution"):
        return d["distribution"]
    # runs before distribution was recorded: infer from schema suffix / tags
    if (d.get("schema") or "").split("_")[0].endswith("rand"):
        return "random"
    return "random?" if run.get("run_id", "") < "20261112_14" else "unknown"


def pipe_of(run):
    """vector.enable_vec_pipeline of the timed run: mkconfig names the pipeline=on config <...>_run_pipe"""
    return "on" if (run.get("config") or "").endswith("_pipe") else "off"


# ---------- self check ----------
def self_check(run):
    out = []
    q = run["queries"]
    ok = [x for x in q if x["status"] == "OK"]
    cores = (run.get("host") or {}).get("cores") or 1
    total = sum(x["seconds"] for x in ok) or 1
    flags = run.get("flags") or []
    t = run["totals"]
    out.append(f"- 结果：{t['ok']}/{t['queries']} 成功，成功查询合计 {t['seconds_ok']} 秒；状态 {run['status']}；"
               f"报告 {REPORT_WEB}/{run.get('report_id')}")
    h = run.get("host") or {}
    out.append(f"- 环境：{h.get('hostname')} {cores} 核 {h.get('mem_gb')}GB；跑前同机其他 postgres 占用 "
               f"{h.get('other_postgres_cores_busy')} 核；libarrow 布局 {(run.get('layout') or {}).get('summary')}；"
               f"数据 {run['data'].get('schema')} 分布={dist_of(run)}；Pipeline={pipe_of(run)}；"
               + (f"并发 {run['concurrency']['streams']} 个流" if run.get("concurrency") else "并发 1 个流串行")
               + f"；每条查询 {run.get('rounds') or 1} 轮（耗时取中位数）")
    cc = run.get("concurrency")
    if cc:
        out.append(f"- **并发**：{cc['streams']} 个流同时跑，整段 {cc['elapsed_s']}s，成功 {cc['ok']}/{cc['executions']} 次执行，"
                   f"吞吐 {cc['queries_per_hour']} 条/小时；整机可用内存最低 {cc['host_min_avail_gb']}GB，CPU 最高 {cc['host_max_cpu_pct']}%；"
                   "各流：" + "，".join(f"流{x['stream']} {x['ok']}/{x['queries']} 成功 {x['elapsed_s']}s" for x in cc["per_stream"])
                   + "（并发时每条查询的资源分不开，下表只有耗时：各流的中位数）")
    if (run.get("rounds") or 1) > 1:
        noisy = [q for q in run["queries"] if q.get("spread") and q["seconds"] and q["spread"] > max(2, 0.1 * q["seconds"])]
        out.append(f"- 多轮波动：{len(noisy)} 条查询的轮间差距超过 10% 且超过 2 秒"
                   + ("：" + "，".join(f"{q['name']} {q['rounds']}" for q in noisy[:8]) if noisy else ""))
    if flags:
        notes = {"other_load": "同机有别人的负载，计时只能参考", "layout_bad": "libarrow 加载地址落在坏区间，个别查询可能慢 ~30%",
                 "crashed": "跑的过程中集群崩溃过", "proteus_failed": "proteus 自身异常退出"}
        out.append("- **标记**：" + "；".join(f"`{f}`（{notes.get(f, '')}）" for f in flags))
    else:
        out.append("- 标记：无（机器干净，计时可信）")

    hn = run.get("hosts_net") or {}
    if len(hn) > 1:
        out.append("- 各机器网络（测试期间，MB/s，平均/峰值）：" + "；".join(
            f"{h} 收 {v['rx_avg_MBs']}/{v['rx_peak_MBs']} 发 {v['tx_avg_MBs']}/{v['tx_peak_MBs']}" for h, v in hn.items()) +
            "（多机的瓶颈通常是网络：峰值接近网卡带宽时，重查询的 Motion 在排队）")
    co = run.get("collectors") or {}
    if co:
        sm = round(sum(v for k, v in co.items() if k.startswith("sysmon")), 2)
        qm = round(sum(v for k, v in co.items() if k.startswith("qmon")), 2)
        nh = len({k.split("@")[1].rsplit("_", 2)[0] for k in co if "@" in k}) + 1
        out.append(f"- 采集器自身开销（{nh} 台合计）：sysmon {sm}s + qmon {qm}s CPU，"
                   f"平均 {co.get('avg_cores')} 核（每台 {cores} 核），不影响计时")

    # failures
    fails = [x for x in q if x["status"] != "OK"]
    if fails:
        out.append("\n**失败的查询**\n")
        out.append("| 查询 | 状态 | 类别 | 错误 |\n|---|---|---|---|")
        for x in fails:
            out.append(f"| {x['name']} | {x['status']} | {classify_err(x.get('error'))} | {(x.get('error') or '')[-160:]} |")

    # slowest
    out.append("\n**最慢的查询（占成功查询总耗时的比例）**\n")
    cl = run.get("cluster") or {}
    segs = (cl.get("segs_per_host") or 1) * len(cl.get("hosts") or [1])
    out.append("| 查询 | 秒 | 占比 | 累计 | 峰值内存GB | CPU秒 | 平均/峰值核数 | 每 segment 核数 | 计划+派发 s | 关键 slice（忙碌区间 s，峰值核，倾斜 mem/cpu） |\n|---|---|---|---|---|---|---|---|---|---|")
    acc = 0
    for x in sorted(ok, key=lambda x: -x["seconds"])[:10]:
        acc += x["seconds"]
        par = x["cpu_s"] / x["seconds"] if x["seconds"] and x["cpu_s"] is not None else None
        out.append(f"| {x['name']} | {x['seconds']} | {x['seconds']/total:.0%} | {acc/total:.0%} | {n(x['peak_rss_gb'])} | "
                   f"{n(x['cpu_s'])} | {n(par, '{:.1f}')}/{n(x.get('cores_peak'))} | {n(par / segs if par is not None else None, '{:.1f}')} | "
                   f"{n(x.get('plan_dispatch_s'))} | {crit_slice(x)} |")
    uns = [x["name"] for x in q if not x["sampled"]]
    if uns:
        out.append(f"\n资源没有采到的查询 {len(uns)} 条（短于 1 秒采样间隔，或采样器异常）：{', '.join(uns)}")

    # memory heavy
    out.append("\n**内存最高的查询**\n")
    out.append("| 查询 | 峰值内存GB | 主机最低可用GB | slice 峰值（前 3） |\n|---|---|---|---|")
    for x in sorted(q, key=lambda x: -(x.get("peak_rss_gb") or 0))[:5]:
        sl = sorted((x.get("slices") or {}).items(), key=lambda kv: -kv[1]["peak_gb"])[:3]
        out.append(f"| {x['name']} | {x['peak_rss_gb']} | {x.get('host_min_avail_gb')} | "
                   + ", ".join(f"{k} {v['peak_gb']}GB/{v['qes']}QE" for k, v in sl) + " |")

    # spill / io
    spill = [x for x in q if (x.get("write_gb") or 0) > 0.05]
    if spill:
        out.append("\n**有写盘（spill）的查询**：" + "，".join(f"{x['name']} {x['write_gb']}GB" for x in spill))
    else:
        out.append("\n**写盘（spill）**：没有查询写盘超过 50MB。")

    # low parallel efficiency long queries
    out.append("\n**异常（B 指标，计时期间采集，不影响性能；没有基线时这些只是线索，不算慢）**\n")
    an = anomalies(run, segs)
    out += [f"- {a}" for a in an] if an else ["- 没有发现异常。"]
    return out


def crit_slice(x):
    k = x.get("longest_busy_slice")
    v = (x.get("slices") or {}).get(k)
    if not v:
        return top_slice(x)
    b = v.get("busy")
    return (f"{k}（{b[0]}–{b[1]}，{v.get('cores_peak')} 核/{v.get('qes')}QE，"
            f"{n(v.get('skew_mem'))}/{n(v.get('skew_cpu'))}）" if b else k)


def anomalies(run, segs):
    """Lightweight per-query anomaly hints from the B metrics (thresholds follow vec-perf-triage step 5)."""
    out = []
    for x in run["queries"]:
        if x["status"] != "OK" or not x["sampled"]:
            continue
        sec = x["seconds"] or 0
        tags = []
        if x["cpu_s"] is not None and sec >= 5 and x["cpu_s"] / sec < segs:
            tags.append(f"平均只用 {x['cpu_s']/sec:.1f} 核（< segment 数 {segs}），多半在等待")
        pd = x.get("plan_dispatch_s")
        if pd is not None and pd >= 1 and sec and pd / sec >= 0.3:
            tags.append(f"生成计划+派发用了 {pd}s（占 {pd/sec:.0%}），优化器耗时")
        for k, v in (x.get("slices") or {}).items():
            if k == "slice?" or sec < 3:     # unlabeled QEs mix several slices; 1s sampling is too coarse below 3s
                continue
            sm, mx = v.get("skew_mem"), v.get("qe_peak_gb_max") or 0
            if sm and sm > 1.5 and mx - mx / sm > 0.3:
                tags.append(f"{k} 内存倾斜 {sm}（最大 QE {mx}GB）")
            sc = v.get("skew_cpu")
            if sc and sc > 1.5 and v.get("cpu_s", 0) > 5:
                tags.append(f"{k} CPU 倾斜 {sc}")
            if sec >= 5 and v.get("busy_s", 0) >= 0.5 * sec and v.get("cores_peak") is not None \
                    and v["cores_peak"] < 1.2 * v.get("qes", 1) and v.get("cpu_s", 0) > 0.3 * (x["cpu_s"] or 0):
                tags.append(f"{k} 忙了 {v['busy_s']}s、峰值只有 {v['cores_peak']} 核/{v['qes']}QE（每个 QE 约 1 核：单线程瓶颈）")
        if (x.get("write_gb") or 0) > 0.05:
            tags.append(f"写盘 {x['write_gb']}GB（spill）")
        if x.get("mem_shape") == "sawtooth":
            tags.append("内存锯齿（spill 或按批释放）")
        if tags:
            out.append(f"{x['name']}（{sec}s）：" + "；".join(tags))
    return out


def classify_err(e):
    if not e:
        return "未完成/无错误信息"
    e = e.lower()
    for k, v in [("canceling statement due to user request", "被取消"), ("statement timeout", "超时"),
                 ("out of memory", "内存不足"), ("vmem", "内存不足(vmem)"), ("terminated by signal", "崩溃"),
                 ("server closed the connection", "崩溃/断连"), ("segment", "segment 错误"), ("syntax", "SQL 语法"),
                 ("does not exist", "对象不存在")]:
        if k in e:
            return v
    return "其他"


def top_slice(x):
    sl = x.get("slices") or {}
    if not sl:
        return ""
    k, v = max(sl.items(), key=lambda kv: kv[1]["cpu_s"])
    return f"{k} {v['cpu_s']}cpu_s/{v['peak_gb']}GB"


# ---------- comparison ----------
def comparability(cur, base):
    issues = []
    cd, bd = cur.get("data") or {}, base.get("data") or {}
    if dist_of(cur) != dist_of(base):
        issues.append(f"数据分布不同：本次 {dist_of(cur)}，基线 {dist_of(base)}（计划和耗时都会变，差异不能归到提交上）")
    if cd.get("scale") != bd.get("scale"):
        issues.append(f"规模不同：{cd.get('scale')} vs {bd.get('scale')}")
    if cd.get("loaded_at") != bd.get("loaded_at"):
        issues.append(f"数据是重新导入的（{bd.get('loaded_at')} → {cd.get('loaded_at')}），统计信息可能不同")
    for r, n in ((cur, "本次"), (base, "基线")):
        f = set(r.get("flags") or []) & {"other_load", "layout_bad", "crashed"}
        if f:
            issues.append(f"{n}带标记 {sorted(f)}，计时只能参考")
    if pipe_of(cur) != pipe_of(base):
        issues.append(f"Pipeline 不同：本次 {pipe_of(cur)}，基线 {pipe_of(base)}（执行方式不同，差异不能归到提交上）")
    if cur["config"] != base["config"]:
        issues.append(f"配置名不同：{cur['config']} vs {base['config']}")
    return issues


def attribution_ok(run):
    """Resource numbers are trustworthy only with the fork-time attribution (finalize >= 2026-11-12 15:10):
    every attributed query has session_start_lag_s, all >= 0 (the session starts after proteus stamps the start)."""
    lags = [q.get("session_start_lag_s") for q in run["queries"] if q["sampled"]]
    return bool(lags) and all(v is not None and v >= -0.06 for v in lags)


def compare(cur, base):
    out = []
    mem_ok = attribution_ok(cur) and attribution_ok(base)
    if not mem_ok:
        out.append("- 资源（内存、CPU）不做比较：" + ("基线" if attribution_ok(cur) else "本次") +
                   "的资源归属是旧算法算的，相邻查询可能被串错；只比较耗时、计划和结果。")
    bq = {x["name"]: x for x in base["queries"]}
    rows, plan_changed, res_changed, mem_rows, status_rows, slow = [], [], [], [], [], []
    cur_sum = base_sum = 0
    for x in cur["queries"]:
        b = bq.get(x["name"])
        if not b:
            continue
        if x["status"] != b["status"]:
            status_rows.append(f"| {x['name']} | {b['status']} → {x['status']} | {classify_err(x.get('error')) if x['status']!='OK' else ''} |")
        if x["status"] != "OK" or b["status"] != "OK":
            continue
        cur_sum += x["seconds"]; base_sum += b["seconds"]
        d = x["seconds"] - b["seconds"]
        pc = x.get("plan_shape_hash") != b.get("plan_shape_hash")
        noise = max(x.get("spread") or 0, b.get("spread") or 0)     # multi-round runs: the gap must beat the spread
        if abs(d) > T_ABS and b["seconds"] and abs(d) / b["seconds"] > T_PCT and abs(d) > noise:
            if d > 0:
                slow.append(dict(set=cur["test_set"], name=x["name"], file_id=x["file_id"], base_s=b["seconds"],
                                 cur_s=x["seconds"], delta_s=d, delta_pct=round(d / b["seconds"], 3), plan_changed=pc,
                                 base_plan=b.get("plan_shape_hash"), cur_plan=x.get("plan_shape_hash"),
                                 slice_delta=slice_delta(x, b) if mem_ok else None))
            rows.append((d, f"| {x['name']} | {b['seconds']} | {x['seconds']} | {d:+} ({d/b['seconds']:+.0%}) | "
                            f"{'**变了**' if pc else '同'} | " +
                            (f"{n(b['peak_rss_gb'])} → {n(x['peak_rss_gb'])} | {n(b['cpu_s'])} → {n(x['cpu_s'])} | {slice_delta(x, b)} |"
                             if mem_ok else "- | - | - |")))
        if pc:
            plan_changed.append(x["name"])
        if x.get("sha_sorted") and b.get("sha_sorted") and x["sha_sorted"] != b["sha_sorted"]:
            res_changed.append(f"{x['name']}（行数 {b.get('rows')} → {x.get('rows')}）")
        if not mem_ok or x["peak_rss_gb"] is None or b["peak_rss_gb"] is None:
            continue
        dm = x["peak_rss_gb"] - b["peak_rss_gb"]
        if abs(dm) > M_ABS and b["peak_rss_gb"] and abs(dm) / b["peak_rss_gb"] > M_PCT:
            mem_rows.append(f"{x['name']} {b['peak_rss_gb']}→{x['peak_rss_gb']}GB")
    if base_sum:
        out.append(f"- 两边都成功的查询合计：基线 {base_sum}s → 本次 {cur_sum}s（{(cur_sum-base_sum)/base_sum:+.1%}）")
    if status_rows:
        out.append("\n**状态变化**\n\n| 查询 | 状态 | 类别 |\n|---|---|---|")
        out += status_rows
        out.append("")
    if rows:
        out.append(f"\n**耗时变化超过 ±{T_PCT:.0%} 且超过 {T_ABS:.0f} 秒的查询**（慢的在前）\n")
        out.append("| 查询 | 基线秒 | 本次秒 | 变化 | 计划 | 峰值内存GB | CPU秒 | 变化最大的 slice |\n|---|---|---|---|---|---|---|---|")
        out += [r for _, r in sorted(rows, key=lambda r: -r[0])]
        out.append("")
    else:
        out.append(f"- 没有查询的耗时变化同时超过 ±{T_PCT:.0%} 和 {T_ABS:.0f} 秒。")
    out.append(f"- 计划形状变化：{len(plan_changed)} 条" + (f"（{', '.join(plan_changed)}）" if plan_changed else ""))
    if res_changed:
        out.append(f"- **结果指纹变化：{len(res_changed)} 条** — {', '.join(res_changed)}。"
                   "同一份数据下结果变了，可能是正确性问题，要优先核对；如果数据重新导入或分布方式变了，"
                   "带 LIMIT 而排序键有并列的查询也可能合法地变化。")
    else:
        out.append("- 结果指纹：两边都成功的查询结果全部一致。")
    if mem_rows:
        out.append(f"- 峰值内存变化超过 ±{M_PCT:.0%} 且超过 {M_ABS}GB：{', '.join(mem_rows)}")
    return out, bool(plan_changed), slow


def slice_delta(x, b):
    xs, bs = x.get("slices") or {}, b.get("slices") or {}
    best = None
    for k in set(xs) | set(bs):
        d = (xs.get(k, {}).get("cpu_s") or 0) - (bs.get(k, {}).get("cpu_s") or 0)
        if best is None or abs(d) > abs(best[1]):
            best = (k, d)
    return f"{best[0]} cpu_s {best[1]:+.1f}" if best else ""


# ---------- commits ----------
TEST_PATH = re.compile(r"(^|/)(test|tests|regress|isolation2?|expected|output|behave|t)/|_test\.|\.out$|\.source$|\.ans$")


def area(paths):
    code = [p for p in paths if not TEST_PATH.search(p)]
    if not code:
        return ["test"] if paths else ["other"]
    s = " ".join(code)
    tags = []
    if re.search(r"optimizer/|gporca|/planner|plan/|/path/|/prep/|costsize|cdbplan|orca", s):
        tags.append("optimizer")
    if re.search(r"vectoriz|executor/|/exec|cpp/src/arrow|acero|compute/|nodeHash|motion|interconnect|cdb/dispatcher", s):
        tags.append("executor-vec")
    if re.search(r"contrib/pax|/storage/|parquet|access/(heap|aocs|appendonly|table|common)|/orc/", s):
        tags.append("storage")
    return tags or ["other"]


def ensure(repo, sha):
    if sh(f"git -C {repo} cat-file -t {sha} 2>/dev/null").strip() == "commit":
        return True
    sh(f"git -C {repo} fetch -q origin {sha} 2>/dev/null")
    return sh(f"git -C {repo} cat-file -t {sha} 2>/dev/null").strip() == "commit"


def commit_range(umb, cur, base):
    out = []
    cb, bb = cur["build"], base["build"]
    if cb.get("pipeline") == bb.get("pipeline"):
        out.append(f"- 两次是同一个构建（{cb.get('pipeline')}），差异与提交无关，应归到环境、数据或波动。")
        return out
    out.append(f"- 构建 {bb.get('pipeline')} → {cb.get('pipeline')}；umbrella {bb.get('umbrella_sha','')[:10]} → {cb.get('umbrella_sha','')[:10]}")
    for name, path in SUBMODULES.items():
        a, b = (bb.get("commits") or {}).get(name), (cb.get("commits") or {}).get(name)
        if not a or not b or a == b:
            out.append(f"- {name}：{'未变化' if a == b else '缺少提交信息'}")
            continue
        repo = os.path.join(umb, path)
        if not (ensure(repo, a) and ensure(repo, b)):
            out.append(f"- {name} {a[:10]}..{b[:10]}：本机仓库 {repo} 取不到这两个提交，无法展开")
            continue
        note = ""
        if subprocess.run(f"git -C {repo} merge-base --is-ancestor {a} {b}", shell=True).returncode != 0:
            if subprocess.run(f"git -C {repo} merge-base --is-ancestor {b} {a}", shell=True).returncode == 0:
                note = "（注意：本次构建比基线**更旧**，下面列的是基线多出来的提交）"
                a, b = b, a
            else:
                mb = sh(f"git -C {repo} merge-base {a} {b}").strip()
                note = f"（注意：两边不在同一条线上，从共同祖先 {mb[:10]} 算起；基线一侧另有 " \
                       f"{len(sh(f'git -C {repo} rev-list {mb}..{a}').split())} 个提交不在本次构建里）"
                a = mb
        log = sh(f"git -C {repo} log --no-merges --format='%h%x09%an%x09%s' {a}..{b}").strip().splitlines()
        rows, cnt = [], {}
        for line in log:
            h, au, subj = (line.split("\t") + ["", ""])[:3]
            files = sh(f"git -C {repo} show --name-only --format= {h}").split() if len(log) <= 400 else []
            tags = area(files) if files else ["?"]
            for t in tags:
                cnt[t] = cnt.get(t, 0) + 1
            rows.append((tags, f"| {h} | {au} | {subj[:90]} | {','.join(tags)} |"))
        out.append(f"\n**{name} {a[:10]}..{b[:10]}：{len(log)} 个提交**{note}\n")
        if len(log) > 400:
            out.append(f"- 提交太多（>{400}），没有逐个分类；两次构建相隔太远，建议先在中间的流水线上补跑，缩小范围。\n")
        else:
            out.append("- 按领域：" + "，".join(f"{k} {v}" for k, v in sorted(cnt.items(), key=lambda kv: -kv[1])) + "\n")
        # perf-relevant first, test-only last
        order = {"optimizer": 0, "executor-vec": 0, "storage": 0, "other": 1, "?": 1, "test": 2}
        rows.sort(key=lambda r: min(order.get(t, 1) for t in r[0]))
        out.append("| 提交 | 作者 | 标题 | 涉及 |\n|---|---|---|---|")
        out += [r for _, r in rows[:80]]
        if len(rows) > 80:
            out.append(f"| … | | 还有 {len(rows)-80} 个（多为 other/test） | |")
    return out


TOP_N = 3     # phase 2 deep-dives at most this many slow queries (user decision 2026-11-12)


def comparable_for_slow(cur, base):
    """Slow detection only between runs on the same data and without foreign load (layout_bad is re-checked in phase 2)."""
    cd, bd = cur.get("data") or {}, base.get("data") or {}
    why = []
    if dist_of(cur) != dist_of(base) or cd.get("scale") != bd.get("scale") or cd.get("schema") != bd.get("schema"):
        why.append("数据不同（分布/规模/schema）")
    if pipe_of(cur) != pipe_of(base):
        why.append(f"Pipeline 不同（本次 {pipe_of(cur)}，基线 {pipe_of(base)}）")
    sc = lambda r: (r.get("concurrency") or {}).get("streams") or 1
    if sc(cur) != sc(base):
        why.append(f"并发流数不同（本次 {sc(cur)}，基线 {sc(base)}）")
    for r, nm in ((cur, "本次"), (base, "基线")):
        if "other_load" in (r.get("flags") or []) or "crashed" in (r.get("flags") or []):
            why.append(f"{nm}有 other_load/crashed 标记")
    return why


def pick_base(a, runs, s, cur):
    if a.base in ("none", ""):
        return None
    if a.base != "auto":                     # RUN_ID or CLUSTER:RUN_ID (a run of another cluster generation)
        cname, rid = a.base.split(":") if ":" in a.base else (a.cluster, a.base)
        return load_run(a.host, a.workdir, cname, rid, s)
    first = None
    # this cluster first, then the previous generation (a catalog bump creates a new cluster: see nightly.py)
    gens = [(a.cluster, [r for r in runs if r < a.run])]
    prev = sh(f"ssh -o BatchMode=yes -i {SSH_KEY} {a.host} cat {a.workdir}/clusters/{a.cluster}.prev 2>/dev/null").strip()
    if prev:
        gens.append((prev, list_runs(a.host, a.workdir, prev)))
    for cname, rs in gens:
        for r in reversed(rs):
            b = load_run(a.host, a.workdir, cname, r, s)
            if not b:
                continue
            first = first or b
            if not comparable_for_slow(cur, b):
                return b                   # latest comparable run
    return first


def upload_report(a, od, fname, rid, dest):
    key = os.path.expanduser("~/.tpc-bench/report_key")      # ssh refuses a group/world-readable key
    if not os.path.exists(key):
        sh(f"install -m 600 {REPORT_KEY} {key}")
    o = "-o BatchMode=yes -o StrictHostKeyChecking=no"
    r = sh(f"ssh {o} -i {key} {REPORT_HOST} 'mkdir -p {REPORT_DIR}/{rid}/tpcbench' 2>/dev/null && "
           f"scp -q {o} -i {key} {od}/{fname} {REPORT_HOST}:{REPORT_DIR}/{rid}/tpcbench/{dest} && echo ok")
    print(f"upload {fname} -> {REPORT_DIR}/{rid}/tpcbench/{dest}: {r.strip() or 'FAILED'}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True); ap.add_argument("--workdir", required=True)
    ap.add_argument("--cluster", required=True); ap.add_argument("--run", required=True)
    ap.add_argument("--set", default="h,ds"); ap.add_argument("--base", default="auto")
    ap.add_argument("--umbrella", default=tpcsite.get("TPCBENCH_UMBRELLA_DIR"))
    ap.add_argument("--out", default=os.path.expanduser("~/.tpc-bench/analysis"))
    ap.add_argument("--upload", action="store_true")
    a = ap.parse_args()
    runs = list_runs(a.host, a.workdir, a.cluster)
    od = os.path.join(a.out, a.cluster, a.run); os.makedirs(od, exist_ok=True)
    r1 = [f"# 报告① 本次结果：{a.cluster} / {a.run}\n"]
    r2 = [f"# 报告② 慢查询判定：{a.cluster} / {a.run}\n",
          f"判定规则：和基线（同集群、同测试集、同一份数据、没有 other_load/crashed 标记的上一次运行）逐条比较，"
          f"耗时同时超过 +{T_PCT:.0%} 和 +{T_ABS:.0f} 秒算慢；按多花的秒数排序，最多取前 {TOP_N} 条进入阶段 2。\n"]
    all_slow, sets_info, report_ids = [], {}, {}
    for s in a.set.split(","):
        cur = load_run(a.host, a.workdir, a.cluster, a.run, s)
        if not cur:
            r1.append(f"## tpc-{s}\n\n没有 run.json（这个测试集没跑或 finalize 失败）。\n"); continue
        report_ids[s] = cur.get("report_id")
        r1.append(f"## {cur['test_set']}（报告 {cur.get('report_id')}，构建 {cur['build'].get('pipeline')}）\n")
        r1 += self_check(cur)
        r1.append("")
        base = pick_base(a, runs, s, cur)
        r2.append(f"## {cur['test_set']}\n")
        info = dict(cur_run=a.run, cur_build=cur["build"].get("pipeline"), cur_commits=cur["build"].get("commits"),
                    cur_umbrella=cur["build"].get("umbrella_sha"), report_id=cur.get("report_id"))
        if not base:
            r2.append("- 没有可比较的历史运行，只能看报告①里的异常线索，不判定慢查询。\n")
            sets_info[s] = dict(info, base_run=None); continue
        info.update(base_run=base["run_id"], base_cluster=(base.get("cluster") or {}).get("name"),
                    base_build=base["build"].get("pipeline"),
                    base_commits=base["build"].get("commits"), base_umbrella=base["build"].get("umbrella_sha"),
                    base_report_id=base.get("report_id"))
        sets_info[s] = info
        r2.append(f"- 基线：{base['run_id']}（报告 {base.get('report_id')}，构建 {base['build'].get('pipeline')}，分布 {dist_of(base)}）")
        iss = comparability(cur, base)
        if iss:
            r2.append("- **可比性问题**：")
            r2 += [f"  - {i}" for i in iss]
        why = comparable_for_slow(cur, base)
        c, plan_changed, slow = compare(cur, base)
        r2 += c
        if why:
            r2.append(f"- **不判定慢查询**：{'；'.join(why)}。上面的差异只作参考。")
        else:
            all_slow += slow
        r2.append("\n### 提交范围\n")
        r2 += commit_range(a.umbrella, cur, base)
        r2.append("")
    all_slow.sort(key=lambda x: -x["delta_s"])
    top = all_slow[:TOP_N]
    r2.append("## 结论\n")
    if not all_slow:
        r2.append("- **没有慢查询**，不进入阶段 2。")
    else:
        r2.append(f"- 慢查询 {len(all_slow)} 条，合计多花 {sum(x['delta_s'] for x in all_slow)} 秒；"
                  f"进入阶段 2 的前 {len(top)} 条：")
        r2.append("\n| 查询 | 基线秒 | 本次秒 | 多花 | 计划 | 变化最大的 slice |\n|---|---|---|---|---|---|")
        for x in top:
            r2.append(f"| {x['name']} | {x['base_s']} | {x['cur_s']} | +{x['delta_s']}s ({x['delta_pct']:+.0%}) | "
                      f"{'变了' if x['plan_changed'] else '同'} | {x['slice_delta'] or '-'} |")
        if len(all_slow) > TOP_N:
            r2.append(f"\n其余 {len(all_slow) - TOP_N} 条：" + "，".join(f"{x['name']} +{x['delta_s']}s" for x in all_slow[TOP_N:]))
    for fname, body in (("report1_results.md", r1), ("report2_slow.md", r2)):
        with open(os.path.join(od, fname), "w") as f:
            f.write("\n".join(body) + "\n")
    slow_json = dict(cluster=a.cluster, run=a.run, host=a.host, workdir=a.workdir, sets=sets_info,
                     slow_total=len(all_slow), top=top, others=all_slow[TOP_N:])
    with open(os.path.join(od, "slow.json"), "w") as f:
        json.dump(slow_json, f, ensure_ascii=False, indent=1)
    rdir = f"{a.workdir}/clusters/{a.cluster}/runs/{a.run}"
    sh(f"scp -q -i {SSH_KEY} {od}/report1_results.md {od}/report2_slow.md {od}/slow.json {a.host}:{rdir}/")
    if a.upload:
        for s, rid in report_ids.items():
            if rid:
                for fname in ("report1_results.md", "report2_slow.md"):
                    upload_report(a, od, fname, rid, fname)
    print(od)


if __name__ == "__main__":
    main()
