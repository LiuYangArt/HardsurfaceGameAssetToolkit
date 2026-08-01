# Feature Chamfer FeatureGraph Rust 正式集成验证结果

日期：2026-08-01
状态：`VERIFIED`（Windows 正式默认 Rust；Python fallback 保留）

## 完整替换复验（取代首次局部评分结论）

后续按用户授权把 Surface Patch、候选组合、全局评分和 strand traversal 作为完整 Rust solver
重新实现。Mixed / `Extruded.002` / Radius `0.01` 三轮正式 A/B 全部满足：Operator、最终
Mesh、Feature groups、vertex matching、ChamferPlan 和 FeatureGraph 语义逐轮相等。

- FeatureGraph 中位：Python `0.584269s`，Rust `0.104300s`，下降 `82.15%`。
- Operator 中位：Python `1.853112s`，Rust `1.367118s`，下降 `26.23% / 0.485994s`。
- 最终 Mesh：`3910 V / 7208 E / 3300 F / 2620 Chamfer Faces`，健康性 `0/0/0`。

随后扩展到 Tricky-b 正式入口，发现 Rust 对 cyclic group 用几何坐标决定方向，而 Python 用
Vertex index。修正 canonical traversal 后，Tricky-b 的 Mesh `1152/2055/905/722`、groups、
vertex matching、ChamferPlan 和完整 FeatureGraph 语义全等。Windows auto 已启用 Rust；
macOS/Linux 或 native module 不可用时仍走 Python，强制 native 的错误不会被静默吞掉。

机器证据：

- Mixed：`tests/artifacts/feature_chamfer_feature_graph_final_ab_integrated_final/comparison.json`
- Tricky-b：`tests/artifacts/feature_chamfer_feature_graph_tricky_b_ab_fixed/comparison.json`
- 完整回归：`tests/artifacts/feature_chamfer_rust_full_regression_final/results.json`（157 PASS / 1 FAIL；
  唯一失败是无关的 FBX exporter stdout `OSError`，单项重跑已 PASS）
- 单项重跑：`tests/artifacts/feature_chamfer_rust_marmoset_retry/results.json`

以下为首次“仅替换全局评分”路线的历史记录，状态已由本节取代。

## 历史：首次局部评分路线

Rust 路径曾旁路接入正式 Operator 并完成 Mixed A/B，但没有性能收益，已从正式 runtime 撤回。

- 正确性：PASS。Python/native 的最终 Mesh、Feature groups、vertex matching、ChamferPlan 全部一致。
- Python FeatureGraph 中位：`0.589451s`。
- native FeatureGraph 中位：`0.805099s`，反而慢 `36.58%`。
- Python Operator 中位：`2.094033s`。
- native Operator 中位：`2.279357s`，反而慢 `8.85% / 0.185325s`。
- 第一失败门槛：FeatureGraph 需下降至少 50%，实际为负收益。
- 因 Phase 2 STOP，Phase 3 auto 启用 NOT RUN；正式默认继续 Python。

### 历史机制说明

Rust 只替换全局组合评分。为了保持正式动态 containment/BVH 语义，当前集成先在 Python 中逐组合执行正式 scorer 来取得 containment，再把 729 项打包给 Rust。这个重复工作抵消了 Rust 内核收益，因此正式路径比 Python 更慢。

这与旁路紧凑 replay 的 `87.18%` 提升不冲突：旁路 benchmark 的 containment 已经冻结，正式运行则必须动态计算。

### 历史正确性证据

三次独立冷运行均满足：

- Operator：`FINISHED`；
- 实际 backend：分别为 `python` / `native`；
- Mesh：`3910 V / 7208 E / 3300 F / 2620 Chamfer Faces`；
- boundary/non-manifold/zero-area：`0/0/0`；
- Mesh fingerprint：`1c867671843be6b837ed6fe3d70e28ce192e63ee0cbe39e2e16edc8250515be8`；
- Feature groups fingerprint：`c551fc87c2998b03a22e4f2f70088bc887cc9e70d128372798cea436b0ae90da`；
- vertex matching fingerprint：`991e682db936d00ac3f8fc0d7a9d04bebb60e82614618d0cfd1f3a676c2c5885`；
- ChamferPlan：`7c1f6eeaefb1940a92e660cc3461b110c51fbd98ff57b69fc33a4c17903e8652`。

### 历史阶段

| 阶段 | 状态 |
|---|---|
| Phase 0 Python oracle | PASS |
| Phase 1 旁路接入、默认 Python | RECOVERY |
| Phase 2 正式 Operator A/B | STOP |
| Phase 3 启用 auto | NOT RUN |
| Phase 4 完整回归 | NOT RUN |

补充回归：统一测试执行 158 项，首次 `157 PASS / 1 FAIL`；唯一失败是既有 FBX 导出测试的 stdout `OSError`，与 FeatureGraph 无关。单独重跑该项实际功能 `PASS`（导出 12828-byte FBX），但测试进程在既有 unregister 清理处报错。Feature Chamfer 相关测试未出现回归。

撤回正式接入后，又单独运行 Mixed 正式回归与单 Operator 调度回归，`2/2 PASS`；Blender 退出时仍出现同一既有 unregister 清理异常，不影响两项结果。

### 历史证据

- `tests/artifacts/feature_chamfer_feature_graph_rust_integration/python.json`
- `tests/artifacts/feature_chamfer_feature_graph_rust_integration/native.json`
- 恢复后回归：`tests/artifacts/feature_chamfer_formal_recovery/results.json`
- 当时首次局部路线使用的临时接入已撤回；当前完整 solver 的 driver、runner、加载器及原生模块已正式保留。

上述撤回结论只描述首次局部评分实现，已被本文开头的完整 solver 复验取代。
