---
name: tpc-bench
description: 一句话触发的 TPC-H / TPC-DS 性能测试（单机或多机，可整晚无人值守）。从 umbrella 流水线取最新 main（或指定流水线号）的 RPM，解包部署到测试机的独立目录，用 proteus 跑测试并轻量采集每条查询的资源、计划、结果指纹；和上一次比较找出慢查询，对前 3 条自动复核、二分到流水线、剖析，由 claude -p 写出根因、提交、修复方案和预计收益；三份报告上传到 proteus 报告网站和 claude-sync。用户只说"去 56 跑 1TB tpcds""今晚跑个全的测试"之类，其余由本 skill 探测补全。
---

# tpc-bench

用户只给关键信息（机器、规模、测试集）。其余参数一律自己补：查清单、上机器探测、取流水线。
只在下面"必须问"的情况停下来问。

## 站点配置（第一次使用前）

skill 本身不含任何站点信息。把 `site.env.example` 复制成 `~/.tpc-bench/site.env` 并填好：ssh 密钥、报告服务器（ssh 目标、网页前缀、目录、报告库的连接串）、umbrella 的 GitLab 主机和项目、proteus 的 git 地址、本地 umbrella 仓库、claude-sync 目录。
- 本机脚本通过 `scripts/tpcsite.py` 读取这份配置。
- `nightly.py` 每次运行会把它拷到每台测试机的 `<workdir>/bin/site.env`，测试机上的 `upload.sh` 和 `upload_metrics.py` 从那里读。
- 报告服务器的 ssh 密钥是 proteus 仓库里的 `tools/report_key`，skill 里不带。

## 0. 安全规则（每一步都要遵守）

- 只动 tpc-bench 自己的东西：`<workdir>` 下的文件、自己建的集群（数据目录里有 `.tpcbench_cluster` 标记）。
  别人的集群、容器、进程、`~/.bashrc`、`/usr/local` 下的链接、rpm 数据库，一律不碰。
- 不做 drop_caches：proteus 一律带 `PRESERVE_SYSTEM_CACHE=true`；导数据的配置用 `REPORT_TYPE=setup`。
- proteus 会杀掉机器上所有的 gpfdist / dbgen / dsdgen（以 gpadmin 身份执行，容器里的 gpadmin 是同一个 uid）。
  - `patch_proteus.sh` 把 stop_gpfdist 限制为只杀 `tpcbench_` 目录下的进程。
  - `load.sh` 导数据前发现外人的 gpfdist、dbgen 或 dsdgen，就中止。
- 不加内存保护（不自动取消查询），否则结果没法和别人比。OOM 照实记录。
- 下面这些动作要先把计划给用户看，得到确认后才执行：
  - 新建集群；
  - 重启或切换已有集群的版本；
  - 导数据（1TB 要几个小时）；
  - 机器上有别人的重负载时，是否照样跑。

## 1. 补全计划

1. **主机**
   - 先查 `~/.tpc-bench/inventory.yaml`：别名到 IP、ssh 用户和 key、workdir、已知集群。
   - 查不到时，把 "56" 这类写法当作已知网段 IP 的最后一段去试（清单里任一台机器的 `/24` 网段），
     用 `ssh -i $TPCBENCH_SSH_KEY root@IP` 试连。连通后写回清单。
2. **探测**：`ssh root@IP python3 - < scripts/remote/discover.py`，得到以下信息：
   - 架构、核数、内存、磁盘余量；
   - 所有 postmaster：端口、目录、是否在容器里、是否带 tpcbench 标记；
   - 外人的 gpfdist；
   - 3 秒内各集群的 CPU 占用（`postgres_cores_busy`）。
3. **集群**
   - 优先用这台机器上带 tpcbench 标记的集群（清单里有记录）。
   - 没有就计划新建：端口从 6532 起找空闲的；**每台机器的 segment 数：规模 ≤100 用 8 个，1TB（及以上）固定 32 个**（用户要求）；
     数据目录选余量最大的两块 `/data*` 盘；workdir 是 `<余量最大的盘>/tpcbench`。集群名按规模取：`sf10`、`sf1000`。
   - 1TB 额外检查：两块数据盘合计余量 ≥ 约 2TB（原始文本 ~1TB + PAX 数据），不够就停下来问；
     内存参数按 32 段重算（`gp_vmem_protect_limit × 32` 要明显小于物理内存，留出向量化不记账的内存），
     不能照搬 8 段的值；导数据第一次约 2.5–3 小时（未实测，SF10 外推），建议白天先导好。
   - 多机时，所有主机用相同的目录布局（同一个 workdir、同一组数据盘），coordinator 放在第一台。
     多机集群命名 `mh<规模>`（如 `mh1`、`mh1000`），和单机集群分开存数据、分开当基线（数据分片数不同，结果不能互比）。
4. **数据**：读 `clusters/<name>/data_<set>_sf<scale>[rand].json`，核对其中的 `distribution`。没有这份文件，或规模、分布方式不一致，就计划导数据。
5. **构建**：在本机执行 `python3 scripts/resolve_build.py latest|<流水线号> --arch <探测到的架构>`。
   - 和集群当前构建（`clusters/<name>/build.cur`）一样就不切换。
   - 不一样就计划部署并切换（`cluster.sh use`）。切换失败（比如 catalog 不兼容）会自动退回原构建，
     这时要问用户是否新建集群并重新导数据。
6. **默认值**
   - "全的" = h,ds；
   - 1 轮；
   - 上传；
   - 向量化开；
   - **Pipeline 开和关都要测**（用户要求）：`vector.enable_vec_pipeline` 的 off 和 on 是两套独立的测试配置。
     - off 的配置名是 `..._run`，run_id 是 `<时间>`；on 的配置名是 `..._run_pipe`，run_id 是 `<时间>_pipe`。
     - 两种模式各自找基线，互不比较。
     - 夜跑默认先跑 off、再跑 on，两次 nightly 前后串起来跑；用户只要其中一种时，才单独跑那一种。
     - 两种模式下，guc.conf 和 PRE_QUERY_SQL 都显式写这个参数，阶段 2 复测时用的也是同一种模式。
   - **轮数：默认 3 轮**（用户要求）。用 proteus 的 `SINGLE_USER_ITERATIONS=3`，每条查询连续跑 3 次。
     - 耗时取中位数；资源归到中位数那一次；`rounds` 里记 3 次原始耗时，`spread` 记最快和最慢的差。
     - 判定变慢时，差距还必须大于两边的 spread。
     - 1TB 跑 3 轮，耗时约为 1 轮的 3 倍，单机 H+DS 约 3.6 小时。时间不够就用 `--rounds 1`，并在计划里说明。
   - **并发：`--streams N`**（用户要求；例如 4）。这是独立的一套测试：
     - 走 proteus 的 multi-user：N 个流同时跑，每个流的查询参数不同，种子固定为 `RNGSEED`，每次都一样。
     - 配置名是 `..._run_c<N>`，run_id 是 `<时间>_c<N>`，只和流数相同的运行比较。
     - 报告①写整段耗时、吞吐（条/小时）、每个流的成功数和耗时、整机内存最低值和 CPU 最高值。
     - 并发时分不清每条查询各自的资源，表里只列耗时：各流的中位数。
     - 不做 triage，也不做 EXPLAIN。
     - 默认组合是 1 流 × 3 轮。完整的矩阵是 Pipeline 开/关 × 1 流/N 流，开销大，按周轮着跑，或者在用户要求时跑。
     - proteus 补丁 5：只统计我们自己目录下的 multi-user 进程，避免等别人的 proteus。
   - pax 存储，hash 分布（proteus 默认，按 distkeys 建表）；用户说 random 才用 `--random true`，数据放在单独的 `sf<规模><am>rand_*` schema；
   - tags 按 `<am> <random|hash> vec<on|off> pipe<on|off> c<流数> r<轮数> b<流水线号> <N>node <主机名> sf<规模>` 生成，用户的额外标签附在后面。

把补全后的计划（主机、集群、构建、数据、测试、上传、预计耗时、同机负载、要用户确认的动作）用一段话列出来，等用户回复"确认"。

## 2. 执行

**整晚无人值守（推荐，用户说"今晚跑""夜里跑"或没说时都用这个）**：计划确认后，在本机执行

```
nohup python3 $S/nightly.py --ssh root@<coordinator IP> [--hosts root@<IP2>,root@<IP3>] --workdir <W> \
      --cluster <name> --scale <N> [--sets h,ds] [--build latest|<流水线号>] [--base auto|<run_id>] [--allow-load] [--pipeline off|on] [--rounds 3] [--streams 1] \
      > /dev/null 2>&1 &
```

**多机（`--hosts`）只在所有机器都空闲时运行**（用户要求）：开跑前每台机器跑 `idle.py`（30 秒，整机 CPU 来自 /proc/stat，
能看到短命的查询进程），三条都满足才算空闲——整机繁忙 < 6 核、没有别人的 gpfdist/dbgen/dsdgen、可用内存 ≥ 350GB（1TB）/ 50GB；
**间隔 5 分钟连续两次**空闲才开始；不空闲就每 15 分钟复查，到 `--idle-deadline`（默认 03:00）仍不空闲则放弃，
并往 claude-sync 写一条"未运行"（写明哪台、谁在占用）。跑的途中别人开始用机器不中断，报告打 `other_load`。
单机默认不检查（`--idle-gate on` 可以打开）。

它依次完成：同步脚本 → 取包部署、切换构建 → 检查数据（`--allow-load` 才自动导）→ 阶段 1 计时 →
报告①② → 阶段 2（前 3 条慢查询）→ `claude -p` 写报告③ → 上传报告服务器和 claude-sync。
日志 `~/.tpc-bench/nightly/<cluster>/<run_id>/nightly.log`，状态 `state.json`；结果目录 `~/.tpc-bench/analysis/<cluster>/<run_id>/`。
1TB 预计（一轮 H+DS）：
- 单机 32 段：H 约 26 分钟、DS 约 51 分钟（实测）；夜里 1.5 小时（无慢查询）到约 4.5 小时（3 条慢查询）；首次导数据再加约 3 小时。
- 三机 96 段（56/57/58）：DS 约 29 分钟（实测，单机的 1.76 倍快）、H 约 15 分钟（估算）；重查询快 2–3.5 倍，
  小查询反而慢（派发和 Motion 固定开销）；瓶颈是网络（之前实测单块 10GbE 跑满）。夜里约 1 小时起。
无人值守需要长期有效的登录：本机 `claude setup-token`（普通登录约一周过期）。

下面是分步执行（交互时用，或 nightly 出错后手工补跑）。

`S=<本 skill 所在目录>/scripts`（独立安装时是 `~/.claude/skills/tpc-bench/scripts`）；`W=<workdir>`；`H=root@<主机>`；`K="-i $TPCBENCH_SSH_KEY"`。

1. **准备（每台主机）**
   - 本机 clone 或更新 proteus 到 `~/.cache/tpc-bench/proteus`（`$TPCBENCH_PROTEUS_GIT`，
     测试机上没有 git 凭据），记下 `git rev-parse HEAD > .tpcbench_rev`，再执行 `scripts/patch_proteus.sh`。
   - 用 rsync 同步到 `$W/proteus`（排除 `.git` 和 `results`），`$S/remote/` 同步到 `$W/bin/`。
     同步后要 `chmod +x $W/bin/*` 并 `chown -R gpadmin`。
   - 执行 `pip install --target $W/pylib python-dotenv jinja2`（以 gpadmin 身份；已经装过就跳过）。
2. **取包**（每台主机，root 身份）
   - `$W/bin/fetch_deploy.sh $W <流水线号> <rpm_url> <release_yaml_url>`。
   - 把 resolve_build 的 JSON 存成 `$W/pkgs/<id>/build.json`。
   - 包会一直留在 `pkgs/` 下，以后二分时用（GitLab 的 job 产物只保留 1 周）。
3. **新建集群**（gpadmin 身份，在 coordinator 上执行）
   - `$W/bin/init_cluster.sh $W <name> <id> <port> <segs_per_host> <hosts_csv> <datadirs_csv>`。
   - 再把 discover 的输出存成 `$W/clusters/<name>/host.json`。
4. **切换构建**：`$W/bin/cluster.sh $W <name> use <id>`。
5. **导数据**
   - `nohup $W/bin/load.sh $W <name> h <scale>`，ds 同理。两个测试集必须先后执行，不能并行。
   - 导完会自动 ANALYZE、记录行数、删除生成的平面文件。
6. **测试**
   - `nohup $W/bin/run.sh $W <name> <run_id> <sets> <scale> <upload> "<tags>" &`，run_id 用 `YYYYmmdd_HHMMSS`。
   - 进度看 `clusters/<name>/runs/<run_id>/state.json` 和 `run.log`。
   - 用 Monitor 等待 `state.json` 里的 phase 变为 `done`，不要频繁轮询；SF10 大约 20 分钟，1TB 大约 2 小时。
   - 流程验证时可以加 `INJECT_CANCEL=<查询文件号，如 105>`，故意让一条查询失败。
7. **分析**（每次跑完都要做，不能省；见第 3 节）
   - 报告①②：`python3 $S/analyze.py --host $H --workdir $W --cluster <name> --run <run_id> --set <sets> --upload`
   - 有慢查询时阶段 2 + 报告③：`python3 $S/nightly.py ... --run-id <run_id>`（复用已跑完的运行，跳过阶段 1）。
8. **正式对比报告（HTML，用户要求的格式）**：
   - 先用 `python3 $S/report_html.py --stage <ssh> <W> <cluster> <run_id> <本地目录>` 把每次运行的 run.json、SQL、EXPLAIN 拉到本地。
   - 再写 spec.json（说明见脚本开头），执行 `python3 $S/report_html.py spec.json report.html`，用 Artifact 发布。
   - 报告的结构依次是：摘要、配置表（Pipeline、并发、轮数都要写）、方法、总耗时、各项对比（单机在前，多机在后）、没测到的场景、后续工作。
   - 每条查询都能展开，里面有两边的 SQL、两边的执行计划（差异行高亮）和各 slice 的资源；变慢或失败的标红。
   - 根因分析写成 HTML 片段，挂在对应的对比项下面。
9. **汇报**
   - 读三份报告、每个测试集的 `summary.txt` 和 `run.json`，用中文告诉用户以下内容：
     - 报告链接；
     - 成功和失败的条数；
     - 失败原因；
     - flags（other_load、layout_bad、crashed、proteus_failed）；
     - 和上一次同配置运行的差异（见第 3 节）。
   - 更新 `~/.tpc-bench/inventory.yaml`：集群、数据、最后一次运行。

## 3. 分析的三个阶段和三份报告

多机时：每台机器各跑一份 qmon/sysmon（结果拉回 coordinator：`qmon.<host>.jsonl`、`sysmon.<host>.tsv`），
finalize 按 1 秒对齐合并（pid 加机器偏移），每条查询的 slice 统计覆盖所有机器的 QE；报告①多一节各机器网络
（收/发 MB/s 平均和峰值）和各机器采集器开销；报告库的指标按机器 IP 分别写入；阶段 2 的 perf 在每台机器上都做
（`prof_*.<host>.hot.txt`）；layout 检查覆盖所有机器的 postmaster。

**阶段 1（每次都做，计时期间只读 /proc，不影响性能）**：qmon 每秒、sysmon 每 5 秒采样；采集器自身 CPU 记在
`run.json` 的 `collectors`（SF10 实测平均远小于 1 核）。finalize 为每条查询算出：峰值内存、CPU 秒、平均/峰值核数、
生成计划+派发时间（`plan_dispatch_s`）、内存曲线形状；每个 slice 的峰值、倾斜（最大/中位数）、忙碌区间、峰值核数，
以及忙碌最久的 slice（近似关键路径）。
- **报告①** `report1_results.md`：最慢查询及占比、内存最高、spill、失败分类、干扰标记、异常线索
  （每个 segment 不到 1 核、优化器耗时、倾斜、单线程瓶颈、锯齿）。
- **报告②** `report2_slow.md` + `slow.json`：基线 = 同集群、同测试集、同数据、无 other_load/crashed 的上一次运行。
  单条耗时同时超过 +10% 和 +2 秒算慢；按多花的秒数排序，**只取前 3 条**进入阶段 2（用户决定）。
  附两次构建之间的提交（database / arrow，按 optimizer / executor-vec / storage / test 分类）。
  没有基线时只列异常线索，不判定慢。数据不同或有 other_load 时不判定慢。

**阶段 2（只对前 3 条慢查询，计时结束后单独跑，会切换和重启 tpc-bench 自己的集群）**：`deep.py`
1. 复核：旧构建 A / 新构建 B 按 ABBAAB 交替各 3 次，每次切换后先让 libarrow 布局干净（`bad=0`）再预热；
   中位数差距 > 10% 且大于两边的波动才算 CONFIRMED，否则 NOISE（不往下查）。
2. 二分：A、B 之间有多个流水线时，用这一条查询在中间的流水线上测（各 3 次），找出第一个变慢的流水线。
   每天一次子模块更新，相邻两晚通常只隔 1 个流水线；CI 产物只保留 7 天，过期的跳过并注明。
3. 剖析（两个构建各一次）：全部 QE 的 perf 热点函数（`prof_*.hot.txt`）、变化最大的 slice 中一个 QE 的
   dwarf 调用栈汇总（`prof_*.cg_top.txt`）、EXPLAIN VERBOSE、EXPLAIN ANALYZE。

**最慢 3 条 SQL 的 triage（每次都做，用户要求）**：计时和报告①②完成后，`nightly.py` 的 `triage_top3` 对每个测试集里最慢的 3 条成功查询做 vec-perf-triage，只在当前构建上跑，不切换构建。
- 先用 sampler 跑一遍，得到每个 slice 的内存曲线、CPU 和倾斜。
- 再跑一遍并抓 perf：所有机器上全部 QE 的热点函数，加上当次计时里忙得最久的那个 slice 中一个 QE 的 dwarf 调用栈。
- 峰值内存 ≥ 50GB 的查询，在最大那个 slice 的内存上涨窗口里抓一次 memattr，把内存归到算子和函数。
- 最后做 EXPLAIN ANALYZE，拿到实际行数。
- 数据放在 `runs/<run_id>/triage/<set>_<file_id>/`；报告③里有一节"最慢的 3 条 SQL 分析"，按 triage 第 2–11 步写。
- 用 `--no-triage` 可以关掉；已经跑完的运行可以用 `--run-id` 补做 triage。
- 重放查询时，固定使用那次运行自己的 Pipeline 模式。
- **展示格式是用户确认过的（2026-11-13），由 `scripts/triage_html.py` 生成，页面是 `triage.html`。**
  - 页面最上面是红框"一眼看重点"：3–5 条结论，每条带数字。
  - 每条 SQL 一张卡片，从上到下依次是：
    - 标题：耗时用大号红字，旁边写占本测试集总耗时的比例；
    - 蓝框结论：结论、可省多少、建议、置信度；
    - 关键数字：内存 ≥200GB、整机可用内存 <50GB、spill ≥50GB 显示红色，内存 ≥100GB、spill ≥10GB 显示橙色；
    - 自动标签：高内存、内存接近耗尽、spill、倾斜、单线程瓶颈；
    - triage 的各个字段；
    - slice 表：关键路径那一行用橙底，超过阈值的数字用红字。
  - 页面最后是一张汇总表。
  - 结论内容由 `claude -p` 写进 `triage_analysis.json`（字段见脚本开头）。还没有数据的字段显示灰色斜体"（待 triage 数据）"。
  - 页面会上传到报告服务器 `/proteus/perf/<id>/tpcbench/triage.html`；交互汇报时用 Artifact 发布。

**阶段 3**：`claude -p` 按 vec-perf-triage 的方法写 **报告③** `report3_deep.md`：总体结论；每条慢查询的现象、
复核结论、定位到的流水线和提交（读 diff）、因果链、证据（至少两条）、置信度、修复方案（文件和函数）、
修复后预计耗时（以旧构建实测为上限，标"估算"，不编译验证——用户决定）、风险。
三份报告上传到报告服务器 `/proteus/perf/<report_id>/tpcbench/` 和 claude-sync
`Knowledge/Projects/hashdata-lightning-umbrella/perf-reports/<日期>-<集群>-<run_id>/`（含 index.md）。

## 4. 已知的坑

- **`TERM` 必须是 xterm**：ssh 加 su 得到的是 `TERM=dumb`，proteus 的 `tput sc` 会静默返回 1，
  在 `set -e` 下直接退出。`cluster.env` 和各脚本都已经强制 `TERM=xterm`。
- **proteus 的 ANALYZE 只在 SQL 步骤里做**：导数据后必须显式 ANALYZE，`load.sh` 已经做了。
  计时运行时 `RUN_ANALYZE=false`。
- **查询要固定**：`RUN_QGEN=true` 加 `UNIFY_QGEN_SEED=true` 保证每次生成同一套查询；查询文件会一起存档。
- **TPC-H 和 TPC-DS 的 query_id 有重叠**：不能跨测试集按 id 匹配。
- **proteus 的计时精度只有秒**：短查询的差异要看多轮的结果。
- **proteus 每个测试集开始时都会重启集群**：应用 guc.conf 后执行 `gpstop -air`（立即停止，下次启动要做恢复）。
  所以 preflight 时记录的进程信息都会失效：
  - qmon 发现缓存的 postmaster 不在了就立刻重新查找；
  - layout 在每个测试集跑完后对实际跑查询的进程重新记录（`<set>/layout.txt`）；
  - 会话号（con）在重启后从头分配，并且不是每条查询加 1。finalize 按会话进程的启动时间
    （精确到约 10 毫秒），和查询的开始秒一对一匹配；两条查询在同一秒开始、只采到一个会话时，
    标为 `ambiguous`，不计入比较。
- **多机：远端 segment 起不来，`Local Software Version does not match`**：RHEL 的 bash 在 ssh 会话的子 shell 里
  （有 `SSH_CLIENT` 且 `SHLVL<2`）会重新读 `~/.bashrc`；57/58 的 gpadmin `.bashrc` 会 source `/usr/local/hashdata-lightning`
  的环境，把 gpsegstart 子 shell 里的 GPHOME 换成机器上原装的版本。不改 `.bashrc`：`fetch_deploy.sh` 在我们自己
  gphome 的 `cloudberry-env.sh` 末尾加 `unset SSH_CLIENT SSH2_CLIENT`（标记 `tpcbench-ssh-bashrc-fix`）。
- **多机：proteus 的共享副作用**（`patch_proteus.sh` 打了 4 个补丁，load.sh 检查补丁齐全才导数据）：
  stop_gpfdist 只杀 tpcbench 的；`pkill dbgen/dsdgen` 只杀命令行带 `tpcbench_` 的；gpfdist 端口用
  `TPCBENCH_GPFDIST_PORT`（load.sh 在所有机器上找 27000 起的空闲段）——默认端口 `<digit>4660/5880` 和别的 proteus 用户相同。
  proteus 还会把 `start_gpfdist.sh`、`generate_data.sh`、dbgen/dsdgen 拷到每台机器 gpadmin 的家目录（别人的 proteus 也这样做，
  每次导数据前都会重新拷）。**别人没打补丁的 proteus 在我们导数据时结束，会杀掉我们的 gpfdist**——这只能靠空闲检测避开。
- **多个规模共用一个 proteus 目录**：`05_sql/` 里同时有各规模的查询文件，run.sh 只归档本次实际执行过的
  （以 `*.single.result.out` 为准），否则 EXPLAIN、计划哈希和阶段 2 会拿到别的规模的 SQL。
- **在 `while read` 循环里调 ssh 必须加 `-n`**，否则 ssh 吃掉循环的输入，只处理第一台远端机器。
- **短查询没有资源数据**：短于 1 秒采样间隔的查询，`resources` 字段会写明原因，analyze 里显示为 `-`。
  长查询也显示"未采样"就是归属出了问题。96 段三机集群上，QD 在 proteus 记下结束时间后还会存活约 2 秒，
  所以 finalize 允许会话比结束时间晚 `END_SLACK=5` 秒消失（原来 1.3 秒，曾漏掉 DS Q23 和 H Q17）。
- **proteus 的 TPC-DS 生成缓存**：`generate_data.sh` 默认（`USE_CACHE=true`）会把全部原始文件再拷一份到
  `/data/nvme0`（或 `/data/nvme1`）下的 `tpcds_cache/scale_N/parallel_P/`。这块盘不归我们管，
  1TB 时 330GB 曾把 56 的 nvme0 写满，store_sales 导入失败。`load.sh` 已强制 `USE_CACHE=false`。
  别人的 `tpcds_cache`（比如 `/data/tpcds_cache`、`scale_300`）不要动。
- **磁盘估算（1TB，hash，PAX zstd5）**：
  - H 的原始文本约 1.25TB，PAX 约 0.3TB；
  - DS 的原始文本约 0.33TB，PAX 约 0.5TB（按 SF10 的比例估算）；
  - 原始文本放在 segment 目录里，导完才删。
- **建集群后要有 `host.json`**：`mkconfig.py` 要用，`init_cluster.sh` 不写。`nightly.py` 发现没有时会自动探测生成。
- **多机远端采集器的文件按追加写**：以前每个测试集开始时会清空，前一个测试集就没法带着远端 QE 重新跑 finalize 了。
- **鲲鹏上的随机变慢**：libarrow 加载地址对 256MB 取模落在 F6–FC MB 区间时，个别查询会慢约 30%，
  `layout.txt` 会记录。必要时重启集群，直到 `bad=0`。
