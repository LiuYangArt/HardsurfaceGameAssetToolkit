# Feature Chamfer FeatureGraph Rust 全局评分 Replay 验证结果

日期：2026-08-01
状态：`PROTOTYPE / STOP`（Phase 0、1A PASS；Phase 1B STOP；Phase 1C NOT RUN）

## 结论

- 固定 Mixed / `Extruded.002` / Radius `0.01` / 正式 UI `hst.feature_chamfer_gn`。
- Python replay 与正式结果 729/729 全等，681 项 accepted，best index `473`，首差无。
- Rust release 的 accepted/None、完整 score、geometry signature、pair links、best 729/729 全等；单元测试 4/4 PASS。
- pure Rust 中位 `0.130485s`，相对 Python `1.044854s` 快 `87.51%`，达到内核门槛。
- Python→PyO3 完整端到端中位 `0.872036s`，只快 `16.54%`、节省 `0.172818s`，未达到 `70% / 0.20s` 门槛。
- 101 次 Python、pure Rust、PyO3 结果均稳定；native 缺失时 Python replay 729/729 PASS。
- 正式 Python runtime、`auto_load.py` 未修改；不授权正式集成。

## 验证合同与审计

- 正式运行捕获 729 个组合；48 个 forbidden 组合未执行 containment，681 个 accepted 使用对应 index 的生产 BVH 实际输出。
- pair links 使用稳定数值 half-edge ID，不依赖 BMesh 对象字符串或 dict 顺序。
- Replay SHA256：`ccedf5a2b0e204d81503857ccee72c5048955d0962edef770cd521ca57c709c3`。
- 端到端每轮都从 Python primitive replay 重新构造 nested dict/list，单次 PyO3 批量调用，并完整解包 729 项与 best；未复用预打包 Rust 对象。
- 计划明确要求性能轮完整逐组合结果可用。未来若改为只回传 best/pair links，属于另一份需重新冻结的合同，不能改写本轮 `STOP`。
- Rust 的七位小数实现只证明本冻结 729 项等价，不泛化为任意输入都与 CPython `round(..., 7)` 等价。

## 阶段状态

| 阶段 | 状态 | 证据 |
|---|---|---|
| Phase 0 | PASS | Python replay 729/729；20 warmup + 101 repeats；中位 `1.044854s` |
| Phase 1A | PASS | Rust 729/729；首差无；单测 4/4 |
| Phase 1B | STOP | pure Rust 达标；PyO3 端到端只快 `16.54%`、节省 `0.172818s` |
| Phase 1C | NOT RUN | 前置性能门槛未通过 |

正式下游结果为 `3910 V / 7208 E / 3300 F`，boundary/non-manifold/zero-area=`0/0/0`，fingerprint `68b79296dec484f892498689f12bfc44ff2462c0908d606f05f80aecb6556742`。

## REJECTED 轮次

- `capture-v1`：best signature 比较方向错误，且 input hash 混入计时/oracle。
- `capture-v2`：缺少 containment 执行标记、float bits 与正式 selected-pairs 交叉断言。
- `Phase1A attempts 1/2`：PyO3 list/tuple 解码脚本缺陷。
- `Phase1A attempts 3/4`：validator 把数值相同的 list/tuple 判为差异。
- `Phase1B diagnostic`：旧计时误含 fingerprint 的 JSON/SHA；移出计时后重新完成 20+101，最终数据为 `0.872036s`。

## 证据

- 独立工作目录：`C:\Users\LiuYang\.codex\worktrees\10d0\HardsurfaceGameAssetToolkit`
- 机器摘要：`tests/artifacts/feature_chamfer_feature_graph_rust_score/summary.json`
- Replay/oracle：`tests/artifacts/feature_chamfer_feature_graph_rust_score/replay.json`
- Phase 0/1：`tests/artifacts/feature_chamfer_feature_graph_rust_score/phase0.json`、`phase1.json`
- native 缺失：`tests/artifacts/feature_chamfer_feature_graph_rust_score/native_missing.json`
- 旁路原型：`prototypes/feature_chamfer_rust_global_score/`

本轮没有 commit/push，也没有把旁路原型复制或接入主工作区。
