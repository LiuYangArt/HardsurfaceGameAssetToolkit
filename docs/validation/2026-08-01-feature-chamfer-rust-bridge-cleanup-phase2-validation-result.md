# Feature Chamfer Rust Bridge 清理 Phase 2 验证结果

日期：2026-08-01
状态：`PROTOTYPE / PASS`

## 1. 目标与范围

验证 39 条已修改 chain 的 Rust/PyO3 单次批量双向最大偏差是否与 Python oracle 逐值、阈值判断等价，并达到至少 70% 内核降幅。仅为旁路原型；正式 runtime 始终为 Python。未修改正式入口、Python 生产算法、阈值、排序、BMesh、Bridge/Fill、Boolean、dissolve 或 `auto_load.py`，未生成/读取图片，未 commit/push/合并。

## 2. 冻结合同与输入

- 基线：`a59adbf6a6aaf675395645c1643033df69c177b2`，detached worktree。
- 环境：Blender `5.2.0 LTS` / Python `3.13.13` / Windows x86-64；Rust/Cargo `1.92.0`；PyO3 `0.29.0`；release/MSVC。
- 固定输入：Mixed fixture / `Extruded.002` / Radius `0.01`。
- 来源链路：Phase 1 正式 Operator 的 `optimized/run-01/result.json` → `deviation_replay`。driver 只包装生产函数；121 条无修改 chain 已短路，不进入 replay。
- 筛选规则：`merged_vertex_count != 0 OR dissolved_vertex_count != 0`；与过滤后的 `cleanup_records` 同序核对，共 39 条。
- fingerprint：replay `cdfc8b287a90d0c7c4bdb76bdfd35da8d7f4e86f8c26a60b0a5c4e379699921e`；来源 result `10bb38604230a27fb051e0b6040b92b4ad6e857582fcca9698b5f6ef134c1051`。
- 输入摘要：source/cleaned 坐标 `1869 / 1619`，点到线段求值 `216322`。
- 当前 Blender 用生产函数体和 `mathutils.Vector` 重算两次：39/39 稳定，并与来源记录 39/39 exact。Python 批量内核中位 `0.0603242s`（callable 只加载一次，31 次）。

## 3. 分阶段结果

### 阶段一：合同与 replay 前置审计

- 状态：`PASS`。
- 第一处差异：无。
- 证据：`contract.json`、`phase1_replay_source.json`、`python_oracle.json`。

曾用系统 Python tuple/f64 仿写代替 Blender `mathutils.Vector`，仅 13/39 exact。该轮输入/执行语义不同，已 `REJECTED`，未作为 oracle。

### 阶段二：Rust/PyO3 旁路原型

- 状态：`PROTOTYPE / PASS`。
- 独立 crate；一次 PyO3 批量调用；release `.pyd` 仅放 artifact；未接正式包或业务入口。
- Cargo tests：3/3 PASS（open/cyclic identity、短链 inf、退化 segment）。

### 阶段三：数值语义审计与 round 4

- 状态：`PASS`。
- round 3 曾为 `STOP`：38/39 exact，唯一首差 chain 10。
- chain 10 的最大值来自 `source_to_cleaned`：source 点 `59` 到 cleaned segment `57`。
- 对 point/start/end、segment、`length_squared`、dot、factor、`segment*factor`、projection、delta、length 的分量和 float bits 做逐步对照。首个差异出现在 `length_squared`：Blender `3f44006bfd000000`，旧 Rust `3f44006bfe9a2000`；根因是旧 Rust 用 f64 展开点积，未复现 `mathutils.Vector` 的 float32 向量存储与内部累加/返回语义。
- round 4 复现 float32 Vector 的减法、点积、长度平方和标量乘法，同时保留最终 Python scalar/length 的对应语义。虽然 `length_squared`/dot 返回值低位仍因库内部实现不同，但决定结果的 projection、delta、distance float bits 已与 Blender 一致；39 条最终 deviation 达到 39/39 exact。
- round 3 已标 `SUPERSEDED`，完整首差仍保留在 `native_comparison-round3-superseded.json`。

### 阶段四：阈值、fallback 与性能

- 状态：`PASS`。
- deviation：`39/39 exact`；第一处差异：无。
- 阈值判断：`39/39` 一致。
- 单次批量调用：PASS，无逐 chain/逐点跨语言往返。
- Python 批量中位：`0.0603242s`。
- 纯 Rust 批量内核中位：`0.0009798s`，下降 `98.38%`。
- Python→PyO3 单次调用端到端中位：`0.0010765s`，下降 `98.22%`。
- native 缺失：Python replay 39/39 PASS；正式 runtime 未接 native，始终 Python。

## 4. 审计记录

- round 1 `REJECTED`：Rust 直接消费 JSON f64，而 Python 先进入 float32 `mathutils.Vector`，输入精度语义不一致。
- round 2 `SUPERSEDED`：复现 float32 坐标存储，但错误地把全部 scalar/length 运算降为 f32。
- round 3 `SUPERSEDED`：38/39 exact；chain 10 中间量审计后由 round 4 替代。
- round 4 `PASS`：39/39 exact、阈值 39/39、两组性能降幅均超过 70%。
- 工具/编译命令错误均只记日志，不构成实验结论。
- 使用过的禁止机制：无。

## 5. 最终结论

Phase 2 Rust 旁路原型达到 Go 门槛：同一冻结输入上 deviation 和阈值判断完全一致，单次批量调用，纯 Rust 与 Python→PyO3 端到端中位降幅均超过 98%，native 缺失时 Python replay 完整通过。

此结论只支持 `PROTOTYPE / PASS`。正式 runtime 仍为 Python；未授权、未执行 Phase 3 集成，更未接 `auto/native` backend。

## 6. Artifacts

- 合同/环境：`contract.json`、`environment.json`
- 输入/oracle：`phase1_replay_source.json`、`python_oracle.json`
- chain 10 审计：`chain10_mathutils_audit.json`、`chain10_trace_comparison.json`
- 最终对比：`native_comparison.json`
- 历史：`native_comparison-round1-rejected.json`、`native_comparison-round2-rejected.json`、`native_comparison-round3-superseded.json`
- 时序：`timings.json` 与历史 timings
- fallback：`fallback_matrix.json`
- 构建产物：`_hst_feature_chamfer_native_prototype.cp313-win_amd64.pyd`
- 日志：`logs/`
