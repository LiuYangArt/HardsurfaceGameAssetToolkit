# Feature Chamfer 通用化 Phase 1 失败剖面

> 日期：2026-07-22；状态：`PROTOTYPE`；Phase 1：`GO`；产品整体：`NOT VERIFIED`。
> 目标 Operator：`hst.feature_chamfer_gn`；动作：`PREVIEW` → `FINALIZE`。
> 失败聚焦：mixed / `Extruded.002` / radius=0.01 的 `REGRESSION_FAILURE`。

## 结论

mixed / `Extruded.002` / 0.01 的 `regular_patch_invalid` 不是随机失败，而是 `build_chamfer_strip`（`utils/experimental_pipe_chamfer_utils.py` 中的 open rail strip builder）在特定 rail pair 上因边界采样不均造成的“数值级退化”。同一对象在 radius=0.03 时则因另一前置 guard（`shared_rail_invalid`）而安全失败，避开了该路径。因此该 regression 不说明整个对象不可倒角，而是当前 strip builder 对长边/非均匀采样的容忍度过低，导致一个理论上可处理的 open rail pair 被误判为宽度超限。

## 失败路径

```text
hst.feature_chamfer_gn → PREVIEW (FINISHED)
                     → FINALIZE (CANCELLED)
                       → GN_PREVIEW_V1 backend
                         → PATCHED stage
                           → _patch_boundaries
                             → _patch_regular_rail_records
                               → _zipper_bridge_open
                                 → build_chamfer_strip
                                   → SIGNED_STRIP_WIDTH_EXCEEDED
```

## 关键证据

### 触发点

- `error_code`: `regular_patch_invalid`
- `error_message`: `group=17 span=1: Open Rail correspondence guard failed: SIGNED_STRIP_WIDTH_EXCEEDED`
- 位置：`utils/experimental_pipe_chamfer_utils.py` ~L1914 `build_chamfer_strip`

### 该 rail pair 的几何

| 指标 | 值 |
|---|---|
| group | 17 |
| span | 1 |
| cyclic | False |
| rail_left 顶点数 | 44 |
| rail_right 顶点数 | 38 |
| geometry_guard | PASS（0.909 inlier ratio，低于其他成功 pair 但仍过阈值） |
| max_edge_length | 0.2688（远大于 radius=0.01） |
| 端点平均宽度 | 0.0363 |

### 复现 guard 失败数值

使用 `build_chamfer_strip` 的弦长参数化 monotonic correspondence，该 rail pair 出现：

- `expected_width`（代码固定为 `radius * sqrt(2)`）= 0.01414
- `maximum_width_error`（固定为 `max(radius * 0.60, 1e-5)`）= 0.0060
- 实际 width error inlier ratio = 0.675（< 0.95）
- `maximum_relative_advance` = 0.2688（> 0.1131 = expected_width * 8）

失败直接由 `maximum_relative_advance > expected_width * 8` 触发，而该大值的来源是 rail 上存在一条长度约 0.2688 的边界边。当一侧推进到这条长边时，另一侧按弦长参数被“拖过”多个顶点，导致对应点对的横向距离骤增，被 guard 判为宽度超限。

### 其他 `SIGNED_STRIP_WIDTH_EXCEEDED` 案例的共性

| case | group | span | max_edge_length | 失败模式 |
|---|---|---|---|---|
| tricky__solid_016__r0p010 | 2 | 8 | 1.2190 | 超长边导致 inlier ratio 仅 0.044 |
| tricky__solid_016__r0p030 | 2 | 8 | 1.2208 | 同上，与 radius 无关 |
| tricky_b__extruded_002__r0p010 | 4 | 1 | 0.4479 | 顶点数极少（2/3），端点宽度误差超限 |
| tricky_b__extruded_002__r0p030 | 4 | 1 | 0.4479 | 同上 |
| tricky_b__extruded_003__r0p010 | 2 | 0 | 0.0535 | 没有超长边，但 rail pair 整体宽度约 0.046，远超 expected_width 0.014；端点不对应 |

共性：失败不是几何“必然交叉”，而是**rail pair 与 strip builder 的假设失配**：
1. 边界边长度与 radius 严重不成比例（长边跨越）；
2. 或 rail pair 两侧端点/宽度与期望的“等距条带”相差太远；
3. 当前 builder 没有先重采样或分治长边，而是直接用原始顶点做弦长参数化。

## 为什么同一对象在 radius=0.03 时不同失败

mixed / `Extruded.002` / 0.03 的 `error_code` 是 `regular_patch_shared_rail_invalid`（`Shared Rail is not a single endpoint Edge: group=11 span=0`）。说明 radius 放大后，Boolean boundary 的拓扑结构变化导致共享 rail 的 setback 检查先失败，整个 finalize 在到达 group 17 span 1 的 strip builder 之前已安全退出。因此 0.01 的 `SIGNED_STRIP_WIDTH_EXCEEDED` 是一个路径相关的回归，不是对象级不可处理。

## 诊断假设（尚未验证）

1. **根因假设 A**：Boolean 差集后，某些边界环上保留原始 Mesh 的长边（source feature edge 或切后大面），strip builder 应对此类边做重采样或参数化修正。
2. **根因假设 B**：geometry guard 在验收 rail pair 时只看 inlier ratio 与投影连续性，未对 `max_edge_length / radius` 设限，导致 Numerically unreliable 的 pair 进入 strip builder。
3. **根因假设 C**：`_zipper_bridge_open` 的 `expected_width` 使用固定 `radius * sqrt(2)`，但某些 rail pair 实际宽度因来源不同（open pipe 与 boolean boundary 混合）与该值差异较大，应允许按 pair 自适应宽度或 fallback 到三角化。

## 建议进入 Phase 2 前必须回答的问题

- 该 group 17 span 1 的 rail pair 在 Preview 阶段是否可见？其长边对应 source mesh 的哪个 Sharp Edge / face boundary？
- 若对 group 17 span 1 的边界边做均匀重采样（subdivide 长边），strip builder 是否通过？是否生成合法 mesh？
- 该失败是否可以通过放宽 `maximum_relative_advance_limit` 临时绕过？对产品拓扑/视觉的影响是什么？
- 是否应将该对象在 radius=0.01 时标记为 `EXPECTED_UNSUPPORTED`，因为存在超长边？还是需要修改算法以支持该输入？

## 明确未做

- 未修改 `utils/experimental_pipe_chamfer_utils.py` 或任何 Feature Chamfer 实现。
- 未修改矩阵 runner 的分类。
- 未运行 Blender 或重新生成 artifact；本阶段只基于现有 diagnostics.json 做分析。

## 验证命令

```text
python tools/run_feature_chamfer_matrix.py --blender /Applications/Blender.app/Contents/MacOS/Blender --repetitions 2
```

Phase 0 已执行并产出基线；Phase 1 仅读取 `tests/artifacts/feature_chamfer_matrix/` 下的 JSON 证据。

## 下一阶段（Phase 2）候选入口

根据 roadmap，Phase 2 是“建立统一 `ChamferPlan` 语义计划”。本剖面建议在进入 Phase 2 前，先对 group 17 span 1 做一个最小可复现 probe，验证“重采样长边”能否消除 `SIGNED_STRIP_WIDTH_EXCEEDED`，以决定是否把“rail boundary 重采样”作为 `ChamferPlan` 的必填步骤。
