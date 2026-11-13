#!/usr/bin/env python3
"""triage_html.py <run_dir> <out.html> [--analysis triage_analysis.json] [--subtitle "..."]

"最慢 3 条 SQL 分析" page in the format the user approved on 2026-11-13. <run_dir> is a local copy of a run that holds
<set>/run.json (tpc-bench finalize output), e.g. the analysis dir or a report_html.py --stage dir.

Layout, top to bottom:
  - "一眼看重点" red box: key_points from the analysis (before triage: auto points from the run's own numbers)
  - colour legend
  - table of the 3 slowest successful queries per test set
  - one card per query:
      title with the time in large red digits and its share of the set's total
      blue verdict box: 结论 / 可省 / 建议 / 置信度
      KPI tiles (red: memory >= 200GB, host avail < 50GB, spill >= 50GB; orange: memory >= 100GB, spill >= 10GB)
      automatic flags (高内存, 整机内存接近耗尽, spill, 内存倾斜 >= 1.5, 单线程瓶颈 of the critical slice)
      triage fields: 计划 DAG 与关键路径 / 资源体检 / 时间花在哪 / 内存花在哪 / 行数：估计 vs 实际 / 归类 / 因果链 / 证据
      slice table sorted by memory, the critical-path slice row highlighted, memory >= 100GB and skew >= 1.5 in red
  - summary table: 主要原因 / 归类 / 可省多少 / 置信度 / 建议
Every field that has no data yet is shown as grey italic "（待 triage 数据）".

triage_analysis.json (written by claude -p from the triage data, see nightly.report3_and_sync):
{ "key_points": ["...html...", ...],
  "queries": { "<set>:<file_id>": { "verdict": "", "saving": "", "advice": "", "confidence": "已证实|很可能|推测",
      "dag": "", "use": "", "time": "", "memory": "", "rows": "", "category": "", "chain": "", "evidence": ["", ""],
      "cause_short": "" } } }
"""
import argparse, html, json, os

CSS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "report_html.css")
EXTRA_CSS = """
.card{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:14px 18px;display:grid;gap:10px}
.card h3{margin:0;display:flex;flex-wrap:wrap;gap:6px 10px;align-items:baseline}
.card h3 .sec{font-family:var(--mono);font-size:22px;color:var(--bad)}
.verdict{border:2px solid var(--accent);border-radius:6px;padding:8px 12px;display:grid;grid-template-columns:auto 1fr;gap:4px 12px;font-size:14px}
.verdict b{color:var(--accent)}
.kpis{display:flex;flex-wrap:wrap;gap:8px}
.kpi{border:1px solid var(--line);border-radius:6px;padding:4px 10px;font-size:12px;color:var(--muted);min-width:7em}
.kpi b{display:block;font-family:var(--mono);font-size:17px;color:var(--fg)}
.kpi.hot{border-color:var(--bad);background:var(--badbg)} .kpi.hot b{color:var(--bad)}
.kpi.warm{border-color:var(--warn);background:var(--warnbg)} .kpi.warm b{color:var(--warn)}
.flags{display:flex;flex-wrap:wrap;gap:6px}
.flag{font-size:12px;padding:1px 8px;border-radius:9px;background:var(--bad);color:var(--panel);font-weight:500}
.flag.w{background:var(--warn)}
.kv{display:grid;grid-template-columns:9em 1fr;gap:4px 12px;font-size:14px}
.kv dt{color:var(--muted)} .kv dd{margin:0;min-width:0}
.todo{color:var(--na);font-style:italic}
tr.crit td{background:var(--warnbg);font-weight:600}
td.hi{color:var(--bad);font-weight:700}
.key{background:var(--panel);border:2px solid var(--bad);border-radius:6px;padding:10px 16px}
.key li{margin:2px 0}
@media (max-width:600px){.kv{grid-template-columns:1fr}.verdict{grid-template-columns:1fr}}
"""
TODO = '<span class="todo">（待 triage 数据）</span>'
SETS = (("h", "TPC-H"), ("ds", "TPC-DS"))


def qn(q):
    return q["name"].rsplit(".", 1)[1]


def top3(run):
    ok = [q for q in run["queries"] if q["status"] == "OK"]
    return sorted(ok, key=lambda q: -q["seconds"])[:3], sum(q["seconds"] for q in ok) or 1


def flags_of(q):
    f = []
    if (q.get("peak_rss_gb") or 0) >= 200:
        f.append(("高内存", ""))
    if (q.get("host_min_avail_gb") or 999) < 50:
        f.append(("整机内存接近耗尽", ""))
    if (q.get("write_gb") or 0) >= 10:
        f.append((f"spill {q['write_gb']:.0f}GB", "w"))
    for k, v in (q.get("slices") or {}).items():
        if k != "QD" and (v.get("skew_mem") or 0) >= 1.5 and (v.get("qe_peak_gb_max") or 0) >= 1:
            f.append((f"{k} 内存倾斜 {v['skew_mem']}", "w"))
    crit = q.get("longest_busy_slice")
    cs = (q.get("slices") or {}).get(crit) or {}
    if cs.get("cores_peak") and cs["cores_peak"] <= cs["qes"] * 1.4 and (cs.get("busy_s") or 0) >= 0.5 * q["seconds"]:
        f.append((f"{crit} 单线程瓶颈（{cs['qes']} 个 QE 只用 {cs['cores_peak']} 核）", ""))
    return f


def auto_points(tops):
    qs = [q for t, _ in tops.values() for q in t]
    if not qs:
        return []
    pts = []
    big = [q for q in qs if (q.get("peak_rss_gb") or 0) >= 150]
    if big:
        m = max(qs, key=lambda q: q.get("peak_rss_gb") or 0)
        pts.append(f'<b style="color:var(--bad)">内存</b>：{len(qs)} 条里有 {len(big)} 条峰值超过 150GB，最高 {m["name"]} {m["peak_rss_gb"]}GB'
                   f'（整机可用内存最低剩 {m.get("host_min_avail_gb")}GB）。')
    sp = [q for q in qs if (q.get("write_gb") or 0) >= 10]
    if sp:
        pts.append('<b style="color:var(--bad)">spill</b>：' + "，".join(f'{q["name"]} 写盘 {q["write_gb"]:.0f}GB' for q in sp) + "。")
    st = [q for q in qs if any("单线程" in t for t, _ in flags_of(q))]
    if st:
        pts.append(f'<b style="color:var(--bad)">单线程瓶颈</b>：{len(st)} 条的关键路径 slice 每个 QE 约只用 1 个核。')
    pts.append(f"主要原因、可省多少、优化建议：{TODO}")
    return pts


def card(s, q, tot, an):
    a = an or {}
    g = lambda k: a.get(k) or TODO
    sl = sorted((q.get("slices") or {}).items(), key=lambda kv: -(kv[1].get("peak_gb") or 0))
    crit = q.get("longest_busy_slice")
    cs = (q.get("slices") or {}).get(crit) or {}
    rows = ""
    for k, v in sl[:5]:
        hi = lambda x, t: f'<td class="hi">{x}</td>' if x and x >= t else f"<td>{x}</td>"
        rows += (f"<tr{' class=\"crit\"' if k == crit else ''}><td>{k}{' ← 关键路径' if k == crit else ''}</td><td>{v.get('qes')}</td>"
                 f"{hi(v.get('peak_gb'), 100)}<td>{(v.get('cpu_s') or 0):.0f}</td><td>{(v.get('busy') or ['', ''])[0]}–{(v.get('busy') or ['', ''])[1]} s</td>"
                 f"<td>{v.get('cores_peak')}</td>{hi(v.get('skew_mem'), 1.5)}{hi(v.get('skew_cpu'), 1.5)}</tr>")
    lv = lambda v, a_, b_: "hot" if (v or 0) >= a_ else ("warm" if (v or 0) >= b_ else "")
    kpi = lambda label, val, c="": f'<div class="kpi {c}"><b>{val}</b>{label}</div>'
    av = q.get("host_min_avail_gb")
    name = ("TPC-H" if s == "h" else "TPC-DS") + f" Q{qn(q)}"
    ev = a.get("evidence") or []
    mem = (q.get("peak_rss_gb") or 0) >= 50
    return f"""<div class="card">
<h3><span>{name}</span><span class="sec">{q['seconds']} s</span><span class="note">占本测试集总耗时 {q['seconds'] / tot * 100:.0f}%</span></h3>
<div class="verdict"><b>结论</b><span>{g('verdict')}</span><b>可省</b><span>{g('saving')}</span><b>建议</b><span>{g('advice')}</span><b>置信度</b><span>{g('confidence')}</span></div>
<div class="kpis">{kpi('峰值内存 GB', q.get('peak_rss_gb'), lv(q.get('peak_rss_gb'), 200, 100))}{kpi('整机最低可用 GB', av, 'hot' if av is not None and av < 50 else '')}{kpi('CPU 核·秒', f"{(q.get('cpu_s') or 0):.0f}")}{kpi('峰值核数', q.get('cores_peak'))}{kpi('spill GB', q.get('write_gb'), lv(q.get('write_gb'), 50, 10))}{kpi('读盘 GB', q.get('read_gb'))}</div>
<div class="flags">{''.join(f'<span class="flag {c}">{html.escape(t)}</span>' for t, c in flags_of(q)) or '<span class="note">没有异常标记</span>'}</div>
<dl class="kv">
<dt>计划 DAG 与关键路径</dt><dd>关键路径上的 slice：<b>{crit}</b>（忙碌 {(cs.get('busy') or ['', ''])[0]}–{(cs.get('busy') or ['', ''])[1]} s）。{g('dag')}</dd>
<dt>资源体检</dt><dd>{g('use')}</dd>
<dt>时间花在哪</dt><dd>{g('time')}</dd>
<dt>内存花在哪</dt><dd>{g('memory') if mem else '峰值低于 50GB，不做 memattr'}</dd>
<dt>行数：估计 vs 实际</dt><dd>{g('rows')}</dd>
<dt>归类</dt><dd>{g('category')}</dd>
<dt>因果链</dt><dd>{g('chain')}</dd>
<dt>证据</dt><dd>① {ev[0] if len(ev) > 0 else TODO}<br>② {ev[1] if len(ev) > 1 else TODO}{''.join(f'<br>{chr(9314 + i)} {e}' for i, e in enumerate(ev[2:]))}</dd>
</dl>
<div class="tbl"><table class="mini"><thead><tr><th>slice（按内存排序）</th><th>QE</th><th>内存峰值 GB</th><th>CPU 核·秒</th><th>忙碌区间</th><th>峰值核数</th><th>内存倾斜</th><th>CPU 倾斜</th></tr></thead><tbody>{rows}</tbody></table></div>
</div>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir"); ap.add_argument("out")
    ap.add_argument("--analysis", default=None); ap.add_argument("--subtitle", default="")
    a = ap.parse_args()
    an = json.load(open(a.analysis)) if a.analysis and os.path.exists(a.analysis) else {}
    aq = an.get("queries") or {}
    tops = {}
    for s, _ in SETS:
        p = os.path.join(a.run_dir, s, "run.json")
        if os.path.exists(p):
            tops[s] = top3(json.load(open(p)))
    tbl, body, summ = [], [], []
    for s, name in SETS:
        if s not in tops:
            continue
        t, tot = tops[s]
        for q in t:
            x = aq.get(f"{s}:{q['file_id']}") or {}
            hi = lambda v, th: f'<td class="hi">{v}</td>' if (v or 0) >= th else f"<td>{v}</td>"
            tbl.append(f"<tr><td>{name}</td><td><b>Q{qn(q)}</b></td><td><b>{q['seconds']}</b></td><td>{q['seconds'] / tot * 100:.0f}%</td>"
                       f"{hi(q.get('peak_rss_gb'), 200)}<td>{(q.get('cpu_s') or 0):.0f}</td>{hi(q.get('write_gb'), 10)}"
                       f"<td>{q.get('longest_busy_slice')}</td><td>{x.get('cause_short') or TODO}</td></tr>")
            summ.append(f"<tr><td>{name} Q{qn(q)}</td><td>{x.get('cause_short') or TODO}</td><td>{x.get('category') or TODO}</td>"
                        f"<td>{x.get('saving') or TODO}</td><td>{x.get('confidence') or TODO}</td><td>{x.get('advice') or TODO}</td></tr>")
        body.append(f"<h3>{name}</h3>" + "".join(card(s, q, tot, aq.get(f"{s}:{q['file_id']}")) for q in t))
    pts = an.get("key_points") or auto_points(tops)
    page = f"""<title>最慢 SQL 分析</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&family=JetBrains+Mono:wght@400;600&display=swap">
<style>{open(CSS_FILE).read()}{EXTRA_CSS}</style>
<div class="wrap">
<header><h1>最慢 3 条 SQL 分析</h1><p class="sub">{html.escape(a.subtitle)}</p></header>
<div class="key"><b>一眼看重点</b><ul>{''.join(f'<li>{p}</li>' for p in pts)}</ul></div>
<p class="note">颜色：<b style="color:var(--bad)">红</b> = 优先关注（内存 ≥200GB、整机可用 &lt;50GB、spill ≥50GB、倾斜 ≥1.5、单线程瓶颈）；<b style="color:var(--warn)">橙</b> = 留意（内存 ≥100GB、spill ≥10GB）；slice 表橙底行 = 关键路径；灰色斜体 = 还没有数据。</p>
<section><h2>1. 最慢的 3 条（每个测试集）</h2><div class="tbl"><table><thead><tr><th>测试集</th><th>查询</th><th>耗时 s</th><th>占比</th><th>峰值内存 GB</th><th>CPU 核·秒</th><th>spill GB</th><th>关键 slice</th><th>主要原因</th></tr></thead><tbody>{''.join(tbl)}</tbody></table></div></section>
<section><h2>2. 逐条分析（vec-perf-triage）</h2>{''.join(body)}</section>
<section><h2>3. 汇总</h2><div class="tbl"><table><thead><tr><th>查询</th><th>主要原因</th><th>归类</th><th>可省多少（估算）</th><th>置信度</th><th>建议</th></tr></thead><tbody>{''.join(summ)}</tbody></table></div></section>
</div>"""
    open(a.out, "w").write(page)
    print(a.out, len(page))


if __name__ == "__main__":
    main()
