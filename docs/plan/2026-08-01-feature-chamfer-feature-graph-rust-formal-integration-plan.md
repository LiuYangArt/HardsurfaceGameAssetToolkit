# Feature Chamfer FeatureGraph Rust 正式集成计划

日期：2026-08-01
状态：`VERIFIED`（完整 Rust solver 已接正式入口；跨平台 Python fallback 保留）

> 后续按用户授权改为完整 Rust FeatureGraph solver。Mixed 的正式三轮 A/B 已同时通过
> 等价和性能门槛；Tricky-b 暴露的 cyclic canonical traversal 方向差异已修复并通过正式 A/B。
> Windows auto 已启用 Rust，macOS/Linux 和 native 不可用时仍走 Python。最新证据见同名结果
> 文档的“完整替换复验”章节；下文保留首次局部评分路线的历史。

## 1. 目标

本轮已在 Windows x86-64 + Blender 5.2/Python 3.13 中，把完整 Rust FeatureGraph solver 接入正式 Feature Chamfer runtime，同时永久保留 Python 路径。

最终正式 A/B 已完成：Mixed 三轮 Python/native 的完整合同逐轮一致，FeatureGraph 中位下降 `82.15%`，Operator 中位下降 `26.23% / 0.485994s`；Tricky-b 跨样本 A/B 也已全等。首次“只替换全局评分”的性能 `STOP` 仅作为历史保留，已被完整 solver 结果取代。

正式集成只有在 Mixed / `Extruded.002` / Radius `0.01` 的正式 UI Operator 上同时满足结果等价和性能门槛后，才允许默认 `auto` 选择 Rust。

## 2. 运行策略

- `auto`：Windows 且原生模块 ABI 匹配时使用 Rust；macOS/Linux、模块缺失或 ABI 不匹配时使用 Python。
- `python`：强制现有 Python solver，用作 oracle 与诊断。
- `native`：强制 Rust；模块缺失或执行错误直接报错，不静默 fallback。
- 原生模块已经成功加载后的执行异常必须保留上下文并抛出。
- 禁止修改 FeatureGraph 算法、候选、阈值、排序、tie-break、containment/BVH、Bridge/Fill/Boolean。

## 3. 正式边界

Python adapter 负责读取 Blender Mesh/BMesh 和冻结必须依赖 Blender API 的几何查询；Rust 一次完成 Surface Patch、候选组合、全局评分、matching 与 strand traversal，并返回完整 groups/stats。Python 恢复 Vector 等现有对象合同后继续原下游 Plan、Cutter、Boolean 与 Bridge/Fill。

不得调用 Python scorer 冒充 Rust，不得逐组合跨语言调用，不得把测试 replay 固定数据用于正式输入。

## 4. 分阶段硬门槛

### Phase 0 — Python oracle

- Mixed 正式 UI Operator，至少 20 warmup + 21 repeats 的 FeatureGraph/Operator 基线，或复用同轮可审计基线。
- 冻结最终 Mesh fingerprint/计数/健康性、Feature groups、vertex matching、ChamferPlan。
- 固定组合规模必须仍为 729/681；变化则先解释并重新冻结。

### Phase 1 — 集成但默认 Python

- 加入原生加载器、Rust crate、Windows cp313 模块与 `auto/python/native` 选择。
- 初始默认必须为 Python；native 缺失时插件能注册且 Python 正式 Operator 完整运行。
- 单元/旁路全量 729/729 等价继续通过。

### Phase 2 — 正式 Operator A/B

同一份当前代码、同一 Mixed 输入，分别强制 `python` 与 `native`：

- 正式 Operator 完成状态一致；
- 最终 Mesh fingerprint/计数/健康性一致；
- Feature groups、vertex matching、ChamferPlan 一致；
- native runtime 证明确实调用 Rust；
- 至少 3 次有效正式 A/B，中位 FeatureGraph 下降至少 50%；
- Operator 中位下降至少 15% 且绝对节省至少 0.20s。

Stop：任一正确性或性能门槛失败，恢复正式默认 Python，后续 auto NOT RUN。

### Phase 3 — 启用 auto 与 fallback

仅 Phase 2 PASS：

- Windows 默认 `auto` 实际调用 Rust；
- 强制 Python 仍可用；
- 模块缺失/ABI 不匹配时 auto 使用 Python；
- native 执行异常不静默 fallback；
- macOS/Linux 路由静态测试为 Python。

### Phase 4 — 最小回归

- Rust crate tests；
- FeatureGraph backend/fallback 回归；
- Mixed 正式 Operator；
- `python .\tools\run_blender_tests.py`。

## 5. 状态

- `PROTOTYPE`：仅旁路证明。
- `INTEGRATED`：正式代码已包含路径，但默认仍为 Python。
- `VERIFIED`：正式 Operator A/B、auto/fallback 与最小回归通过。
- `ACCEPTED`：如需用户视觉确认，交付 .blend 后由用户确认；本任务禁止图片判定。
- `STOP`：首个等价或性能门槛失败，正式默认保持 Python。

## 6. 证据

- 结果：`docs/validation/2026-08-01-feature-chamfer-feature-graph-rust-formal-integration-result.md`
- Mixed 最终三轮证据：`tests/artifacts/feature_chamfer_feature_graph_final_ab_integrated_final/`
- Tricky-b 证据：`tests/artifacts/feature_chamfer_feature_graph_tricky_b_ab_fixed/`
- 完整 solver、native loader、Windows 二进制和 Python fallback 均已保留在正式工作区。
