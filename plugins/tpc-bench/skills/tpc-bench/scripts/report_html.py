#!/usr/bin/env python3
"""report_html.py <spec.json> <out.html> -- the formal comparison report (HTML, one self-contained page).

Layout (user's required structure, 2026-11-13):
  1 summary  2 test configuration matrix (one column per run: hosts x segs, build, distribution, vectorization,
  pipeline, concurrency, rounds, GUCs, query seed, layout, time, report ids)  3 method  4 totals (one small table
  per comparison)  5.. one section per comparison, single-host comparisons first: per-query tables for TPC-H and
  TPC-DS (slower / failed rows red, faster green, different SQL grey), every row expands to the SQL of both runs,
  both EXPLAIN plans side by side with the differing lines highlighted, and per-slice resources of both runs; then
  the analysis fragment for that comparison (root cause, evidence, confidence) and the resource table of the slow
  queries  last: scenarios not covered, next steps.

spec.json:
{ "title": "...", "subtitle": "...", "summary_html": "<ul>..</ul>", "method_extra_html": "", "gaps_html": "", "next_html": "",
  "runs": { "<key>": { "label": "新单机", "dir": "<local staged dir>", "config": {"机器": "56", ...} } },
  "comparisons": [ { "title": "单机：新构建 vs 旧构建", "base": "old", "cur": "new", "note_html": "",
                     "analysis_html_file": "a.html" } ] }
A staged run dir holds <set>/run.json (tpc-bench finalize output; a legacy run may have only name/seconds/status),
<set>/queries/<file>.sql and <set>/plans/<file>.plan (missing plans are shown as missing).
stage() copies them from a tpc-bench run on the coordinator:  report_html.py --stage <ssh> <W> <cluster> <rid> <dir>
"""
import difflib, html, json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tpcsite
KEY = tpcsite.get("TPCBENCH_SSH_KEY")
SETS = (("h", "TPC-H"), ("ds", "TPC-DS"))


def stage(ssh, w, cluster, rid, d):
    for s, _ in SETS:
        os.makedirs(f"{d}/{s}", exist_ok=True)
        src = f"{w}/clusters/{cluster}/runs/{rid}/{s}"
        subprocess.run(f"scp -q -r -i {KEY} {ssh}:{src}/run.json {ssh}:{src}/queries {ssh}:{src}/plans {d}/{s}/ 2>/dev/null",
                       shell=True)


def qnum(name):
    return int(name.rsplit(".", 1)[-1])


def load_run(d, s):
    p = f"{d}/{s}/run.json"
    if not os.path.exists(p):
        return None
    r = json.load(open(p))
    qs = {}
    for q in r["queries"]:
        n = qnum(q["name"])
        fid = q.get("file_id")
        q["_sql"] = q["_plan"] = None
        for sub, key in (("queries", "_sql"), ("plans", "_plan")):
            dd = f"{d}/{s}/{sub}"
            if os.path.isdir(dd):
                m = [x for x in os.listdir(dd) if (fid and x.startswith(f"{fid}.")) or x.split(".")[-2:-1] == [f"{n:02d}"]]
                if m:
                    q[key] = open(os.path.join(dd, m[0]), errors="replace").read()
        qs[n] = q
    r["_q"] = qs
    return r


def norm_sql(t):
    if not t:
        return None
    t = re.sub(r"--[^\n]*", "", t)
    t = re.sub(r"(h|ds)bench_\w+", "R", t); t = re.sub(r"search_path=\w+", "SP", t)
    return re.sub(r"\s+", " ", t).strip()


def pipe_of(r):
    return "开" if (r.get("config") or "").endswith("_pipe") else "关"


def f1(v):
    return "—" if v is None else (f"{v:.0f}" if abs(v) >= 10 else f"{v:.1f}")


def esc(t):
    return html.escape(str(t))


def slices_html(q):
    sl = q.get("slices") or {}
    if not sl:
        return '<p class="note">没有 slice 数据（查询短于 1 秒采样间隔，或失败）。</p>'
    rows = "".join(f"<tr><td>{esc(k)}</td><td>{v.get('qes')}</td><td>{f1(v.get('peak_gb'))}</td><td>{f1(v.get('qe_peak_gb_max'))}</td>"
                   f"<td>{f1(v.get('cpu_s'))}</td><td>{v.get('busy_s')}</td><td>{f1(v.get('cores_peak'))}</td>"
                   f"<td>{v.get('skew_mem')}</td><td>{v.get('skew_cpu')}</td></tr>"
                   for k, v in sorted(sl.items(), key=lambda kv: -(kv[1].get("cpu_s") or 0)))
    return ('<div class="tbl"><table class="mini"><thead><tr><th>slice</th><th>QE 数</th><th>内存峰值 GB</th><th>单 QE 最大 GB</th>'
            '<th>CPU 核·秒</th><th>忙碌 s</th><th>峰值核数</th><th>内存倾斜</th><th>CPU 倾斜</th></tr></thead><tbody>'
            + rows + "</tbody></table></div>")


def plan_norm(line):
    """what counts as a plan difference: the operator tree only. Same rule as finalize.plan_hash (costs, row/width
    estimates and every number -- segment counts 32:1 vs 96:1, literals -- replaced), plus role / schema names."""
    l = re.sub(r"\(cost=[^)]*\)|\(actual[^)]*\)|\d+(\.\d+)?", "#", line)
    l = re.sub(r"\b(h|ds)bench_\w+|\b\w+_tpc(h|ds)\b", "R", l)
    return l.rstrip()


def plan_body(t):
    """EXPLAIN output without psql noise (SET lines, header, dashes, '(N rows)')"""
    if not t:
        return t
    return "\n".join(l for l in t.splitlines() if l.strip() and not l.startswith(("SET", "(")) and "QUERY PLAN" not in l
                     and not set(l.strip()) <= {"-"})


def sql_norm(line):
    """SQL lines: role / search_path / qgen comments differ per run and are not part of the query"""
    if re.match(r"\s*(set role|set search_path|--)", line):
        return ""
    return re.sub(r"\s+", " ", line).strip()


def plan_diff(a, b, norm=plan_norm):
    """two columns, lines aligned; changed lines (after norm) highlighted"""
    if not a and not b:
        return '<p class="note">两边都没有保存执行计划。</p>'
    al = (a or "（没有保存执行计划）").splitlines(); bl = (b or "（没有保存执行计划）").splitlines()
    sm = difflib.SequenceMatcher(None, [norm(x) for x in al], [norm(x) for x in bl], autojunk=False)
    L, R = [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        cls = "" if op == "equal" else ' class="chg"'
        n = max(i2 - i1, j2 - j1)
        for k in range(n):
            x = al[i1 + k] if i1 + k < i2 else ""
            y = bl[j1 + k] if j1 + k < j2 else ""
            L.append(f"<span{cls if x else ''}>{esc(x)}</span>"); R.append(f"<span{cls if y else ''}>{esc(y)}</span>")
    return f'<div class="plans"><pre>{chr(10).join(L)}</pre><pre>{chr(10).join(R)}</pre></div>'


def detail_html(qa, qb, la, lb):
    sa, sb = norm_sql(qa.get("_sql") if qa else None), norm_sql(qb.get("_sql") if qb else None)
    if sa and sb and sa == sb:
        sql = f'<h5>SQL（两边相同）</h5><pre class="sql">{esc(qb["_sql"])}</pre>'
    else:
        sql = (f'<h5>SQL（两边不同：模板相同、代入的取值不同，不同的行已高亮）</h5>' + plan_diff(qa.get("_sql") if qa else None, qb.get("_sql") if qb else None, sql_norm)
               if (sa or sb) else '<p class="note">没有保存 SQL。</p>')
    same = (qa or {}).get("plan_shape_hash") and (qa or {}).get("plan_shape_hash") == (qb or {}).get("plan_shape_hash")
    ph = (f'<h5>执行计划（EXPLAIN，未执行）：左 {esc(la)}，右 {esc(lb)}；{"结构相同" if same else "<b>结构不同</b>"}。'
          '只高亮算子结构上的差异；代价、行数估计、segment 数、用户名和 schema 名的差别不算</h5>')
    sl = (f'<h5>slice 资源：{esc(la)}</h5>{slices_html(qa or {})}<h5>slice 资源：{esc(lb)}</h5>{slices_html(qb or {})}')
    err = "".join(f'<p class="err">{esc(l)} 错误：{esc(q.get("error"))}</p>' for q, l in ((qa, la), (qb, lb)) if q and q.get("error"))
    return err + sql + ph + plan_diff(plan_body((qa or {}).get("_plan")), plan_body((qb or {}).get("_plan"))) + sl


def compare_set(A, B, la, lb, s):
    rows, tot = [], dict(n=0, a=0, b=0, faster=0, slower=0, fail=[], newok=[])
    for n in sorted(set(A["_q"]) | set(B["_q"])):
        qa, qb = A["_q"].get(n), B["_q"].get(n)
        oka = qa and qa["status"] == "OK"; okb = qb and qb["status"] == "OK"
        ta, tb = (qa or {}).get("seconds"), (qb or {}).get("seconds")
        sa, sb = norm_sql((qa or {}).get("_sql")), norm_sql((qb or {}).get("_sql"))
        samesql = not (sa and sb) or sa == sb
        cls, tag, ch = "", "", "—"
        if oka and not okb:
            cls, tag = "bad", f'<span class="pill pbad">{esc(lb)} 失败</span>'; tot["fail"].append(n)
        elif okb and not oka:
            tag = f'<span class="pill pgood">{esc(la)} 失败，{esc(lb)} 成功</span>'; tot["newok"].append(n)
        elif not samesql:
            cls, tag = "na", '<span class="pill pna">SQL 不同</span>'
        elif oka and okb:
            d = (tb - ta) / ta * 100 if ta else 0; ch = f"{d:+.0f}%"
            tot["n"] += 1; tot["a"] += ta; tot["b"] += tb
            if d > 10 and tb - ta >= 2:
                cls, tag = "bad", '<span class="pill pbad">变慢</span>'; tot["slower"] += 1
            elif d < -10 and ta - tb >= 2:
                cls, tag = "good", '<span class="pill pgood">变快</span>'; tot["faster"] += 1
        plan = ("相同" if (qa or {}).get("plan_shape_hash") == (qb or {}).get("plan_shape_hash")
                else "<b>不同</b>") if (qa or {}).get("plan_shape_hash") and (qb or {}).get("plan_shape_hash") else "—"
        st = lambda q, t: "—" if q is None else (f"{t}" if q["status"] == "OK" else f"{t}（失败）")
        rid = f"d_{s}_{n}_{id(A)}"
        rows.append(f'<tr class="{cls} row" data-d="{rid}" data-pd="{1 if plan.startswith("<b>") else 0}" tabindex="0"><td><span class="tw">▸</span> Q{n:02d}</td><td>{st(qa, ta)}</td><td>{st(qb, tb)}</td>'
                    f'<td>{ch}</td><td>{tag}</td><td>{plan}</td>'
                    f'<td>{f1((qa or {}).get("peak_rss_gb"))} → {f1((qb or {}).get("peak_rss_gb"))}</td>'
                    f'<td>{f1((qa or {}).get("cpu_s"))} → {f1((qb or {}).get("cpu_s"))}</td>'
                    f'<td>{f1((qa or {}).get("read_gb"))} → {f1((qb or {}).get("read_gb"))}</td>'
                    f'<td>{f1((qa or {}).get("write_gb"))} → {f1((qb or {}).get("write_gb"))}</td></tr>'
                    f'<tr class="det" id="{rid}" hidden><td colspan="10"><template>{detail_html(qa, qb, la, lb)}</template></td></tr>')
    head = (f'<thead><tr><th>查询</th><th>{esc(la)} s</th><th>{esc(lb)} s</th><th>变化</th><th>判定</th><th>计划</th>'
            f'<th>峰值内存 GB</th><th>CPU 核·秒</th><th>读盘 GB</th><th>spill GB</th></tr></thead>')
    return f'<div class="tbl"><table>{head}<tbody>{"".join(rows)}</tbody></table></div>', tot


def config_matrix(spec, runs):
    keys = list(spec["runs"])
    auto = {}
    for k in keys:
        r = runs[k].get("h") or runs[k].get("ds") or {}
        b = r.get("build") or {}
        c = {"构建": b.get("pipeline") or "", "Pipeline（vector.enable_vec_pipeline）": pipe_of(r) if r.get("config") else "",
             "并发": (f"{r['concurrency']['streams']} 个流同时跑" if r.get("concurrency") else "1 个流，串行"),
             "轮数": f"{r.get('rounds') or 1}（耗时取中位数）" if (r.get("rounds") or 1) > 1 else "1"}
        rid = "/".join(str((runs[k].get(s) or {}).get("report_id") or "—") for s, _ in SETS)
        c["报告编号（H / DS）"] = rid
        auto[k] = c
    rows = []
    fields = []
    for k in keys:
        for f in list(spec["runs"][k].get("config", {})) + list(auto[k]):
            if f not in fields:
                fields.append(f)
    for f in fields:
        vals = [spec["runs"][k].get("config", {}).get(f, auto[k].get(f, "")) for k in keys]
        if len(set(vals)) == 1 and len(keys) > 1:
            rows.append(f"<tr><td>{esc(f)}</td><td colspan='{len(keys)}'>{vals[0]}</td></tr>")
        else:
            rows.append(f"<tr><td>{esc(f)}</td>" + "".join(f"<td>{v}</td>" for v in vals) + "</tr>")
    return ('<div class="tbl"><table class="cfg"><thead><tr><th>项目</th>' + "".join(f"<th>{esc(spec['runs'][k]['label'])}</th>" for k in keys)
            + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")


CSS = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "report_html.css")).read()
JS = """<script>
document.addEventListener('click',e=>{const r=e.target.closest('tr.row');if(!r)return;tog(r)});
document.addEventListener('keydown',e=>{if(e.key==='Enter'){const r=e.target.closest('tr.row');if(r)tog(r)}});
function tog(r){const d=document.getElementById(r.dataset.d);const t=d.querySelector('template');
 if(t){d.firstElementChild.appendChild(t.content.cloneNode(true));t.remove()}
 d.hidden=!d.hidden;r.classList.toggle('open',!d.hidden)}
function pf(sec,on){document.querySelectorAll('#'+sec+' tr.row').forEach(r=>{const h=on&&r.dataset.pd!=='1';r.hidden=h;if(h)document.getElementById(r.dataset.d).hidden=true})}
function all(sec,open){document.querySelectorAll('#'+sec+' tr.row').forEach(r=>{if(r.hidden)return;const d=document.getElementById(r.dataset.d);if(d.hidden===open)tog(r)})}
</script>"""


def main():
    if sys.argv[1] == "--stage":
        stage(*sys.argv[2:7]); return
    spec = json.load(open(sys.argv[1])); out = sys.argv[2]
    base_dir = os.path.dirname(os.path.abspath(sys.argv[1]))
    runs = {k: {s: load_run(os.path.join(base_dir, v["dir"]), s) for s, _ in SETS} for k, v in spec["runs"].items()}
    body, totals = [], []
    for i, c in enumerate(spec["comparisons"], 5):
        la, lb = spec["runs"][c["base"]]["label"], spec["runs"][c["cur"]]["label"]
        sec = [f'<section id="c{i}"><h2>{i}. {esc(c["title"])}</h2>', c.get("note_html", ""),
               '<div class="legend"><span><span class="sw" style="background:var(--bad)"></span>红：变慢或失败</span>'
               '<span><span class="sw" style="background:var(--good)"></span>绿：变快</span>'
               '<span><span class="sw" style="background:var(--na)"></span>灰：两边 SQL 不同，不比较</span>'
               f'<span>点击任意一行展开：SQL、两边的执行计划（差异高亮）、每个 slice 的资源</span>'
               f'<button onclick="all(\'c{i}\',true)">全部展开</button><button onclick="all(\'c{i}\',false)">全部收起</button>'
               f'<label><input type="checkbox" id="pf{i}" onchange="pf(\'c{i}\',this.checked)"> 只看计划结构不同的查询</label></div>']
        for j, (s, name) in enumerate(SETS, 1):
            A, B = runs[c["base"]][s], runs[c["cur"]][s]
            if not A or not B:
                continue
            t, tot = compare_set(A, B, la, lb, s)
            sec.append(f"<h3>{i}.{j} {name} 逐条耗时</h3>{t}")
            totals.append((c["title"], name, la, lb, tot, A, B))
        if c.get("analysis_html_file"):
            sec.append(open(os.path.join(base_dir, c["analysis_html_file"])).read())
        sec.append("</section>")
        body.append("".join(sec))
    trows = []
    for title, name, la, lb, t, A, B in totals:
        d = (t["b"] - t["a"]) / t["a"] * 100 if t["a"] else 0
        okA = sum(1 for q in A["queries"] if q["status"] == "OK"); okB = sum(1 for q in B["queries"] if q["status"] == "OK")
        fail = "、".join(f"Q{n:02d}" for n in t["fail"]) or "无"
        trows.append(f"<tr><td>{esc(title)}</td><td>{name}</td><td>两边都成功且 SQL 相同的 {t['n']} 条</td><td>{t['a']} s</td><td>{t['b']} s</td>"
                     f"<td class='{'good' if d < 0 else 'badc'}'><b>{d:+.1f}%</b>"
                     + (f"（快 {t['a'] / t['b']:.2f} 倍）" if t["b"] and t["a"] / t["b"] >= 1.3 else "")
                     + f"</td><td>{t['faster']} / {t['slower']}</td>"
                     f"<td>{okA}/{len(A['queries'])} → {okB}/{len(B['queries'])}</td><td>{fail}</td></tr>")
    tot_html = ('<div class="tbl"><table class="tot"><thead><tr><th>对比</th><th>测试集</th><th>比较范围</th><th>前者</th><th>后者</th>'
                '<th>变化</th><th>变快 / 变慢 条数</th><th>成功条数</th><th>后者新增失败</th></tr></thead><tbody>' + "".join(trows) + "</tbody></table></div>")
    page = f"""<title>{esc(spec.get('page_title', 'TPC 1TB 对比报告'))}</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&family=JetBrains+Mono:wght@400;600&display=swap">
<style>{CSS}</style>
<div class="wrap">
<header><h1>{esc(spec['title'])}</h1><p class="sub">{esc(spec.get('subtitle', ''))}</p></header>
<section><h2>1. 摘要</h2>{spec.get('summary_html', '')}</section>
<section><h2>2. 测试配置</h2>{config_matrix(spec, runs)}</section>
<section><h2>3. 方法与口径</h2><ul>
<li><b>耗时</b>：proteus 记录，从发出查询到返回结果，精确到 1 秒。</li>
<li><b>资源</b>：每秒采样这条查询的 QD/QE 进程，得到内存峰值（同一时刻所有进程相加）、CPU 核·秒、读盘、写盘（即 spill）；多机是几台机器加起来的数。</li>
<li><b>判定</b>：耗时变化超过 10%，并且相差 2 秒以上，才算变快或变慢。</li>
<li><b>执行计划</b>：计时结束后对每条 SQL 跑一次 EXPLAIN（不执行），比较时去掉代价和行数估计，只看结构；"计划不同"就是结构不同。</li>
<li><b>SQL 不同</b>：两次生成查询的随机种子不同，模板一样但代入的取值不一样，这种查询不计入对比。</li>
{spec.get('method_extra_html', '')}</ul></section>
<section><h2>4. 总耗时</h2>{tot_html}</section>
{''.join(body)}
<section><h2>{5 + len(spec['comparisons'])}. 本轮没有覆盖的场景</h2>{spec.get('gaps_html', '')}</section>
<section><h2>{6 + len(spec['comparisons'])}. 后续工作</h2>{spec.get('next_html', '')}</section>
</div>{JS}"""
    open(out, "w").write(page)
    print(out, len(page))


if __name__ == "__main__":
    main()
