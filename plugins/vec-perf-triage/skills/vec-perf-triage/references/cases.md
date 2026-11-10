# 案例与机器记录

这里存放具体数字和机器信息，供 `known-patterns.md` 引用。
数字只在当时的构建、数据和机器上成立。引用时注明日期，不能当作门限。
团队内部的机器地址、目录、issue 链接不在这里，按团队自己的记录查。

## 机器类型

### ARM 测试机（单主机 32 primary）
- 鲲鹏（HiSilicon TaiShan-v110），单主机 32 个 primary，约 500 GiB 内存，内核 5.14（el9），perf 5.14。
- `TopDownL1/L2/L3` 指标组可用。2026-11 实测 L1：retiring 0.43 / bad_spec 0.03 / backend 0.37 / frontend 0.17。
- PSI 没开（`/proc/pressure` 不存在）；没装 matplotlib 和 FlameGraph 脚本。
- tracefs 只有 root 能访问（权限 700），`flame.sh switches/offcpu` 要加 `SUDO=sudo`；加 sudo 后 bcc offcputime 可用。
- 同一台机器上还有别人的集群，测量前先确认它们是否空闲，不要碰别人的集群。
- `stacks.sh` 的代价：33 个进程、`JOBS=8` 时，每次快照墙钟约 15 秒、CPU 约 12 分钟，几乎全花在 gdb 加载符号上。

### 共享开发机
- 同机有别人的 docker 集群在跑重负载，cgroup 峰值达到 483G。测内存前先查对方 cgroup 的 `memory.current`，OOM 时用 task_memcg 区分是谁触发的。

## 案例

| 编号 | 日期 | 场景 | 数字 |
|---|---|---|---|
| M1 | 2026-11 | TPC-DS 1TB q23 | slice5 单 QE 从 2.14G 降到 0.21G（加 yield 原型后）；全部 QE 峰值之和从 375/371G 降到 313/307G；耗时不变，结果一致。当时 slice 级数字是"各 QE 峰值之和"，属于上界 |
| M2 | 2026-11 | q23，队列深度 1024 + 64K 包 | 峰值之和从 375G 涨到 446G；slice1 单 QE 从 4.07G 涨到 6.35G |
| M3 | 2026-09 | Iceberg q09 / q18 | 打开 pipeline 后，q09 从 OOM 变为 283s 跑完，快于行引擎；不开时扫描输出堆积到 13.4GB/QE |
| M4 | 2026 | 小查询固定开销 | HT 初始目录从 8MB 改为 128KB，单 QE 从 830MB 降到 15MB |
| M5 | 2026 | q23 之后的会话 | 空闲时单会话 RSS 105–210G |
| C1 | 2026 | TPC-H 慢 3.3 倍；q18 慢 4.66 倍 | 预算被平分成 1/129，每份约 4MB；RebuildDirectory 占 70% CPU |
| C2 | 2026 | q19 | PAX 和 Iceberg 都慢 1.26 倍，多出约 17 秒 |
| C3 | 2026 | q24 | 打开 pipeline 后 CPU 多 38%，每批约 2.2 万行 |
| C4 | 2026 | q24 | 强制两阶段 agg 后为 0.98 倍；q23 / q78 触发了 OOM 保护 |
| S1 | 2026 | q75 / q14 / q58 | 卡住，CPU 约 3%，一直到语句超时；后来加了 VEC-YIELD-GUARD 规避 |
| S2 | 2026 | q31 / q74 / q79 | 没有线程池、又打开反压时卡住（`BuildSink` 中的例外） |
| M7 | 2026-11 | TPC-DS 1TB q23a（带 CTE，全部 slice 为 batch 模式） | 峰值 359G 中：slice2（扫描 + join item + substr）91G，按每行约 42B × 6878 万行/QE 估算与实测 2.87G/QE 一致；slice5（纯扫描）68G；slice9（扫描 + join date_dim）58G。早先的 slice5 yield 原型把单 QE 从 2.14G 降到 0.21G。按 slice 放开 guard 的整体收益尚未验证 |

## memattr 案例：q23a 各 slice 的函数级拆分（2026-11-10，ARM 测试机）

| slice | 内存 | 算子 | 函数（占该 slice 新增内存） |
|---|---|---|---|
| slice1 | 128G（单 QE 停在 4.01G = `sonicagg_spill_memory_mb`） | SonicHashAgg | `sonic::RowTable::AddBlock` 58%（新块整块 memset），`ScatterColumn` / `ScatterStringImpl` 39% |
| slice2 | 91G | HashJoin 探测输出 63% | `DecodeSelectedInternal` 51–55%，`ExecBatchBuilder::AppendSelected` 4% |
| | | Project 25% | `StringTransformExec<SliceCodeunitsTransform>`（substr） |
| | | PAX 扫描 12% | `pax::SyncFastIO::read`、`DataBuffer::Write` |
| slice5 | 68G | PAX 扫描 99.9% | `pg_short_numeric_to_vec_short_numeric` 55.5%（numeric(7,2) 转成 16 字节），ZSTD 解压 21%，`DataBuffer::Write` 12.5% |
| slice9 | 58G | PAX 扫描 74% | numeric 转换 53% |
| | | HashJoin 探测输出 26% | `ExecBatchBuilder::AppendSelected` 23.6% |

- 覆盖率（采样字节 ÷ RssAnon 增量）：slice5 89%、slice1 87%、slice9 62%、slice2 34%。slice2 那个窗口有约 2/3 的增长没有以 4K 缺页出现，MB 列是按比例推算的。这台机器的 THP 为 always，可能是大页，也可能是 mremap 扩容；当时没有记录 AnonHugePages，原因未确认（之后 memattr 已经会记录）。
- slice9 发送完后的内存是 glibc 保留：对 32 个 QE 调 `malloc_trim(0)` 后从 58.3G 降到 0.65G，整体峰值从 359G 降到 300.6G，耗时不变。
- `sonicagg_spill_memory_mb` 从 4096 改为 2048（各 2 轮）：峰值 358.7G → 295.7G，耗时 184s → 246s（+33%），spill 写出 4.2G → 70.8G。这个参数和 `hashjoin_spill_memory_mb`、`winagg_spill_memory_mb` 都按**每个算子、每个 QE** 计，默认都是 4096，不是整条查询的总量。q23 的 HashJoin 哈希表远小于上限，调 `hashjoin_spill_memory_mb` 没有作用。
- slice1 每组约 590 字节，比按 schema 估算的大好几倍，原因未查清。

## 脚本验证记录
- 2026-11-10，ARM 测试机，q23a 完整流程跑了 2 遍（基线构建）：
  - 耗时 190.5s / 184.7s；峰值 359.0 / 358.8 GiB（t≈97s）；结果 sha 一致；MemAvailable 最低 114.5 GiB。
  - 新口径（每个时刻先求和，再取峰值）：slice1 128G、slice2 91G、slice5 68G、slice9 58G。旧口径（各 QE 峰值相加）下 slice2 是 182G（n=64），是新口径的两倍，所以旧的 slice 级数字只能当上界。
  - slice5 的 busy 是 2–183s，内存开局就到平台（与 M1 一致）。在 t=25–35s 抓 page-fault 得到 0 个样本，因为已经错过了内存上涨阶段；这时它的 CPU 约 50% 在 `SendTupleVec`。
  - fp 回溯下 92% 的帧是 `[unknown]`；改用 dwarf 后降到 31%，热点（ZSTD 解压、`pax::...MaterializeAll`）能看清。
- 2026-11-10，同一台机器，`store_sales` 小查询（命中 1900 万行）：
  - sampler：耗时精确到毫秒；空闲 QE 不再重复计数；写语句被拒绝；查询失败时 status=FAIL、退出码为 1。
  - ab.sh：预热后按 ABBA 交替，向量化开 6.3s、关 18.2s，组内波动 1–2%，结果 sha 一致。
  - stacks.sh：对 pg_sleep 会话抓 2 次，正确判定为"无 CPU 增长、栈无变化"。
  - flame.sh：cpu 和 topdown 不需要 sudo；switches 和 offcpu 需要 `SUDO=sudo`。
- 2026-11-10，同一台机器，memattr：
  - 对 q23a 已有的 4 个窗口离线重跑 `opattr.py`，结果和手工分析一致（见上面的案例表）。
  - 实跑：`store_sales` 300 天范围按 (customer, item) 聚合，19.4s。在 slice1 上涨窗口（t=10–15s）跑 memattr：RssAnon +533MB，覆盖率 106%，SonicHashAgg 97.2%（`AddBlock` 67.5%，`ScatterColumn` 20.7%）。不需要 sudo。
  - 同一条查询窗口放在 t≈2–8s 时 slice1 还没开始工作，得到 0 个样本，符合"只能在上涨阶段抓"。
