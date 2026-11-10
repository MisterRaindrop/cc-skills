# 内存归因完整示例：TPC-DS 1TB q23a（ARM 测试机，单主机 32 segment，2026-11-10）

这是 SKILL.md 6.3 节的完整示例，演示报告应该细到什么程度：每个大 slice 一棵调用树（从算子入口一直到底层写内存的函数），一张"首次写入 vs 持有"对照表，然后对占比高的函数逐个追到代码和根因，并用对照实验验证。
数字只在当时的构建、数据和机器上成立。

## 0. 整体

峰值 359G（t≈98s），结果 sha 和基线一致，耗时 186s。

| slice | 峰值 | 做什么 | 执行模式 |
|---|---|---|---|
| slice1 | 128G | SonicHashAgg（frequent_ss_items：GROUP BY substr(i_item_desc,1,30), i_item_sk, d_date） | batch（查询带 CTE） |
| slice2 | 91G | 扫 store_sales ⋈ date_dim ⋈ item，substr，发给 slice1 | batch |
| slice5 | 68G | 纯扫 store_sales 3 列（customer_sk, quantity, sales_price） | batch |
| slice9 | 58G | 扫 store_sales ⋈ date_dim；发送完后由 glibc 保留 | batch |
| 其余 | ~14G | — | — |

## 1. 调用树（memattr --tree，GiB = 占比 × slice 峰值）

### slice1：SonicHashAgg

```
96.2%  123.1G  SonicGroupByNode::InputReceived > LocalAggregator::Sink
83.1%  106.4G    LocalAggregator::AppendEmptyGroups               新分组写入行表
43.4%   55.6G      ScatterColumn                                  分组键写入
27.1%   34.7G        ScatterStringImpl                            字符串键（30B，>12B 进 heap）
24.6%   31.5G          __memcpy_generic
16.3%   20.9G        sonic::ScatterColumn（定长键 self 14.5%）
39.7%   50.8G      RowTable::AppendRow > RowTable::AddBlock       新开 256KB 行块
39.0%   50.0G        __GI___memset_kunpeng                        整块清零
11.9%   15.3G    RowMatcherAdapter::MatchKeys > duckdb::RowMatcher::Match > TemplatedMatch
                                                                  只读比较；可能是零页读缺页，见注意事项
 1.1%    1.4G    UpdateAggregates > CountStarAggregate::Update
 2.1%    2.7G  Motion 接收（rxThreadFunc > recvfrom；GetRecordBatch > prepareRxConnForRead）
 1.6%    2.0G  Sort：addChunkToSorter > materializeChunk > memcpy
```

### slice2：HashJoin(⋈item) → Project(substr) → Sink

```
61.6%  56.1G  HashJoinNode::OnProbeSideBatch > SwissJoin::ProbeSingleBatch > JoinProbeProcessor
57.7%  52.6G    JoinResultMaterialize::Flush > FlushBuildColumn > RowArray::DecodeSelected
51.1%  46.6G      DecodeSelectedInternal::lambda > SafeStore      build 侧（item）列解码，含完整 i_item_desc
 3.6%   3.3G    JoinResultMaterialize::Append > ExecBatchBuilder::AppendSelected   probe 侧列
27.4%  25.0G  ProjectNode > ExecuteScalarExpression > StringTransformExec<SliceCodeunits>
12.9%  11.8G    PoolBuffer::Resize > BaseMemoryPoolImpl::Reallocate > memcpy   shrink_to_fit 拷到新缓冲
11.3%  10.3G    ExecArray > SliceForward > std::copy > memmove                 写进超额分配的缓冲
10.8%   9.8G  PAX 扫描：SyncFastIO::read > pread 5.8G；DataBuffer::Write 2.0G；ZSTD 1.5G
```

### slice5：纯 PAX 扫描

```
98.0%  66.7G  PaxRecordBatchGenerator::Next > PaxVecReader::ReadBatch
94.3%  64.1G    VecAdapter::AppendToVecBuffer > AppendPorcFormat
55.6%  37.8G      pg_short_numeric_to_vec_short_numeric          numeric(7,2) → 16 字节
15.0%  10.2G      PaxNonFixedEncodingColumn::MaterializeAll > ZSTD_decompress（self 9.2G，HUF 1.0G）
12.4%   8.4G      CopyFixedBuffer > DataBuffer::Write > memcpy    两个 int 列
10.3%   7.0G      PaxEncodingColumn::MaterializeAll > ZSTD_decompress（self 4.2G，HUF 2.7G）
 3.4%   2.3G    OrcReader::ReadGroup > PaxDeltaDecoder::Decoding
```

### slice9：PAX 扫描 + HashJoin(⋈date_dim)

```
73.5%  42.9G  PaxVecReader::ReadBatch
58.4%  34.1G    AppendPorcFormat > pg_short_numeric_to_vec_short_numeric
 9.8%   5.7G    ZSTD（两类列合计）
26.5%  15.5G  JoinResultMaterialize::Append > ExecBatchBuilder::AppendSelected > SafeStore  probe 侧列复制进输出
```

覆盖率（采样字节 ÷ RssAnon 增量）：slice1 和 slice5 约 0.9–1.06；slice9 0.60（AnonHugePages 占增长 20%）；slice2 0.35–0.38（AnonHugePages 占增长 51–62%）。

## 2. 首次写入 vs 持有（行宽核对）

| slice | 每行留在 Sink 里的列 | 估算 | 实测 | 持有构成 | 调用树里 |
|---|---|---|---|---|---|
| slice5 | 4B + 4B + numeric 16B = 24B，约 9000 万行/QE | 2.2G/QE | 2.14G/QE | numeric 约 67%（~45G），int 约 33%（~23G） | numeric 55.6%，int 12.4%，ZSTD 25%（临时缓冲，不持有） |
| slice2 | substr 30B + 偏移 4B + item_sk 4B + d_date 4B = 42B × 6878 万行/QE | 2.9G/QE | 2.87G/QE | substr 约 81%（~74G），两个 int 约 19%（~17G） | join 解码 62%，substr 27% |

slice2 偏差的原因：join 解码的完整 i_item_desc（实测平均 100.5B）只是 substr 的输入，用完即弃，但每批都重新缺页；substr 的大缓冲也是临时的（见 3.3）。所以这个 slice 的调用树只说明内存在哪里被写，持有构成以行宽为准。

## 3. 占比高的项逐个追根因

### 3.1 slice1：SonicHashAgg 128G → 分组被重复存了约 9 倍（候选 M8）

- **算术**：EXPLAIN ANALYZE 中 HashAgg 输出 6.83M 组/QE（HAVING 之前），输入 6878 万行/QE。行布局（`row_layout.cc`）：null 位图 1B → 对齐到 8，字符串键 16B（string_t），i_item_sk 4B，d_date 4B，count 8B = **40B/行**，另外 30B 字符串进 heap。不重复时约 6.83M × 70B ≈ 0.48G/QE，实测在 4.0G 的 spill 上限顶满，还 spill 了 131MB/QE。**约 8.9 倍。**
- **代码**：`local_aggregator.cc` 的 Sink 里 `if (hash_table_.IsFull(count)) { hash_table_.Abandon(); }`，注释写"Don't grow hash table ... Finalize will merge repeated rows"。目录固定为 `kDefaultHTCapacity = 1<<20`，密度超过 2/3（约 69.9 万项）就清空目录、**保留所有行**。之后再出现的同一个分组会被当作新组，再存一行，到 finalize 才合并。
- **推论**：重复程度不取决于分组数，而取决于同一分组的行在输入里有多分散：分组跨越的 abandon 轮次越多，就会被存越多次。
- **对照实验**（同一输入：store_sales 300 天，15.45M 行/QE；只改 GROUP BY 键；slice1 单 QE 的内存，基线 0.09G）：

| 键 | 组/QE | 行在表中的分布 | slice1/QE | 相对基线增量 |
|---|---|---|---|---|
| ss_item_sk | 9.4K | — | 0.09G | 0 |
| ss_customer_sk | 365K（< 69.9 万） | — | 0.09G | 0 |
| ss_ticket_number | 1.35M | 同一票据的行相邻 | 0.09G | 0 |
| ss_customer_sk, ss_sold_date_sk | 1.34M | 基本相邻 | 0.09G | 0 |
| **ss_item_sk, ss_sold_date_sk** | **1.40M** | **分散** | **0.28G** | **+0.19G ≈ 680 万行，约 4.9 倍** |
| ss_ticket_number, ss_item_sk | 15.45M（全不同） | — | 0.53G | +0.44G（每行约 28B 的标尺） |

  组数相同（1.35M 对 1.40M），只有分布不同，内存差 0.19G。q23 的键 (substr, item, date) 正是分散型。
- **置信度**：很可能。证据有两条：算术和对照实验。还缺直接计数：`groups_created_` 计数器存在，但没有输出，要加日志才能拿到。
- **修复方向**：分组重复率高时（例如上一轮 abandon 的命中率很低）把目录翻倍扩容，设一个上限，比如 16M 项、128MB。按估算，slice1 可从 4G/QE 降到约 0.6G/QE（128G → ~20G），并且不再 spill、finalize 不用再合并大量重复行。**这是未验证的估算，需要改 arrow、重新编译。**

### 3.2 slice5 / slice9：numeric(7,2) 每个值占 16 字节

- **代码**：`pax_porc_adpater.cc` 的 numeric 分支：`type_len = VEC_SHORT_NUMERIC_STORE_BYTES`（16B）；精度不超过 `VEC_SHORT_NUMERIC_MAX_PRECISION`（35）的都存成 128 位，没有 64 位的 decimal。
- numeric(7,2) 用 int64（甚至 int32）就能装下。slice5 持有的 numeric 约 45G，改成 8B 可省一半（~22G）；slice9 也类似。需要向量化引擎支持窄 decimal，改动大。
- 顺带发现：对短头 numeric，每个值都 `VarlenaShortTo4B`，即 malloc + free 一次。这是 CPU 开销，不影响内存。
- 更直接的办法是 M7：Sink 有了上限之后，这些行本来就不会积压。

### 3.3 slice2：substr 先超额分配，再整块拷贝

- **代码**：`scalar_string.cc` 的 `StringTransformExec::Exec`：按 `MaxCodeunits` 分配 = min(输入字节数, 4 × 30 × 行数)，i_item_desc 平均 100.5B，所以每行约分配 100B；写入 30B 后 `Resize(..., shrink_to_fit=true)`，由 `Reallocate` 整体拷贝到新缓冲。
- 也就是 SliceForward 写的是一块临时大缓冲，Reallocate 再拷一次；真正持有的是缩小后那块，每行 30B。
- 上游的 join 先把完整的 i_item_desc（约 100B/行）解码进输出，Project 再截成 30B。如果计划能在 build 侧（item，30 万行）先做 substr，join 就只需要解码 30B。这能省临时内存和 CPU，但持有量不变。

### 3.4 汇总：可省多少（都是估算，未验证）

| 方向 | 作用的 slice | 估算可省 | 代价 |
|---|---|---|---|
| M7：VEC-YIELD-GUARD 按 slice 判断，产出方走 yield 并启用有上限的 Sink | slice2/5/9 | 大部分，~200G；slice5 原型实测单 QE 2.14G → 0.21G | 改执行器，回归会卡住的那几条查询 |
| M8：sonic 目录在重复率高时扩容 | slice1 | ~100G（128G → ~20G），并去掉 spill | 改 arrow sonic |
| numeric 窄存储 | slice5/9 | ~30–40G（仅在 M7 之前有意义） | 类型系统改动，大 |
| `sonicagg_spill_memory_mb` 4096 → 2048 | slice1 | 63G（实测） | 耗时 +33%（实测） |

## 4. 注意事项（本例里踩到的）

- 透明大页（always）让 slice2 一半以上的增长看不见；memattr 会打印 AnonHugePages 增量和覆盖率。
- `RowMatcher::Match` 只读，却占 11.9%：读到还没写过的匿名页会映射零页，不增加 RSS。这部分可能被高估。
- 同一窗口两次运行，函数级比例会漂移（AddBlock 59% 对 40%），算子级稳定。
- 带 `%` 运算的 GROUP BY 键会让这条查询退回行引擎（计划里没有 Vec 前缀）。做对照实验前要先看 EXPLAIN，并带上和原查询相同的 `set` 语句。
