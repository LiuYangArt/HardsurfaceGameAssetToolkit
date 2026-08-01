# Feature Chamfer FeatureGraph Rust 紧凑接口验证结果

日期：2026-08-01
状态：`PROTOTYPE / PASS`（正式集成未授权）

## 1. 结论

- 固定 Mixed / `Extruded.002` / Radius `0.01` / 正式 UI `hst.feature_chamfer_gn`。
- 紧凑接口具备正式集成验证价值：端到端中位从 Python `1.026091s` 降至 `0.131558s`，下降 `87.18%`，绝对节省 `0.894533s`。
- Phase 0、1A、1B 全部 PASS；Phase 1C 判断为 `PROTOTYPE / PASS`。只说明值得另建正式 Operator A/B 集成计划，不授权接正式入口。
- 首处语义差异：无。正式 runtime、默认后端、算法、阈值、排序、BVH、`auto_load.py` 均未修改。

## 2. 冻结合同

- 环境：Windows x86-64；Blender 5.2.0 LTS / Python 3.13.13；Rust 1.92.0；PyO3 0.29.0 release。
- Fixture：`tests/fixtures/feature-chamfer-topology-defect-mixed.blend`。
- Replay 来自上一轮正式 UI Operator 捕获；文件字节 SHA256 为 `578d9034bf4c347a9af91fccb9ded88a1a7ffe61b1b4aa63a2c6d951d692b5b9`；按正式捕获定义重算的 canonical input SHA256 为合同值 `ccedf5a2b0e204d81503857ccee72c5048955d0962edef770cd521ca57c709c3`。
- Oracle：正式 Python runtime 捕获的 729 项逐组合结果和正式下游返回数据。
- 紧凑调用仍在 Rust 中计算 729 项，只返回 best index、best score、best option indices、best pair links、fingerprint。
- 性能计时不包含 Blender 启动、磁盘读取、全量审计返回和 JSON/SHA 指纹计算。

## 3. 分阶段结果

### Phase 0 — PASS

- 正式下游消费已核对到 `utils/experimental_pipe_chamfer_utils.py:1754-1798`：best options、score 前六项、selected pairing 和 matching records。
- Replay SHA256 三方一致。
- Rust release 单独全量审计：729/729 accepted/None、完整 score（含 geometry signature）、pair links、best 全等；accepted 681；best index `473`；首差无。

### Phase 1A — PASS

- 全量审计继续 729/729 PASS。
- 紧凑返回键只有：`best_index`、`best_score`、`best_option_indices`、`best_pair_links`、`fingerprint`；没有逐组合 `results`。
- Python 恢复的 best options、selected pairs、数值 strand pairs、vertex matching records 全等。
- 恢复结构 fingerprint：`86f0c78fb6b496550c020f4cb56fd7f1a5d3618007c89d3e9965110128028d77`；首差无。

### Phase 1B — PASS

- 20 warmup + 101 repeats。
- 每轮都从冻结 Python primitive 重建 common 与 729 combinations；一次 PyO3 调用；解包紧凑结果；恢复 best options、strand pairs、records；未复用预打包 Rust 对象。
- Python 中位：`1.026091100s`。
- 紧凑 PyO3 端到端中位：`0.131557900s`。
- 相对下降：`87.1787%`（门槛 ≥70%）。
- 绝对节省：`0.894533200s`（门槛 ≥0.20s）。
- Python、native fingerprint、恢复 fingerprint 的 101 次结果均稳定。
- native 缺失独立 Blender 进程：Python replay 729/729 PASS。

### Phase 1C — PROTOTYPE / PASS

紧凑返回同时满足语义等价和性能硬门槛，因此 FeatureGraph Rust score 路线具备另建正式 Operator A/B 集成计划的价值。当前旁路原型不得直接接入正式入口。

## 4. REJECTED 轮次

- `source-discovery-command`：PowerShell/rg 引号及当前路径缺失；仅工具失败，不是验证 STOP。
- `compact-prototype-edit-attempt`：一处精确替换锚点在前序编辑后不存在；随后检查源文件确认目标修改，未作为证据。
- `validator-write-attempt`：PowerShell here-string 语法错误；未运行验证。
- `native-build-cp314`：初次构建误链接 `python314.dll`，Blender cp313 导入失败；已标 REJECTED，使用 Blender Python 3.13 重建后的 binary。
- 使用过的禁止机制：无。

## 5. 证据与范围

- 工作目录：`C:\Users\LiuYang\.codex\worktrees\708e\HardsurfaceGameAssetToolkit`。
- 机器摘要：`tests/artifacts/feature_chamfer_feature_graph_rust_compact/summary.json`。
- 阶段证据：同目录 `phase0.json`、`phase1a.json`、`phase1b.json`、`native_missing.json`。
- Replay：同目录 `replay.json`。
- 旁路原型：`prototypes/feature_chamfer_rust_global_score/`。
- 独立规格审计：PASS；已只读复核正式捕获、canonical hash、729/729、紧凑返回字段、计时边界、20+101、稳定性、fallback、阶段顺序和禁止修改范围。
- 未执行：正式集成、GUI/视觉验收、图片、完整回归、commit、push。
