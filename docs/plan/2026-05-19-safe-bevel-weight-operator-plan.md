# Safe Bevel Weight Operator 方案设计

日期：2026-05-19

本文档规划一个独立 operator，用于修复极端 corner / 多边交汇处的 Bevel Modifier 破面风险。范围只包含方案设计，不写代码。

## 1. 背景

当前项目的 bevel 流程主要通过 `HSTBevel` modifier 实现：

- `functions/hst_functions.py` 中 `add_bevel_modifier()` 添加或更新 Bevel Modifier。
- 当 mesh 存在 `sharp_edge` attribute 时，工具会创建 `bevel_weight_edge`，并将 sharp edge 写为 `1.0`。
- Bevel Modifier 使用 `limit_method = "WEIGHT"` 后，边上的 bevel weight 可以控制该边的倒角影响。
- 当前 `use_clamp_overlap = False`，可以保留全局 bevel 宽度，但在局部空间不足的 corner 处可能破面。

用户反馈的典型问题是：

- 一些尖锐 corner 或 concave / convex 交界处，倒角带互相挤压。
- 如果开启 clamp overlap，Blender 可能因为局部小问题压缩更大范围的 bevel，导致整体美术效果变差。
- 期望保留原有 bevel operator 的稳定行为，新增一个专门处理问题模型的 operator。

## 2. 目标

新增一个独立 operator：**Safe Bevel Weight / Bevel Repair**。

核心目标：

- 不修改原 `HST_OT_BatchBevel` 和 `HST_OT_BevelTransferNormal` 的默认行为。
- **明确不修改 `use_clamp_overlap`，也不把开启 clamp 作为修复路径。**
- 通过局部降低 `bevel_weight_edge`，让危险 corner 附近的 bevel 自动变窄。
- 保留模型大部分区域的原 bevel 宽度和美术效果。
- 支持用户只处理选区附近的问题边。
- 可重复运行，参数可在 Blender `Adjust Last Operation` 面板中后调。

非目标：

- 不修改任何现有 Bevel Modifier 的 `use_clamp_overlap`。
- 不新增任何依赖 clamp overlap 的自动修复逻辑。
- 不自动 apply Bevel Modifier。
- 不做完整自交检测。
- 不替代原有 batch bevel 流程。
- 不保证所有非 CAD / 脏拓扑 mesh 都能自动修复。
- 第一版不做复杂 UI 面板，只提供 operator 参数。

## 3. 设计原则

### 3.1 禁止修改 clamp overlap

本 operator 的设计前提是：**不修改 `use_clamp_overlap`。**

原因：

- clamp overlap 是 modifier 级全局行为。
- 一个局部极端 corner 可能导致更大范围 bevel 被压小。
- 这会破坏原模型整体 bevel 宽度和美术效果。
- 本工具只通过 `bevel_weight_edge` 做局部控制。

因此实现时不得：

- 自动设置 `bevel_modifier.use_clamp_overlap = True`。
- 把 clamp 作为 fallback。
- 新增“失败后开启 clamp”的容错逻辑。

### 3.2 独立工具，不改原工具

原 bevel operator 是批量基础工具，应保持可预测。Safe Bevel Weight 是后处理工具，用于问题模型或问题区域。

推荐流程：

1. 用户运行原 `Batch Bevel`。
2. 发现局部 corner 破面或高风险。
3. 用户选中问题模型，必要时选中问题边/面。
4. 运行 `Safe Bevel Weight`。
5. 工具只修改 `bevel_weight_edge`。
6. 原 Bevel Modifier 继续使用同一个 `HSTBevel.width`。

### 3.3 非破坏式

工具只写 mesh edge attribute：

- `bevel_weight_edge`

不直接修改：

- mesh topology
- modifier stack 顺序
- Bevel Modifier 全局 width
- WeightedNormal / Triangulate / DataTransfer modifier

### 3.4 局部处理

修复逻辑应尽量限制在风险 corner 附近。

原因：

- 全局 clamp 会牺牲整体倒角观感。
- 极端问题通常出现在少数顶点或短边区域。
- edge weight 是局部控制 bevel 的更合适入口。

## 4. Blender API 依据

根据 Blender Python API：

- `BevelModifier.limit_method` 支持 `WEIGHT`。
- `BevelModifier.edge_weight` 可指定 edge bevel weight attribute 名称。
- `BevelModifier.miter_inner` 支持 `MITER_SHARP` / `MITER_ARC`。
- `BevelModifier.miter_outer` 支持 `MITER_SHARP` / `MITER_PATCH` / `MITER_ARC`。
- `BevelModifier.vmesh_method` 支持 `ADJ` / `CUTOFF`。
- `BevelModifier.use_clamp_overlap` 可以避免 overlap，但会改变宽度分布；这里只作为背景说明。

本方案主要依赖 `bevel_weight_edge`，miter / vmesh 设置只作为可选增强。实现时不得读取、修改或 fallback 到 `use_clamp_overlap`。

## 5. Operator 规格

建议 operator：

- `bl_idname = "hst.safe_bevel_weight"`
- `bl_label = "Safe Bevel Weight"`
- `bl_description = "降低高风险 corner 附近的 bevel weight，减少局部 bevel 破面"`
- `bl_options = {"REGISTER", "UNDO"}`

交互方式：

- `invoke()` 只做上下文校验和参数初始化。
- 不弹 `invoke_props_dialog`。
- `invoke()` 校验通过后直接 `return self.execute(context)`。
- 参数出现在 `Adjust Last Operation` 面板。

## 6. 输入条件

### 6.1 对象要求

处理对象：

- 当前选中的 mesh object。
- 排除 UCX object，沿用项目现有过滤模式。

跳过对象：

- 非 mesh object。
- 没有 `HSTBevel` modifier 的 object，默认跳过并 report。
- 没有任何可 bevel edge 的 object，默认跳过。

### 6.2 Bevel Modifier 要求

优先读取：

- `HSTBevel.width`
- `HSTBevel.limit_method`
- `HSTBevel.edge_weight`

如果 modifier 存在但不是 `WEIGHT` 模式：

- 第一版建议仍可创建 / 更新 `bevel_weight_edge`。
- 但不自动切换 `limit_method`，避免改变原工具行为。
- report 提示：该 object 的 Bevel Modifier 不是 Weight 模式，已写入 attribute 但 modifier 可能不会消费。

也可在第二版增加参数：

- `Set Modifier To Weight Mode`

默认关闭。

## 7. 参数设计

第一版建议参数：

### 7.1 `selected_only`

类型：`BoolProperty`

默认：`False`

含义：

- `False`：处理整个选中 object。
- `True`：只处理 edit/object selection 附近的 edge / face。

用途：

- 用户手动定位问题 corner 后，可以只修那一小片。

### 7.2 `min_weight`

类型：`FloatProperty`

默认：`0.2`

范围：`0.0 - 1.0`

含义：

- 自动降权时的最低 bevel weight。
- 避免把倒角完全取消。

建议：

- `0.15 - 0.35` 适合保留微小倒角。
- `0.0` 可用于非常严重的破面区域。

### 7.3 `aggressiveness`

类型：`FloatProperty`

默认：`0.6`

范围：`0.0 - 1.0`

含义：

- 控制降权强度。
- 越大，危险区域权重越低。

### 7.4 `falloff_steps`

类型：`IntProperty`

默认：`1`

范围：`0 - 5`

含义：

- 从危险 edge / vertex 向外扩散几圈边。
- 让过渡更平滑，避免权重断崖。

建议：

- `0`：只处理危险边。
- `1`：默认，适合大多数 corner。
- `2+`：更柔和，但影响范围更大。

### 7.5 `short_edge_ratio`

类型：`FloatProperty`

默认：`2.2`

范围：`0.5 - 10.0`

含义：

- 如果 bevel edge 长度小于 `bevel_width * short_edge_ratio`，视为短边风险。

说明：

- 对 `offset_type = WIDTH`，局部空间不足通常和边长 / 邻接距离相关。
- 该参数不是几何真值，只是风险启发式。

### 7.6 `sharp_angle_degrees`

类型：`FloatProperty`

默认：`35.0`

范围：`1.0 - 120.0`

含义：

- 同一 vertex 上两条 bevel edge 的夹角小于此值时，视为尖角风险。

### 7.7 `corner_edge_count`

类型：`IntProperty`

默认：`3`

范围：`2 - 8`

含义：

- 同一 vertex 连接的 bevel edge 数量大于等于该值时，视为多边交汇风险。

### 7.8 `preserve_user_lower_weight`

类型：`BoolProperty`

默认：`True`

含义：

- 如果用户已经手动把某条 edge weight 设得更低，工具不把它升高。
- 第一版只做 `new_weight = min(old_weight, computed_weight)`。

## 8. 核心算法

### 8.1 数据准备

对每个 target object：

1. 获取 mesh data。
2. 获取 `HSTBevel` modifier。
3. 读取 `bevel_width = modifier.width`。
4. 获取或创建 `bevel_weight_edge` attribute。
5. 找出候选 bevel edges：
   - `bevel_weight_edge > 0.0` 的边。
   - 如果 attribute 不存在，但存在 `sharp_edge`，先按 sharp edge 初始化为 `1.0 / 0.0`。
   - 如果两者都不存在，可按当前 Bevel Modifier 的 `ANGLE` 逻辑估算候选边，但第一版建议只 report，不隐式猜测。

### 8.2 风险评分

为每条候选 edge 计算 `risk_score`，范围 `0.0 - 1.0`。

风险来源：

#### A. 短边风险

规则：

- `edge.length < bevel_width * short_edge_ratio`

评分建议：

- `short_ratio = edge.length / (bevel_width * short_edge_ratio)`
- `short_risk = 1.0 - saturate(short_ratio)`

含义：

- 边越短，越容易被 bevel 带吃掉。

#### B. 多边交汇风险

对 edge 两端 vertex 分别检查：

- 统计该 vertex 连接的候选 bevel edge 数量。
- 如果数量 >= `corner_edge_count`，增加风险。

评分建议：

- `junction_risk = saturate((bevel_edge_count - corner_edge_count + 1) / 3.0)`

含义：

- 多条 bevel edge 同时汇入一个 vertex，miter 区域更容易拥挤。

#### C. 尖角风险

对同一 vertex 上的候选 bevel edge 两两计算方向夹角：

- 如果夹角小于 `sharp_angle_degrees`，增加风险。

评分建议：

- `angle_risk = 1.0 - angle / sharp_angle`

含义：

- 角越尖，局部 bevel 空间越少。

#### D. concave / convex 混合风险

如果可通过 bmesh 判断 edge convexity：

- 同一 vertex 附近同时存在 convex bevel edge 和 concave bevel edge。
- 或者当前 edge 相邻区域凹凸方向冲突。

评分建议：

- 第一版只给固定加权：`mixed_risk = 0.35`。

说明：

- 该规则有价值，但不应第一版过度复杂。
- 如果实现成本高，可放到第二版。

### 8.3 风险合成

推荐采用 max 合成：

```text
risk_score = max(short_risk, junction_risk, angle_risk, mixed_risk)
```

原因：

- 任一单项高风险都足以导致局部破面。
- max 比加权和更容易解释和调参。

可选第二版：

```text
risk_score = 1 - product(1 - each_risk)
```

但第一版不建议增加调参复杂度。

### 8.4 从风险转换为权重

计算目标权重：

```text
target_weight = 1.0 - risk_score * aggressiveness
safe_weight = max(min_weight, target_weight)
```

写入策略：

```text
new_weight = min(old_weight, safe_weight)
```

原因：

- 不提高用户已有的低权重。
- 只在风险区域降低 bevel。

### 8.5 falloff 扩散

如果 `falloff_steps > 0`：

1. 以风险 edge 为源点。
2. 沿候选 bevel edge adjacency 做 BFS。
3. 每扩散一圈，风险衰减。

建议衰减：

```text
falloff_factor = 1.0 - step / (falloff_steps + 1)
propagated_risk = source_risk * falloff_factor
```

如果同一 edge 收到多个源风险：

```text
edge_risk = max(existing_risk, propagated_risk)
```

这样可以避免权重突变。

## 9. 选区处理

### 9.1 Object Mode

如果 `selected_only = False`：

- 处理整个 selected object。

如果 `selected_only = True`：

- 使用 mesh edge / polygon selection 数据。
- 候选范围限定为：
  - selected edge
  - selected face 的边
  - 以及这些边附近 `falloff_steps` 范围内的边

### 9.2 Edit Mode

第一版可以支持两种策略：

策略 A：进入 object data 读取 selection。

- 保存当前 mode。
- 切到 object mode。
- 读取 `edge.select` / `polygon.select`。
- 执行后切回原 mode。

策略 B：要求 Object Mode。

- 更简单，但体验差。

建议第一版支持策略 A，因为该工具主要用于用户在 viewport 中圈选问题区域后执行。

## 10. Miter / VMesh 可选增强

除了写 edge weight，还可以提供可选参数修改 Bevel Modifier 的局部交汇策略。

建议第一版不要默认改，只提供第二阶段选项。

可选参数：

- `set_miter_outer`
- `miter_outer = MITER_PATCH / MITER_ARC`
- `set_miter_inner`
- `miter_inner = MITER_ARC`
- `set_vmesh_method`
- `vmesh_method = CUTOFF`

风险：

- miter 设置是 modifier 级别，不是局部 edge 级别。
- 改了可能影响整个模型的 bevel corner 外观。
- 因此不适合作为第一版默认行为。

建议：

- 第一版只做 edge weight。
- 第二版增加一个 `Apply Modifier Miter Tuning` 复选项，默认关闭。

## 11. Debug 与可观察性

为方便 agent 和用户排查，建议输出机器可读信息。

### 11.1 Report 信息

Operator 完成后 report：

```text
Safe Bevel Weight: processed 3 objects, adjusted 28 edges, skipped 1 object
```

### 11.2 可选 debug attribute

第二版可增加：

- `hst_bevel_risk_edge`：EDGE / FLOAT
- `hst_bevel_safe_weight_original`：EDGE / FLOAT

用途：

- 显示风险评分。
- 对比修改前后的 weight。
- 便于做 headless regression test。

第一版是否加入：

- 建议加入 `hst_bevel_risk_edge`，默认清零重写。
- 不建议默认保留 original weight attribute，避免污染资产。

### 11.3 日志

只在 debug 参数开启时打印详细信息：

- object name
- candidate edge count
- risky edge count
- adjusted edge count
- top risk reason 统计

不要 silent fallback。

## 12. UI 入口

建议放在 `ui_panel.py` 的 Bevel Tool 区域。

入口：

- `Batch Bevel`
- `Bevel & Transfer Normal`
- `Safe Bevel Weight`

按钮名建议：

- `Safe Bevel Weight`

不建议叫：

- `Fix Bevel`

原因：

- 它不是万能修复。
- 实际行为是调整 edge weight。

## 13. 测试方案

按项目测试规范，新 operator 应补 smoke / regression test。

文件：

- `tests/blender_test_driver.py`

建议新增 case：

### 13.1 `safe_bevel_weight_smoke`

构造：

- 创建一个简单 mesh。
- 添加 sharp edge / bevel weight。
- 添加 `HSTBevel` modifier。
- 运行 `hst.safe_bevel_weight`。

断言：

- operator 返回 `FINISHED`。
- `bevel_weight_edge` 存在。
- 至少一条高风险边 weight 小于 `1.0`。
- 非风险边保持 `1.0`。

### 13.2 `safe_bevel_weight_selected_only_regression`

构造：

- 创建多个 corner 区域。
- 只选择其中一个区域。
- 运行 `selected_only=True`。

断言：

- 选区附近 edge 被降权。
- 非选区风险区域不被改动。

### 13.3 `safe_bevel_weight_preserves_lower_user_weight_regression`

构造：

- 某条 edge 初始 weight = `0.1`。
- 工具计算 safe weight = `0.3`。

断言：

- 最终仍为 `0.1`。

### 13.4 `safe_bevel_weight_missing_modifier_smoke`

构造：

- object 没有 `HSTBevel` modifier。

断言：

- operator 不崩溃。
- object 被跳过。
- 没有误创建无意义 modifier。

## 14. 实施阶段

### Phase 1：最小可用版本

实现内容：

- 新增 operator。
- 读取 `HSTBevel.width`。
- 创建 / 读取 `bevel_weight_edge`。
- 检测短边、多边交汇、尖角。
- 写入降权后的 edge weight。
- 支持 `selected_only`。
- 补 smoke test。

验收：

- 能在用户提供的极端 corner 模型上局部缩小 bevel。
- 大部分普通边保持原 weight。
- 不影响原 bevel operator。

### Phase 2：增强可控性

实现内容：

- 加入 `hst_bevel_risk_edge` debug attribute。
- 输出风险原因统计。
- 增加 selected face 邻域扩散。
- 补 selected only regression。

验收：

- 用户能看出哪些边被判为风险区域。
- agent 能通过 attribute 和测试结果判断工具是否生效。

### Phase 3：Modifier 参数辅助

实现内容：

- 可选 miter / vmesh tuning。
- 默认关闭。
- 加入 UI 参数。

验收：

- 用户显式开启时才修改 modifier 级参数。
- 不改变第一版 edge weight 方案的默认结果。

## 15. 风险与限制

### 风险 1：启发式误判

表现：

- 某些本来可以保持完整倒角的边被降权。

缓解：

- 默认只降低高风险区域。
- 提供 `selected_only`。
- 提供 `min_weight` 和 `aggressiveness`。
- 保留 Undo。

### 风险 2：破面根因不是 bevel width

表现：

- 输入 mesh 本身有重叠面、非流形、极短碎边。

缓解：

- 工具只负责 bevel weight 修复。
- 如果仍失败，应进入 mesh cleanup / CAD repair 流程。

### 风险 3：modifier 不是 Weight 模式

表现：

- attribute 被写入，但 modifier 不使用。

缓解：

- report 明确提示。
- 第二版可提供显式开关切换 modifier 到 Weight 模式。

### 风险 4：falloff 影响过大

表现：

- 问题边附近较大范围倒角变窄。

缓解：

- 默认 `falloff_steps = 1`。
- 用户可设为 `0`。

## 16. 推荐默认值

```text
selected_only = False
min_weight = 0.2
aggressiveness = 0.6
falloff_steps = 1
short_edge_ratio = 2.2
sharp_angle_degrees = 35.0
corner_edge_count = 3
preserve_user_lower_weight = True
```

## 17. 最终建议

建议采用独立 operator 方案，不修改原 bevel operator。

第一版只做一件事：

**基于局部拓扑风险，自动降低危险 corner 附近的 `bevel_weight_edge`。**

这条路线最符合当前需求：

- 保留全局 bevel 美术宽度。
- 避免 clamp overlap 的全局副作用。
- 不破坏现有工具链。
- 后续可继续扩展 debug attribute、selected only、miter tuning 和回归测试。