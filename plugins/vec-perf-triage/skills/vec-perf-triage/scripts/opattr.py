#!/usr/bin/env python3
"""Attribute first-touch page faults of one QE to vec operators and functions.

  opattr.py <perf-script text> <delta_MB> [--thp-mb M] [--period 16] [--qe N] [--sites 4] [--min 0.5]
            [--tree [--tree-min 0.3]]

Input: `perf script` output of `perf record -e page-faults -c <period>
--call-graph dwarf` taken on ONE QE during a window in which its memory grows
(flame.sh memattr does the recording and calls this script).

  delta_MB  RssAnon growth of that QE over the same window; each operator's
            share of the samples is converted to MB with it.
  --thp-mb  AnonHugePages growth (smaps_rollup) over the same window.  With THP
            enabled, one fault maps 2 MB but counts like a 4 KB one, so huge-page
            memory is nearly invisible to the samples; the coverage line says how
            much of the growth the shares actually describe.
  --period  pages per sample (the -c value), used for the coverage check.
  --min     hide operators below this share (percent).
  --tree    per operator, the call tree from the operator's entry frame (the
            root-most frame of that operator) down to the leaf (memset, memcpy,
            allocator, decompressor ...), every node with its share of all
            samples and MB/QE (GiB x qe); single-child chains are joined with
            " > "; nodes below --tree-min percent are folded into "(other)".
  --qe N    number of QEs of the slice; prints a "x N" column.  Only meaningful
            when the slice is not skewed (sampler skew < ~1.1).

Classification: each stack is walked leaf -> root, the first frame matching an
operator pattern names the operator; the function sites shown under it are the
operator frame plus the nearest non-allocator frames toward the leaf.

What this measures: who FIRST WROTE the new pages, not who holds them.  Rows
queued in an unbounded Sink are charged to the scan / join that produced them;
memory freed and re-used inside the window is not counted.  The sanity line
compares sampled bytes with delta_MB:
  sampled >> delta : memory was also freed in the window -> shares describe churn;
  sampled << delta : growth not seen as 4 KB faults (THP huge pages, mremap'd
                     reallocations) -> shares describe only the covered part.
"""
import argparse, collections, os, re

OPS = [  # first match per frame wins; order only matters within one frame
    ("HashJoin: probe output", r"JoinResultMaterialize|JoinProbeProcessor|ProbeSingleBatch|OnProbeSideBatch|DecodeSelectedInternal|ExecBatchBuilder::AppendSelected"),
    ("HashJoin: build hash table", r"SwissTableForJoin|BuildHashTable|OnBuildSide|SwissJoin::Build|HashJoinNode::BuildSide|RowArray::AppendBatchSelection"),
    ("SonicHashAgg", r"sonic::|SonicGroupBy|LocalAggregator"),
    ("Arrow HashAgg/GroupBy", r"GroupByNode|Grouper|HashAggregate|aggregate_node"),
    ("Project (expr eval)", r"ProjectNode|MapNode::|ExecuteScalarExpression|StringTransformExec|CallFunction"),
    ("Filter", r"FilterNode"),
    ("Sink / output queue", r"SinkNode|PushGenerator|BackpressureReservoir"),
    ("Motion send", r"SendTupleVec|SerializeTupleVec|hashAndSendVec|execVecMotionSender|TakeRA"),
    ("Motion recv (IC buffers)", r"RecvTupleChunk|receiveChunksUDPIFC|rxThreadFunc|DeserializeTupleVec|handleDataPacket|getRxBuffer|ExecVecMotion"),
    ("Shared Scan (CTE)", r"ShareInputScan|shareinput|tuplestore|BufFile"),
    ("Scan: PAX read/decode", r"pax::|VecAdapter|ZSTD|ScanNode|dataset::|PaxScan|MicroPartition|numeric_to_vec"),
    ("Sort/Window", r"Sort|Window"),
    ("PG palloc", r"AllocSetAlloc|palloc|MemoryContext"),
]
COMP = [(n, re.compile(p)) for n, p in OPS]
SKIP = re.compile(r"^(\[unknown\]|__memcpy|__memmove|__memset|_int_malloc|malloc|calloc|realloc|posix_memalign|"
                  r"sysmalloc|operator new|std::|arrow::util::SafeStore|arrow::Buffer::|arrow::PoolBuffer|"
                  r"arrow::.*MemoryPool|je_|mi_|__GI_|el0|do_|handle_mm|__arm64|invoke_syscall|exc_|asm_exc)")


def stacks(path):
    cur = []
    for line in open(path, errors="ignore"):
        line = line.rstrip()
        if not line:
            if cur:
                yield cur
            cur = []
        elif line[0] in " \t":
            p = line.split(None, 1)
            if len(p) >= 2:
                cur.append(re.sub(r"\+0x[0-9a-f]+$", "", p[1].split(" (")[0]))
    if cur:
        yield cur


def short(f):
    """Readable frame name: drop argument lists and template arguments."""
    f = re.sub(r"\[clone [^\]]*\]", "", f)
    out, depth = [], 0
    for ch in f:
        if ch in "<(":
            if depth == 0:
                out.append("<>" if ch == "<" else "()")
            depth += 1
        elif ch in ">)":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    r = "".join(out).replace("()", "").replace("<>", "").strip()
    r = re.sub(r"^(arrow::compute::|arrow::)", "", r)
    r = re.sub(r"\(anonymous namespace\)::", "", r)
    r = r.replace("(anonymous namespace)::", "")
    if r.startswith("operator") and "Visit" in f:      # lambda inside Visit<Foo(...)::lambda>
        m = re.search(r"Visit<[^<(]*?([A-Za-z_]+)\(", f)
        r = f"{m.group(1)}::lambda" if m else r
    r = re.sub(r"(::)+", "::", r)
    return (r or f[:60])[:90]


def entry(st, i, op):
    """Root-most frame of the same operator above the leaf-most match i."""
    rx = dict(COMP)[op]
    k = i
    for j in range(i + 1, len(st)):
        if rx.search(st[j]):
            k = j
        elif any(r.search(st[j]) for n, r in COMP if n != op):
            break
    return k


def print_tree(node, n, delta, qe, tmin, indent, total_label=None):
    kids = sorted(node["k"].items(), key=lambda kv: -kv[1]["c"])
    shown = [(name, ch) for name, ch in kids if 100 * ch["c"] / n >= tmin]
    other = node["c"] - node["self"] - sum(ch["c"] for _, ch in shown)
    for name, ch in shown:
        label = [name]
        while len(ch["k"]) == 1 and ch["self"] == 0:       # join single-child chains
            (nm, nx), = ch["k"].items()
            if nx["c"] != ch["c"]:
                break
            label.append(nm)
            ch = nx
        pct = 100 * ch["c"] / n
        mb = delta * ch["c"] / n
        g = f" {mb * qe / 1024:6.1f}G" if qe else ""
        print(f"{pct:6.1f}% {mb:6.0f}MB{g}  {indent}{' > '.join(label)}")
        print_tree(ch, n, delta, qe, tmin, indent + "  ")
    if node["self"] and 100 * node["self"] / n >= tmin and node["k"]:
        mb = delta * node["self"] / n
        g = f" {mb * qe / 1024:6.1f}G" if qe else ""
        print(f"{100 * node['self'] / n:6.1f}% {mb:6.0f}MB{g}  {indent}(self)")
    if other > 0 and 100 * other / n >= tmin / 2:
        mb = delta * other / n
        g = f" {mb * qe / 1024:6.1f}G" if qe else ""
        print(f"{100 * other / n:6.1f}% {mb:6.0f}MB{g}  {indent}(other < {tmin}%)")


def classify(st):
    for i, f in enumerate(st):
        for name, rx in COMP:
            if rx.search(f):
                return name, i
    return "other/unknown", len(st)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("perfscript")
    ap.add_argument("delta_mb", type=float)
    ap.add_argument("--thp-mb", type=float, default=None)
    ap.add_argument("--period", type=int, default=16)
    ap.add_argument("--min", type=float, default=0.5)
    ap.add_argument("--qe", type=int, default=0)
    ap.add_argument("--sites", type=int, default=4)
    ap.add_argument("--tree", action="store_true")
    ap.add_argument("--tree-min", type=float, default=0.3)
    a = ap.parse_args()

    cnt, sites, unk = collections.Counter(), collections.defaultdict(collections.Counter), collections.Counter()
    newnode = lambda: {"c": 0, "self": 0, "k": {}}
    trees = collections.defaultdict(newnode)
    n = 0
    for st in stacks(a.perfscript):
        n += 1
        op, i = classify(st)
        cnt[op] += 1
        if a.tree and op != "other/unknown":
            node = trees[op]
            node["c"] += 1
            for f in reversed(st[:entry(st, i, op) + 1]):     # entry frame -> leaf
                if f.startswith("[unknown]"):
                    continue
                name = short(f)
                node = node["k"].setdefault(name, newnode())
                node["c"] += 1
            node["self"] += 1
        if op == "other/unknown":
            unk[" <- ".join(st[:4])[:160]] += 1
        else:
            below = [f for f in st[:i] if not SKIP.search(f)][-2:]
            sites[op][" <- ".join(below + [st[i]])[:200]] += 1
    if n == 0:
        msg = "window outside the growth phase, or wrong pid"
        if a.delta_mb > 0:
            msg = (f"but RssAnon grew {a.delta_mb:.0f} MB: growth not taken as 4 KB faults "
                   "(THP huge pages, MAP_POPULATE, mremap) -- check --thp-mb / smaps")
        print(f"{a.perfscript}: 0 samples -- {msg}")
        return
    page = os.sysconf("SC_PAGE_SIZE")
    sampled_mb = n * a.period * page / 2**20
    print(f"{a.perfscript}: {n} samples x {a.period} pages; sampled ~{sampled_mb:.0f} MB vs RssAnon delta {a.delta_mb:.0f} MB")
    if a.thp_mb is not None and a.thp_mb > 0:
        print(f"  AnonHugePages grew {a.thp_mb:.0f} MB of the {a.delta_mb:.0f} MB (huge-page faults are ~invisible to the samples)")
    if a.delta_mb > 0:
        cov = sampled_mb / a.delta_mb
        if cov > 2:
            print(f"  NOTE: coverage {cov:.1f}x: memory was also freed in this window; shares describe churn, not net growth")
        elif cov < 0.7:
            why = "THP" if a.thp_mb and a.thp_mb > 0.2 * a.delta_mb else "THP or mremap'd reallocations (pass --thp-mb to tell)"
            print(f"  NOTE: coverage {cov:.0%}: {why}; MB columns assume the uncovered part splits like the sampled part -- unverified")
    if a.delta_mb <= 0:
        print("  NOTE: RssAnon did not grow; MB columns are meaningless, read the shares only")
    hdr = f"  {'share':>6}  {'MB/QE':>7}" + (f"  {'GiB x' + str(a.qe):>8}" if a.qe else "") + "  operator / function sites"
    print(hdr)
    hidden = 0
    for op, c in cnt.most_common():
        if 100 * c / n < a.min:
            hidden += c
            continue
        mb = a.delta_mb * c / n
        col = f"  {mb * a.qe / 1024:8.1f}" if a.qe else ""
        print(f"  {100 * c / n:5.1f}%  {mb:7.0f}{col}  {op}")
        for s, k in sites[op].most_common(a.sites):
            print(f"  {'':>6}  {'':>7}{'  ' + ' ' * 8 if a.qe else ''}    {100 * k / n:5.1f}%  {s}")
    if a.tree:
        print("\n=== call trees: entry frame -> leaf; % of all samples, MB/QE" + (f", GiB x{a.qe}" if a.qe else ""))
        for op, c in cnt.most_common():
            if op == "other/unknown" or 100 * c / n < a.min:
                continue
            mb = a.delta_mb * c / n
            g = f" {mb * a.qe / 1024:6.1f}G" if a.qe else ""
            print(f"\n{100 * c / n:6.1f}% {mb:6.0f}MB{g}  [{op}]")
            print_tree(trees[op], n, a.delta_mb, a.qe, a.tree_min, "  ")
    if hidden:
        print(f"  ({100 * hidden / n:.1f}% in operators below --min {a.min}% not shown)")
    if unk and 100 * cnt["other/unknown"] / n >= a.min:
        print("  other/unknown top stacks (add a pattern to OPS if one is large):")
        for s, k in unk.most_common(3):
            print(f"           {100 * k / n:5.1f}%  {s}")


if __name__ == "__main__":
    main()
