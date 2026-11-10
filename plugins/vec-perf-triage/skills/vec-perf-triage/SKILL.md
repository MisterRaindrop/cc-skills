---
name: vec-perf-triage
description: 分诊 HashData Lightning 向量化引擎查询的内存高、CPU 高、变慢、卡住、并发 OOM。按"安全分级 → 问题陈述 → 计划 DAG → 资源体检 → 时间序列 → 专项 → 下钻 → 归类 → 量化 → 报告"的流程，把资源归因到 slice、算子和代码，判断属于环境、数据、参数、计划、引擎结构还是缺陷，输出一份带置信度的分析文档。
---

# 向量化查询资源问题分诊（v2）

要回答三个问题：
1. **哪里**：资源（内存 / CPU / 等待）花在哪个 slice、哪个算子、哪段代码？
2. **为什么**：从现象到根因的完整因果链，不跳步。
3. **怎么办**：属于哪一类；调参能否解决，还是要改代码；改哪里，预期收益多少，把握多大。

原则：
- **两条独立证据**：每个根因结论至少要有两条互相独立的证据，比如采样曲线加 A/B，或火焰图加原型。只有一条证据的，报告里标"很可能"；没有直接证据的标"推测"。
- **先便宜后昂贵，先不侵入后侵入**：见第 0 步的分级。
- **曲线和火焰图只用来提假设，不能直接当结论**。同一种曲线形状可以有多种解释，必须用对照实验去区分。
- **问题库只用来提示方向**：命中 `references/known-patterns.md` 里的条目，也要按条目里的"判定"重新验证，不能直接套用结论。
- 机器、构建和案例数字只放在 `references/cases.md`，正文的规则不依赖某一台机器。

---

## 第 0 步：安全与侵入性分级（每个动作前先对照）

| 级别 | 动作 | 影响 | 要求 |
|---|---|---|---|
| L0 只读 | 查系统表，读 `/proc`，看日志、`dmesg`、`EXPLAIN`（不带 ANALYZE） | 几乎没有 | 随时可做 |
| L1 跑查询 | `sampler.py` / `ab.sh` / `EXPLAIN ANALYZE` | 占用 CPU、内存、IO，会影响同机的其他人 | 先确认机器空闲或可以占用；要设超时（脚本默认 `statement_timeout=1800s`）；只跑只读 SQL（脚本会拒绝写语句）；输出过大时取消（默认 200MB） |
| L2 采样分析 | `flame.sh cpu/faults/switches/offcpu/topdown` | perf 开销约 1–5%；tracepoint 和 BPF 需要 root | 用 `SUDO=sudo`，不要为了方便去改 tracefs 权限或 `perf_event_paranoid`（这是全局配置） |
| L3 暂停进程 | `stacks.sh`（gdb attach）、gdb 断点、`perf probe` | 进程会被暂停，可能改变正在观察的等待关系；gdb 加载符号很耗 CPU | 只对已经卡住的查询用；先抓一次，有必要再抓多次；限制并发数（`JOBS`） |
| L4 改环境 | 改 `postgresql.conf`、`gpconfig`、重启集群、改内核参数、清缓存（`drop_caches`） | 影响整台机器上的所有人 | **每次都要先得到用户确认** |

别人的集群、容器和进程一律不碰。`qe_pids.py` 通过父进程（本集群的 postmaster）和 `con<N>` 两个条件来确认进程属于本会话，所以不会误采、误暂停别人的进程。

---

## 第 1 步：问题陈述、环境与结果指纹（写进文档开头）

| 问题 | 示例 |
|---|---|
| 现象，用数字描述 | "4 流并发时 OOM；单跑时全部 QE 的 RssAnon 同一时刻之和的峰值为 X GiB" |
| 期望值及依据 | 行引擎（`vector.enable_vectorization=off`）、上一个正常构建，或 DuckDB 在同规模下的数值 |
| 从什么时候开始，最近改过什么 | 构建号、合入的 MR、改过的 GUC |
| 必现还是偶现；单跑还是只在并发时出现 | 偶现的问题至少跑 3 轮 |
| 范围 | 某条查询 / 某类查询 / 全部；PAX 还是 Iceberg |

**环境确认清单：**
- 构建：`postgres --gp-version` 的 SHA 和 build 号，与要对比的版本核对。
- 机器是否独占：同机还有哪些集群、容器，以及它们的 cgroup 内存占用。共享机器会污染 OOM 和 RSS 数据。
- 实际生效的参数：用 `show all` 查 `vector.*`、`gp_interconnect_*`、`statement_mem`、`gp_vmem_protect_limit`、`gp_resource_manager`；确认没有被别人改过。
- 数据：规模（SF）、表格式、ANALYZE 的时间。
- 缓存状态：冷缓存还是热缓存。两组对比必须在同一状态下进行；冷缓存需要 `drop_caches`，属于 L4。
- 采集方式本身的影响：`EXPLAIN ANALYZE` 会改变计时；资源队列对超级用户不生效（`pquery.c` 中有 `!superuser()` 判断），用 gpadmin 测试时看不到准入排队。

**结果指纹**：先在基线上跑一遍并记录结果的 sha256。`sampler.py` 同时给出两个值：`sha_raw` 对行序敏感，`sha_sorted` 不看行序。之后每次 A/B、每个原型都要和它比对。查询没有 ORDER BY，或者输出浮点数时，比较 `sha_sorted`，并且两边要保持相同的 `extra_float_digits`。

**回归问题**：如果有一个好构建和一个坏构建，先在两个构建上各跑 2 轮以上，确认差异大于波动、确实可以复现，再按构建二分。确认差异的目的是排除环境噪声，否则二分出来的结果没有意义。

---

## 第 2 步：画计划 DAG（slice / Motion / CTE）

后面的每一步都要对照这张图来看。

- 用 `EXPLAIN (VERBOSE)` 列出每个 slice 扫哪些表、做什么 join 或 agg、发送和接收哪些 Motion、有没有 Shared Scan（CTE）、gang 有多大。
- 画成有向图：节点是 slice，边是 Motion。在边上标出估计行数，在节点上标出执行模式。执行模式要开 debug1 日志确认：push_pipeline / yield / batch，以及 VEC-YIELD-GUARD 是否命中。
- 每个 slice 一般有多个 QE（每个 segment 一个），所以 slice 级的数字是这些 QE 的合计或分布。

---

## 第 3 步：资源体检（USE，5 分钟内完成）

每类资源检查三项：利用率、饱和度、错误。目的是先找出哪类资源出了问题，避免一上来就钻进代码。

| 资源 | 利用率 | 饱和度 | 错误 |
|---|---|---|---|
| CPU | QE 的 CPU 秒、`mpstat -P ALL` | 运行队列（`vmstat r`）、PSI cpu、cgroup `cpu.stat` 中的 throttled、降频（`cpupower frequency-info`） | — |
| 内存 | QE 的 RssAnon、主机 MemAvailable | PSI memory、swap、page fault 速率、内存回收（`sar -B`）、cgroup `memory.events` | `dmesg` 中的 OOM killer、vmem 拒绝、`Out of memory` |
| 磁盘（spill / 扫描） | `iostat -x` 的 util；QE 的 `write_bytes` / `read_bytes` | await、队列长度、PSI io | IO 报错、磁盘满 |
| 网络（interconnect） | 网卡吞吐（`sar -n DEV`） | `ss -uanp` 中的 Recv-Q / Send-Q、softirq（`mpstat` 的 %soft） | `nstat -az` 中的 UdpRcvbufErrors / UdpInErrors；interconnect 重传和超时（`gp_interconnect_log_stats=on`，语句结束时打印 UDP-IC 统计） |
| arrow 线程池 | 每个 QE 的线程数、处于 R 状态的线程数（sampler 的 `thr` / `run`） | 全部 QE 的 R 线程之和超过核数 = 超订 | — |
| NUMA | `numastat -p <pid>` | 跨节点访存比例 | — |
| 准入 | 资源组的并发槽和 CPU（`gp_toolkit.gp_resgroup_status`） | 排队时间 | 被拒绝 |

注意：资源组的内存配额只决定算子的内存预算（`ResourceGroupGetQueryMemoryLimit`），而向量化的分配不经过 vmem 记账，所以资源组管不住向量化的 RSS（读代码得出）。它对并发数和 CPU 是有效的。

结论写成一句话，例如"内存饱和，CPU 未饱和，无 spill"，或者"CPU 利用率低，也没有 IO 等待 → 时间花在 off-CPU 等待上"。

---

## 第 4 步：时间序列与关键路径

脚本：`scripts/sampler.py --tag T --sql q.sql [--opts "-c ..."]`，详见文末脚本表。它会开一个新会话跑这条查询，每秒按进程采样以下指标：

- **内存**：RssAnon（不含共享内存）、VmHWM（内核记录的峰值，能抓到两次采样之间的尖峰，但包含共享页）；需要更准时加 `--pss` 采 Pss_Anon。主机 MemAvailable。
- **CPU**：utime+stime（只计这个进程启动以来的部分，新会话的 QE 都是本次运行期间启动的）；每秒差分换算成核数。
- **IO**：write_bytes / read_bytes（块设备层的读写，即 spill 和扫描）。
- **线程**：线程总数、R 状态线程数、主线程的 wchan。
- **主机**：PSI（内核没开 PSI 时为 `-`）。
- **等待事件**：sampler 不采。需要时另外查 `gp_stat_activity` 的 `wait_event`。

**`summary.txt` 怎么读：**
- **`peak_sum`**：对每个 slice，先在每个采样时刻把它所有 QE 的内存相加，再取这些和的最大值。不是把各 QE 各自的峰值相加（那些峰值不一定同时出现），所以可以直接做贡献分解。
- **`skew`**：同一 slice 内各 QE 的最大值除以中位数，内存和 CPU 各一列。
- **`busy`**：这个 slice 的 CPU 达到自身峰值 10% 以上的时间段。
- **标签**：每个进程整次运行只用一个标签，即它最后执行的 slice。QE 在 slice 前后空闲的那些时刻，也算在这个 slice 名下。整次运行中从未被采到 slice 标签的 QE 归入 `-/idle`，一般是一秒内就跑完的小 slice。SQL 文件里有多条会派发 slice 的语句时，同一个 QE 会先后执行不同的 slice，按 slice 拆分的数字就不准了，所以每次只跑一条主查询（`set` 语句不受影响）。

`plot.py <run_dir>` 输出 `curves.tsv`（有 matplotlib 时另出 png）。曲线来源是内存 Top N 和 CPU Top N 两个集合的并集。

**关键路径**：slice 之间是并行的，**耗时不能跨 slice 相加**。把每个 slice 的 busy 时间段画到第 2 步的 DAG 上：
- 某个 slice 在跑、下游在等 → 这个 slice 在关键路径上；
- 两个 slice 交替忙 → 它们之间是串行依赖（例如 C5：扫描和发送没有重叠）；
- 全部 slice 都闲、查询却没结束 → 转第 7 步（卡住）。

**曲线形状只用来提假设**：

| 形状 | 候选解释（每种都要用对照区分） |
|---|---|
| 开局就冲到平台，一直持续到结束 | 数据整体积压（上游跑完、下游还没取）；哈希表一次建满；固定的预分配 |
| 线性增长到结束 | 没有反压的队列；正常的哈希表增长；泄漏。区分方法：调整输入规模看斜率；重复执行同一语句，看语句之间 RSS 是否回落 |
| 锯齿形 | spill 或按批释放 |
| 一个 slice 长时间单核满载，其他 slice 空闲 | 单线程瓶颈或串行依赖 |
| CPU 低、耗时长、内存不变 | 在等待：网络、锁、CTE、反压。转第 6 步做 off-CPU 分析 |
| 全部为零、查询不结束 | 卡住，转第 7 步 |

---

## 第 5 步：专项检查

### 5.1 倾斜
- 用 EXPLAIN ANALYZE 的 avg/max（含 max 所在的 segment）；需要每个 segment 的明细时开 `gp_enable_explain_allstat=on`（实验性参数）。
- 判定：同一 slice 内 **max/median > 1.5，并且 max 与 median 的差值在绝对量上有意义**，比如几百 MB 或几秒。只看比例会把很小的数值也判成倾斜。采样里的 `skew` 列是同一个口径。
- 要做行数估计和实际行数的对比：偏差大说明统计信息过期，或者是计划问题（B 类）。

### 5.2 Motion / interconnect（按边看）
- 每条 Motion 边：发送行数（EXPLAIN ANALYZE）、发送方和接收方 slice 的 busy 时间段、接收方 slice 的内存（接收缓冲）。
- 网络错误：`nstat -az | grep -i udp`，跑查询前后各采一次做差。interconnect 的统计用 `gp_interconnect_log_stats=on`。
- 积压：`stacks.sh` 会列出 Recv-Q / Send-Q 不为 0 的 socket。
- 注意：向量化 EXPLAIN ANALYZE 里 Motion 的 first/last 时间不可靠，要以采样为准。

### 5.3 Spill 生命周期
- 写出：write 曲线上升的阶段。回读：read 曲线上升的阶段。看写和读是否交替进行（抖动），写出量和回读量是否成倍（同一数据反复 spill）。
- 预算：`vector.*_spill_memory_mb`；看预算是不是被平分到每个线程。
- 行引擎部分：`gp_toolkit.gp_workfile_usage_per_query`，EXPLAIN ANALYZE 中的 `Work_mem used/wanted`。

### 5.4 线程池与推模型
- 执行模式（第 2 步）。`vector.pool_threads`、`vector.enable_vec_pipeline`、`vector.backpressure_memory_mb`。
- 超订：所有 QE 的 R 线程数相加（`curves.tsv` 的 `threads_R` 列），与核数比较。
- 反压是否生效：debug1 日志里的 BP 和 VEC-YIELD-GUARD；Sink 队列持续增长说明反压没生效（见问题库 M3）。

---

## 第 6 步：下钻到代码（只对第 4、5 步挑出的 slice 做）

### 6.1 引擎自带的统计
- 向量化 EXPLAIN ANALYZE：每个算子的耗时和行数来自 arrow 的 time collector（`hook/executor.c`）。内存一栏只有 PG 内存上下文和 spill 的 `Work_mem`（`vec_spill_stats.c`），**看不到 arrow 池内和池外的分配**（读代码得出，尚未用实际输出核对）。
- debug1 日志：VEC-MEM（池峰值）、BP、VEC-YIELD-GUARD。

### 6.2 选哪种工具

| 想回答的问题 | 工具 | 注意 |
|---|---|---|
| CPU 花在哪里 | `flame.sh cpu` | 采样窗口要覆盖目标阶段：先看曲线，用 `-p` 指定进程，限定时长。默认用 dwarf 回溯：postgres 和 arrow 一般没有帧指针，用 fp 时大部分帧显示为 `[unknown]` |
| 比基线多出来的 CPU 在哪 | 两次 `cpu` 加 `flame.sh diff` | 两边的窗口和负载要可比 |
| 线程不在 CPU 上时在等什么，等了多久 | `flame.sh offcpu`（bcc，计的是时长） | 需要 root 和 BPF 编译环境；退而求其次用 `switches`，它只计次数：1000 次短等待会排在一次 30 秒等待前面 |
| 新增内存在哪里**被第一次写入** | `flame.sh faults` | 这是"首次触碰"的位置，不一定是分配者：池分配，扫描写入，记在扫描头上。要确认分配者，配合下一行。**只能在内存上涨阶段抓**：到了平台期，0 个样本是正常的 |
| 谁分配、谁没释放 | 分配采样：heaptrack，或 jemalloc prof（需替换分配器，L4）；`perf probe` 挂 malloc（L3，用 `nm` 取 mangled 名，匿名命名空间里的函数可能挂不上）。在两个时间点各采一次再做差 | 开销大，只对小规模复现做 |
| 内存是什么类型 | `/proc/<pid>/smaps_rollup`、`pmap -x` | 匿名内存还是文件映射；大块 mmap 还是 glibc 堆 |
| 已经 free 但没还给系统 | glibc `malloc_info` / `malloc_stats`（gdb 里调用，L3） | arrow 构建时关闭了 jemalloc 和 mimalloc（以构建配置为准） |
| IPC 低是因为访存还是指令多 | `flame.sh topdown`（自动列出本机支持的指标组）；`perf stat -e cycles,instructions,cache-misses,branch-misses` | 指标组名和支持情况因 CPU 而异，不要写死 |
| NUMA | `numastat -p`；`perf stat -e` 中的远端访存事件 | — |

内存的判定规则：
- RssAnon 远大于 arrow 池峰值 → 内存在池外：PAX 缓冲、interconnect 接收缓冲、PG palloc 或 glibc 保留。
- 两者接近 → 看池内哪个算子用得最多：哈希表、排序、聚合。
- 首次触碰的调用栈落在扫描、解码或 `StartProducing` 下 → 扫描输出积压（候选，见问题库 M1）。
- 落在 interconnect 接收路径 → 和队列参数有关（候选，见问题库 M2）。

### 6.3 插桩
静态读代码推不出来时，用项目自带的日志接口（`elog(DEBUG1, ...)` 或 arrow 日志）打印关键变量和所走分支。用二分法缩小范围，直到定位到具体某一行、某一个值。

---

## 第 7 步：卡住

1. 查 `gp_stat_activity` 的 `wait_event`、`state`、`query_start`。
2. `stacks.sh <sess_id> 3 10`：每隔 10 秒抓一次所有 QE 的栈，共 3 次。progress.txt 给出各 slice 的 CPU 增量和主线程栈是否变化。**只有 CPU 没增长、栈没变化、socket 队列也没有消化，三者同时满足时，才能判为卡住**。单次快照只是瞬时状态，什么也证明不了。
3. 画等待图（谁在等谁），看是否成环。例如：CTE 读端等写端 → 写端等 Motion 接收 → Motion 发送方等读端。`threads.txt` 列出了每个线程的栈顶，可以看到非主线程在做什么。
4. 用内核数据佐证：Recv-Q 有数据却没人读，说明接收方在等别的东西。
5. 再用最小复现验证这个环：去掉其中一条边（关掉某个模式或参数），卡住就应该消失。

---

## 第 8 步：并发

1. **负载模型**：流数、每个流的查询顺序、是否同时开始、持续多久。和线上目标负载一致才有意义。
2. 先单跑每条查询，记录峰值和耗时；再按负载模型并发跑。
3. 判断峰值约等于单跑峰值之和（简单叠加），还是远超（相互干扰，例如 glibc 保留跨语句累积、线程超订）。
4. 失败分类：OOM killer（`dmesg`，看 task_memcg 确认是谁的 cgroup）、vmem 拒绝、连接被拒、崩溃（core + gdb）、语句超时。
5. 准入和排队：资源组的并发槽、排队时间。内存上的仲裁见第 3 步的注意事项。
6. 对占用最大的几条查询，分别走第 4 到 6 步。

---

## 第 9 步：归类

| 类别 | 特征 | 怎么验证 | 例子（问题库） |
|---|---|---|---|
| **E. 环境** | 换机器或隔离后现象消失或改变 | 同机负载、cgroup、NUMA、降频、磁盘 | E1 |
| **F. 数据** | 倾斜；统计过期；数据量与预期不符 | max/median 加绝对量；ANALYZE 时间 | — |
| **A. 参数** | 换 GUC 后现象明显变化，代码行为符合设计 | 会话级 `PGOPTIONS` 做 A/B（第 10 步） | M2 |
| **B. 计划** | 引擎不变，换计划形状后资源大幅变化；行数估计偏差大 | EXPLAIN ANALYZE 估计行数对比实际行数；强制改计划后 A/B | C4 |
| **C. 引擎结构** | 设计上缺少某种机制，调参调不动 | 读代码确认机制缺失，再做原型验证 | M1、C2、S1 |
| **D. 缺陷** | 行为与设计意图不符，能构造最小复现 | 最小复现，再用 gdb 或日志定位到具体行 | C1、M4 |

- 排查顺序：E → F → A → B → C/D，先便宜后昂贵。
- 一个问题可以同时属于多类，各自都要量化（第 10 步）。

---

## 第 10 步：量化与实验设计

**每个原因回答一个问题：把它去掉能省多少。**
- 参数类：A/B 的差值。
- 结构类和缺陷类：原型或补丁前后的差值。没有原型时，可以用采样估一个上限，但要标明"上限估计"。

**A/B 设计**（`ab.sh` 已经按以下方式实现）：
- 先预热，预热的那次不计入；
- 顺序按 AB、BA、AB……交替，避免某一边总是用上另一边刚热好的缓存；
- 每边至少 3 轮。轮数按波动决定：差值小于组内波动时，要么加轮数，要么不下结论；
- 报告每一轮的原始值，以及中位数和组内波动；
- 只统计成功的轮次，所有成功轮次的结果 sha 必须一致；
- 时间精确到毫秒。

**交互作用**：多个因素（反压、spill 预算、interconnect 参数）之间可能互相影响，单独量化的贡献加起来不一定等于总量。
- 两个因素都可疑时，做 2×2 实验（4 种组合），分别算出各自的单独贡献和交互项。
- 汇总表里各项加起来和总量差得多时，说明还有没找到的原因，或者存在交互作用，要写出来，不要硬凑。

---

## 第 11 步：输出文档

```
# <查询或场景> <现象> 分析

## 结论（3–5 行）
主要原因 / 类别 / 可省多少 / 建议 / 置信度

## 问题陈述
环境（机器、构建号、SF、并发、关键 GUC）、现象和期望（给数字）、复现方式、结果指纹

## 计划 DAG 与关键路径
slice / Motion / CTE 图；每个 slice 的 busy 时间段

## 资源体检
USE 表，结论用一句话写

## Top slice
slice / 做什么 / peak_sum / 单 QE 最大值 / 倾斜 / CPU 秒 / spill / 线程；曲线

## 根因（每个原因一节）
类别；因果链；证据 1、证据 2（采样、火焰图、A/B、代码位置）；
置信度：已证实（两条独立证据，含 A/B 或原型）/ 很可能（一条直接证据）/ 推测

## 贡献量化
原因 → 可省多少 → 验证方式 → 各轮原始数据 → 交互作用说明

## 建议
立即可做（调参，附适用条件）；需要改代码（位置、预期收益、风险、验证范围）

## 未验证 / 遗留

## 问题库候选条目（由人决定是否写入）
```

---

## 第 12 步：问题库候选条目

报告末尾给出候选条目，**不要直接修改** `references/known-patterns.md`，是否写入由人决定。

条目格式：现象（候选信号）→ 类别 → 判定（需要哪两条证据）→ 适用条件 → 修复方向 → 案例（写进 `references/cases.md`）。

新问题先按"现象"对照问题库。命中后，再按条目里的"判定"重新验证。

---

## 工具缺口（建议在引擎侧补齐）

参照 Velox OperatorStats、DuckDB profiling、ClickHouse ProfileEvents / MemorySample：
- 每个算子的 CPU 时间、墙钟时间、阻塞时间（按原因分：等 Motion、等 CTE、等反压），输出和输入的行数、批数、字节数，内存峰值，spill 字节数和次数，并能在 EXPLAIN ANALYZE 中看到；
- 池外内存的统计：PAX 缓冲、Sink 队列、interconnect 缓冲；
- 带调用栈的分配采样（MemorySample）；
- 按 Motion 边统计：行数、字节数、发送方和接收方各自的阻塞时间；
- 线程池统计：活跃线程数、排队任务数、反压暂停和恢复的次数。

---

## 脚本

都在 segment 所在主机上，以数据库 OS 用户运行。只使用会话级参数，不改配置，不重启。多主机集群要在每台主机上各跑一份 sampler。

| 脚本 | 用法 | 级别 | 说明 |
|---|---|---|---|
| `qe_pids.py` | `--con N [--port] [--db]` | L0 | 列出本集群、本会话、本主机上的 QD/QE 进程：pid、slice、cmd |
| `sampler.py` | `--tag T --sql q.sql [--opts "-c ..."] [--port] [--db] [--out ./runs] [--interval 1] [--timeout 1800] [--max-out-mb 200] [--pss] [--allow-write]` | L1 | 输出 `out.txt`、`err.txt`、`series.jsonl`、`summary.txt`、`result.json`；查询失败时退出码为 1 |
| `ab.sh` | `ab.sh q.sql "<opts A>" "<opts B>" [轮数=3] [out]`；环境变量 `WARMUP=1`、`TIMEOUT`、`INTERVAL` | L1 | 预热后按 ABBA 顺序交替跑；输出各轮原始值、中位数、组内波动、结果 sha 是否一致，并判断差异是否超出波动 |
| `plot.py` | `plot.py <run_dir> [--top 8]` | L0 | 输出 `curves.tsv`（另含主机内存、PSI、R 线程数）；有 matplotlib 时另出 png |
| `stacks.sh` | `stacks.sh <sess_id> [次数=3] [间隔=10] [out]`；环境变量 `JOBS=8` | **L3** | 多次抓栈，判断有没有进展，列出 socket 积压；会暂停进程，CPU 开销大 |
| `flame.sh` | `cpu / switches / faults / offcpu <pid> <秒> [out]`；`topdown <pid> <秒> [指标组]`；`diff a b` | L2 | 需要 root 的模式加 `SUDO=sudo`；有 `$FLAMEGRAPH` 时才生成 svg，否则只留原始文本 |

更具体的 perf 用法可参考 `perf-tools:perf-profiling` skill（有就用，不是必需的）。
