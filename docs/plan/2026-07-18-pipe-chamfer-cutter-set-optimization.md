# Experimental Pipe Chamfer Cutter Set 优化计划

## 背景与已确认问题

当前实验已经能完成 Sharp FeatureGraph、独立 Pipe、部分 Boolean Cut，但暴露出三类真实问题：

1. 显式 Pipe Union 采用逐根 Exact Union；复杂交叉会累积碎面并产生 `union_not_manifold`。
2. open Pipe 的端点延长在密集 Feature、薄壁或凹槽中可能碰到无关 Surface/Pipe。
3. Cube 等多 Pipe junction 在 Cut 后还缺 Regular Strip / Junction Patch 的稳定分区，必须继续 fail-closed，不能用 Bevel 掩盖。

## 方向判断

不再生成实体化 Union cutter，也不把互穿 Pipe 简单 Join 成一个自交 Mesh。

保持每根 Pipe 为独立 closed manifold Object，放进专用 cutter Collection；对 source duplicate 使用一次：

- Boolean operation：`DIFFERENCE`
- operand type：`COLLECTION`
- solver：`EXACT`

这直接计算 `source - (pipe_0 ∪ pipe_1 ∪ ...)`，绕开中间 Union Mesh，同时保留每根 Pipe 的 `pipe_id` 与 BVH provenance。

## 实施任务

### Task 1：Cutter Set

- 每次运行创建 source 专属 cutter Collection。
- 独立 Pipe 全部链接到该 Collection。
- `CUTTER_UNION` debug stage 保留兼容枚举，但语义改为显示 Cutter Set，不再执行 Union。
- 统计新增 `cutter_set_object_count`，`union_face_count` 标记为 deprecated/0。

### Task 2：Collection Exact Difference

- Boolean Modifier 使用 `operand_type = COLLECTION` 和 `collection = cutter_collection`。
- 默认 `Boolean Preview` 不 Apply Modifier；用户可直接调整 Blender Boolean 参数。
- 仅显式选择后续自动开口/补面 debug stage 时才 Apply Difference；禁止逐 Pipe Difference。
- Material provenance 只作 probe；BVH 按各 Pipe 几何分类 owner。
- 若 Collection Boolean 没产生 cutter Faces，报告 source、Pipe 数、overlap pairs 和各 Pipe 风险。
- Apply 前给原 Faces 写入 Boolean provenance attribute；Apply 后仅删除未继承该标记的槽面，BVH 不再参与删除决策。

### Task 3：Terminal Face 端点延长

- 若端点存在法线与 Pipe 外延方向近似一致的 terminal face，延长 `1 × radius`。
- surface continuation、cyclic 或 ambiguous 端点不延长。
- 记录每根 Pipe 两端的 extension length，供 debug 和后续 clearance solver 使用。
- 记录 `TERMINAL_FACE / SURFACE_CONTINUATION / AMBIGUOUS / CYCLIC` 分类与 terminal face index。

### Task 4：诊断与交互

- 失败时保留独立 Pipe debug objects，并给出 `pipe_id`、extension、overlap pair 统计。
- 已生成 artifact 后隐藏 source；无 artifact 的早期失败保持 source 可见。
- `union_not_manifold` 从主流程移除；单根 `pipe_not_manifold` 仍为硬失败。
- `Boolean Preview` 默认保留未 Apply 的 Boolean Modifier 与 Cutter Collection，允许手动调整 solver 参数。
- 自动补面无法处理多个倒角交汇时，UI 使用“切割已完成，但拐角开口尚不能自动补齐”的直白说明。

### Task 5：验证

- Headless 回归：多 Pipe Boolean Preview 不需要 Union Mesh，也不 Apply Modifier。
- 回归：独立 Pipe 均 closed manifold；source 不变并在有 artifact 时隐藏。
- 回归：terminal face 端延长 `radius`，surface continuation 端不延长。
- 回归：Boolean Preview 的 output Mesh data 不变，并保留一个可编辑的 Exact Collection Boolean Modifier。
- 用户文件：`C:/Users/LiuYang/Desktop/pipe-chamfer/pipe-chamfer-test.blend`。
- 分阶段记录 FEATURE_GRAPH / PIPES / CUTTER_SET / BOOLEAN_CUT 统计。
- 完整运行 `python .\tools\run_blender_tests.py`。

## 不在本轮伪装完成的内容

- Regular/Junction ownership split。
- 多 Pipe corner 的最终 watertight Patch。
- 完整 Surface clearance / self-intersection solver。

这些阶段继续返回稳定错误码，但不再被显式 Union cutter 的失败提前阻挡。
