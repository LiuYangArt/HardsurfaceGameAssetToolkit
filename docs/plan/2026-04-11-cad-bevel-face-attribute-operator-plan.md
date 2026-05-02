# Plasticity CAD Bevel Face Attribute Operator 实施计划

> Implementation Plan, Task List and Thought in Chinese

## 1. 文档目标

本文档用于规划一个 Blender 5.0+ 的 operator。该 operator 面向从 Plasticity 一类 CAD 建模软件导入到 Blender 的 hard-surface mesh，对选中的 mesh 识别 bevel / fillet / chamfer 过渡面区域，并把结果写入 mesh attribute。这个 attribute 集合在本阶段只作为中间表示，不直接绑定 Unreal 的导出格式，从而保留后续把数据转成 vertex color、Geometry Nodes 输出或自定义导出脚本的灵活性。

本文档只规划，不写代码。范围严格限制为“识别并写入 bevel 面域信息”，不包含 Unreal 导出实现、材质节点实现、自动 shader 接线或所有非 CAD 网格的一般解。

## 2. 需求收敛

### 2.1 输入前提
- 用户选中一个或多个 `MESH` 对象。
- 这些对象的来源默认是 Plasticity / CAD 导出的 FBX 或 OBJ，再导入 Blender。
- 网格应尽量已经经过 `Fix CAD Obj` 或同等清理，至少满足：
  - 顶点已 merge，不是每个面都分裂成孤岛。
  - split normal 信息可用，或能据此恢复 `sharp_edge`。
  - 拓扑基本干净，没有大量开放边、重复壳体或破面。

### 2.2 输出目标
- 对每个输入 mesh 创建或覆盖一组 `FACE` 域 attributes。
- 这组 attributes 至少表达：
  - 这个 face 是否属于 bevel 过渡区域
  - 这个 bevel face 是 `convex` 还是 `concave`
- 结果先以中间表示存在，不提前锁定导出到 Unreal 的打包方式。
- operator 要支持重复执行，并能稳定覆盖旧结果。

### 2.3 明确不做
- 不恢复“原始 bevel source edge”的建模历史语义。
- 不承诺对普通手工 poly mesh、布尔烂拓扑、雕刻网格有同样的识别率。
- 不在第一版里解决 vertex color 打包、UE importer 修改或 shader 逻辑。
- 不把曲率、AO、wear 强度这些后续语义直接混到同一个 operator 里。

## 3. 关键判断

这次功能的核心不是“识别历史上的 bevel 操作结果”，而是“识别 CAD 导入 mesh 中作为主表面之间过渡 patch 的 bevel 面区域”。

对 Plasticity 一类输入，这个定义更准确，原因是：

- 导入后的 mesh 已经失去建模历史，不存在可靠的 source bevel edge 语义。
- 但 CAD tessellation 往往保留了比较规整的 patch 结构，这使得“过渡面 region 识别”反而比普通 poly mesh 更可做。
- Unreal 的 edge wear 最终真正需要的，也更接近“过渡区域 mask”，而不是建模历史标签。

因此，第一版算法应该围绕“CAD patch 分割 + 过渡 patch 分类”来设计，而不是围绕曲率图或单纯的边角阈值来设计。

## 4. 成功标准

### 4.1 功能标准
- 对选中 mesh 成功创建目标 attribute。
- attribute 使用稳定的命名和数据域。
- 再次运行时能够覆盖旧结果，不产生重复脏属性。

### 4.2 识别标准
- 对典型 Plasticity hard-surface 资产，能够把外轮廓圆角、倒角、凹槽圆角、孔口 fillet 等过渡面识别为 bevel 区域。
- 能够把外凸 bevel 与内凹 bevel 分开输出，避免后续在 Unreal 侧再做二次判断。
- 不应大面积误抓主平面、主圆柱面或大造型曲面。
- 对角点补片应有合理的并入策略，不应只识别直线段而漏掉 corner patch。

### 4.3 工程标准
- Operator 风格与仓库现有实现一致：输入检查清晰、报错明确、可重复执行、支持撤销。
- 算法主体应进入 `utils` 层，不把复杂几何逻辑堆在 operator 文件里。
- 输出保持为中间表示，不直接与 Unreal 导出耦合。

## 5. 现有仓库上下文

### 5.1 已有 CAD 预处理链路
仓库已有两个直接相关的 operator：

- `hst.fixcadobj`
- `hst.prepcadmesh`

其中 `Fix CAD Obj` 会执行：
- 应用旋转/缩放
- 合并顶点
- 检查开放边界
- `mark_sharp_edges_by_split_normal(mesh)`

这意味着仓库已经把“split normal -> sharp edge”作为 CAD 网格修复流程的一部分。对于这次 bevel 面识别，这是最重要的先验条件。

### 5.2 已有 edge 级工具
仓库已有这些几何工具：

- `mark_sharp_edges_by_split_normal(obj)`
- `mark_sharp_edge_by_angle(mesh, sharp_angle)`
- `mark_convex_edges(mesh)`

说明：
- sharp、convex 这些 edge 级信息已经有基础设施。
- 新需求缺的不是边标记，而是“如何把 face region 稳定地判成 bevel”。

### 5.3 已有 attribute 工具的缺口
`MeshAttributes` 当前只提供：

- `add(...)`
- `fill_points(...)`

现状问题：
- 没有通用的 `FACE` 域批量写值封装。
- 没有“如果属性已存在则清零/覆盖”的统一工具。

所以本次实现计划里必须包含“先补 attribute 写入工具”的工作，而不是把面域写值细节散到 operator 里。

## 6. 方案比较

### 6.1 方案 A：纯曲率 / 纯法线变化检测

思路：
- 对每个 face 或 edge 统计法线变化。
- 高曲率或高角度区域直接判为 bevel。

优点：
- 对导入来源依赖小。
- 在简单 fillet 上容易看到效果。

缺点：
- 会把圆柱主面、球面造型、大圆滑过渡误抓为 bevel。
- 会漏掉近似平面的 chamfer。
- 对角点区域的稳定性差。

判断：
- 不适合作为主方案，只能作为辅助特征。

### 6.2 方案 B：CAD patch 分割 + 窄过渡 patch 分类

思路：
- 先根据 sharp 边把 mesh 分成多个 face region。
- 再根据 region 的宽度、邻接关系、法线跨度、面积比例等特征，把“夹在两块主表面之间的小尺度过渡 patch”判定为 bevel region。

优点：
- 最符合 Plasticity/CAD 导入 mesh 的结构特征。
- 更容易解释和调试。
- 结果是 face region 级别，不是零碎面级噪声。

缺点：
- 依赖 split normal / sharp patch 的质量。
- 对 tangent continuity 且没有明确 patch 边界的情况需要额外兜底。

判断：
- 推荐作为第一版主方案。

### 6.3 方案 C：从高角度 edge 向两侧扩张面带

思路：
- 找到疑似 feature edge。
- 从这些 edge 两侧向内 flood fill，直到满足另一侧边界条件。

优点：
- 在 patch 边界不明显时有一定补救能力。

缺点：
- 实现复杂，且对 corner patch、交汇处、狭窄缝隙更脆弱。
- 更依赖调参与大量特例。

判断：
- 更适合作为第二阶段 fallback，不建议作为第一版主算法。

## 7. 推荐技术方案

### 7.1 总体原则

第一版应采用：

**先分 region，再判定 region 是否为 bevel patch。**

而不是：

**先给每个 face 打局部分数，再硬阈值挑面。**

原因是 region-first 的方案更符合 CAD 网格的结构，也更便于调试、复现和后续导出。

### 7.2 推荐数据模型

第一版主输出建议：

- `BEVEL_FACE_ATTR`
  - 类型：`FLOAT`
  - 域：`FACE`
  - 语义：总 bevel mask
- `BEVEL_CONVEX_ATTR`
  - 类型：`FLOAT`
  - 域：`FACE`
  - 语义：convex bevel mask
- `BEVEL_CONCAVE_ATTR`
  - 类型：`FLOAT`
  - 域：`FACE`
  - 语义：concave bevel mask

推荐默认取值：
- 非 bevel face：三个属性都为 `0.0`
- convex bevel face：
  - `BEVEL_FACE_ATTR = 1.0`
  - `BEVEL_CONVEX_ATTR = 1.0`
  - `BEVEL_CONCAVE_ATTR = 0.0`
- concave bevel face：
  - `BEVEL_FACE_ATTR = 1.0`
  - `BEVEL_CONVEX_ATTR = 0.0`
  - `BEVEL_CONCAVE_ATTR = 1.0`

选择 `FLOAT` 而不是 `BOOLEAN` 的原因：
- 后续更容易做权重、平滑、数据传输或导出映射。
- Geometry Nodes、Data Transfer、后续 packing 通常对 float 更友好。
- 后续如果想把二值结果升级成强度场，不需要改 attribute 类型。

可选的 debug 扩展属性：

- `BEVEL_SIGN_ATTR`：`FLOAT`，语义为 `-1.0 / 0.0 / 1.0`，分别表示 concave / none / convex
- `BEVEL_REGION_ID`：`INT`，便于 debug region 分类结果

建议结论：
- 第一版必需输出 `BEVEL_FACE_ATTR`、`BEVEL_CONVEX_ATTR`、`BEVEL_CONCAVE_ATTR` 三个属性。
- `SIGN` 和 `REGION_ID` 作为 debug 增强项，只有在实现成本低且能帮助调试时再加入。

### 7.3 Operator 合约

建议定义一个新的 operator，例如：

- `hst.mark_bevel_faces`

建议行为：
- 支持多选 mesh 批处理。
- 仅处理 `MESH` 对象。
- 默认覆盖同名 attribute。
- 允许一个参数决定是否在执行前自动尝试刷新 `sharp_edge`。

建议的输入检查顺序：
1. 是否有选中的 mesh
2. 是否存在空 mesh
3. 是否有开放边界或明显坏拓扑
4. 是否具备 `sharp_edge`；若没有且启用自动预处理，则尝试调用 split-normal sharp 标记
5. 若依然没有有效 region 分割基础，则报错取消

### 7.4 识别流程设计

推荐流程分成 7 步。

#### Step 1: 预处理与 sharp 基础建立

目标：
- 确保 mesh 处于可判定状态。

处理：
- 如果用户尚未执行 `Fix CAD Obj`，operator 可以提供一个 `auto_refresh_sharp` 参数，内部调用等效的 split-normal sharp 标记逻辑。
- 对于开放边界、空 mesh、严重坏拓扑，直接拒绝继续执行。

原因：
- 第一版算法的前提就是 region 分割。如果这个前提不成立，继续做只会产生难以解释的误判。

#### Step 2: 基于 sharp edge 做 face region 分割

目标：
- 把 mesh 切成若干个面区域，每个区域内部跨越的边都不是 sharp。

结果：
- 每个 region 应尽量对应一个 CAD surface patch，或者至少是一块几何性质相近的连续面域。

为什么必须先做这一步：
- bevel 在 CAD 导入 mesh 中最稳定的形态不是“某一小片面”，而是“一个独立的过渡 patch region”。

#### Step 3: 为每个 region 计算描述子

建议至少计算这些描述子：

- `face_count`
- `total_area`
- `boundary_edge_count`
- `adjacent_region_count`
- `normal_span_deg`
  - region 内部 face normal 的最大夹角或近似统计值
- `bbox_extent`
  - region 的局部包围盒尺寸
- `region_width_estimate`
  - region 的窄向宽度估计
- `adjacent_area_ratio`
  - 相邻 region 的面积对比

其中最关键的是：

- 它是否很窄
- 它是否夹在 2 个或多个更大的 region 之间
- 它的法线是否体现“过渡面”的性质

#### Step 4: Bevel region 分类规则

第一版推荐规则不是单阈值，而是组合规则。

建议一块 region 被判为 bevel 的条件组合如下：

必备条件：
- region 不是极大主体面
- `adjacent_region_count >= 2`
- `region_width_estimate <= max_bevel_width`

几何支持条件，至少满足一项：
- `normal_span_deg >= min_normal_span_deg`
  - 适合 round / fillet
- 或者 region 很窄，且两侧相邻 region 的法线差显著
  - 适合 chamfer

抑制条件：
- region 面积过大
- region 宽度过大
- region 只有 1 个相邻 region，像孤立装饰面而不是过渡 patch

这里的核心不是“所有 bevel 都是弯的”，而是：

**它是不是一块小尺度的连接 patch。**

#### Step 5: Convex / Concave 分类

在 bevel region 已经成立之后，第一版就应继续把它分成 convex 和 concave 两类。

推荐主判据：
- 以 candidate bevel region 的 `sharp` 边界为样本
- 只看连接 bevel region 与相邻主 region 的边界 sharp edges
- 读取这些边界 edge 的凸凹性

优先实现建议：
- 直接利用 Blender / BMesh 可获得的 `edge.is_convex` 或仓库已有的 `convex_edge` 结果做 majority vote
- 若一个 bevel region 的边界 sharp edges 绝大多数为凸，则该 region 记为 `convex`
- 若绝大多数为凹，则该 region 记为 `concave`

为什么这个判据合适：
- 对 CAD 导入 mesh，bevel patch 的“类型”最自然地体现在它与相邻主表面的边界折叠方向上
- 这比从 region 自身中心或曲率场直接猜更稳定

冲突与兜底：
- 如果一个 region 的边界既有明显凸又有明显凹，通常说明它是复杂 corner patch、错误分割或不适合当前简单分类的区域
- 第一版可采用保守策略：
  - 优先检查是否能通过角块并入解决
  - 仍无法确定时，保留 `BEVEL_FACE_ATTR = 1.0`，但 `BEVEL_CONVEX_ATTR` 和 `BEVEL_CONCAVE_ATTR` 都写 `0.0`，并在 debug 输出中标记为 ambiguous

#### Step 6: Corner patch 并入策略

只识别直线段 bevel strip 不够，因为 CAD 模型的角点经常会出现三向或多向过渡的小补片。

因此需要第二轮并入：
- 如果一个小 region 自身不完全满足主规则，但它与已识别 bevel region 强相邻，且尺度同样很小，则并入 bevel 集合。

目的：
- 避免只标记边条，不标记角点，导致 Unreal 里 wear mask 在角上断掉。

#### Step 7: 写回 FACE 域 attributes

输出规则：
- 先创建或获取目标 attributes
- 默认先全部清零
- 对判定为 bevel 的 faces 写总 mask
- 对 `convex` bevel faces 额外写 convex mask
- 对 `concave` bevel faces 额外写 concave mask

注意：
- 这一步应该通过统一的 attribute 工具层完成，而不是在 operator 中手工逐一散写。

### 7.5 关键描述子的实现建议

#### `region_width_estimate`

这是整套方案里最关键、也最难做扎实的量。

第一版不建议做过度复杂的 geodesic 宽度，而建议采用一个成本较低、可解释的近似：

- 对 region 的边界进行分组
- 用 region 局部主方向或边界中心差估计主长度轴与窄向轴
- 将窄向轴上的尺寸作为 `region_width_estimate`

这样做的优点：
- 足够快
- 足够解释得通
- 对长条 bevel strip 很有效

不足：
- 对复杂角块、非规则 patch 不如 geodesic 宽度精确

判断：
- 作为第一版完全可接受。

#### `normal_span_deg`

建议做成 region 内部 face normal 的范围统计，而不是单条 edge 的二面角阈值。

原因：
- 单条 edge 角度太局部，容易受 tessellation 密度影响。
- 同一块 fillet patch 的真实几何特征，是法线整体发生了可观旋转，而不是某一条边一定超过固定角度。

#### 相邻 region 法线差

这对 chamfer 很重要。

因为窄而平的 chamfer 自身 `normal_span_deg` 可能接近 0，但它仍然是一个典型 bevel patch。其识别依据应来自：

- 自身很窄
- 两侧连接的是法线差明显的主体 region

### 7.6 凸凹信息的处理建议

现在的目标已经明确包含 Unreal 中的 edge wear，因此 `convex` 和 `concave` 的分离不应该再被视为第二阶段增强，而应是第一版主输出的一部分。

原因：
- 磨损通常主要出现在 `convex bevel`
- `concave bevel` 更适合驱动污渍、积灰、漏液、暗缝等其他语义
- 如果第一版只输出总 bevel mask，后续再拆凸凹只能依赖更脆的二次推断

因此建议：
- 第一版直接输出 `总 bevel / convex bevel / concave bevel`
- `BEVEL_SIGN_ATTR` 只作为 debug 辅助，不作为唯一消费接口

这套设计虽然在存储上有一点冗余，但它对后续导出、材质图层、节点图和调试都更直接。

## 8. 文件改动计划

### 8.1 `const.py`

新增常量建议：
- `BEVEL_FACE_ATTR = "02_BevelFace"`
- `BEVEL_CONVEX_ATTR = "03_BevelConvex"`
- `BEVEL_CONCAVE_ATTR = "04_BevelConcave"`

建议命名考虑：
- 与现有 `00_WearMask`、`01_Curvature` 保持排序风格一致
- 不直接命名为 `WearMask`，避免和后续 shader 语义混淆
- 名称直接体现总 bevel / convex / concave 的语义，减少后续导出脚本二次映射成本

### 8.2 `utils/mesh_attributes_utils.py`

建议补充：
- 通用 attribute 清零函数
- `FACE` 域批量填值函数
- 支持一次性创建/重置多组 bevel attributes 的辅助函数
- 可选的“确保 attribute 存在并重置”的辅助函数

目标：
- 把数据写入逻辑统一抽到工具层

### 8.3 `utils/mesh_utils.py`

建议新增核心几何函数：
- sharp edge 驱动的 face region 分割
- region 描述子计算
- bevel region 分类
- convex / concave 分类
- 按 face 索引集合写回多张 mask 的辅助函数

原因：
- 这些都属于几何分析，不应该堆在 operator 层。

### 8.4 `operators/attribute_ops.py`

建议新增 operator：
- `HST_OT_MarkBevelFaces`

建议放在这里而不是 debug 模块或 CAD 模块的原因：
- 最终行为是“标记一个 attribute”
- 和 `TintMask`、`NormalType`、`SpecType` 同属“属性写入型工具”

### 8.5 `ui_panel.py`

建议增加按钮入口。

推荐位置：
- `Workflow` 区域中 CAD 处理链路附近，放在 `Fix CAD Obj` 之后最合理

原因：
- 这能直接表达依赖顺序：先修 CAD，再标 bevel face

## 9. 参数设计建议

第一版参数建议控制在少而硬，不要一开始做成半个调参面板。

### 必备参数
- `overwrite_existing: Bool`
  - 是否覆盖已有 attribute
- `auto_refresh_sharp: Bool`
  - 若缺少 sharp 基础，是否自动尝试基于 split normal 重建
- `max_bevel_width: Float`
  - 允许的最大 bevel 宽度，使用场景单位

### 推荐参数
- `min_normal_span_deg: Float`
  - 判断 round/fillet 的最小法线跨度
- `max_region_area_ratio: Float`
  - 抑制过大的主体 region 误判
- `merge_corner_patches: Bool`
  - 是否启用角点补片并入

### 不建议第一版开放给用户的参数
- 大量二级阈值
- 多种 debug 模式
- 导出到 vertex color 的打包选项

这些都应该等主识别稳定后再开放，否则只会把 UI 复杂度提前放大。

## 10. 实施步骤计划

### Phase 1: 建立稳定的数据输出骨架
- 在 `const.py` 增加 bevel attribute 常量
- 在 `mesh_attributes_utils.py` 增加 face-domain 写值工具
- 先把“创建/清零/覆盖多张 bevel attributes”流程打通

完成标准：
- 不论识别结果是否准确，operator 都能稳定输出一组合法的 `FACE` 域 float attributes

### Phase 2: 实现 sharp 驱动的 face region 分割
- 使用 `sharp_edge` 将 faces 划分为 region
- 为每个 region 建立面索引集合和邻接关系
- 加 debug 打印或可视化辅助验证 region 是否符合预期

完成标准：
- 在典型 Plasticity 网格上，fillet/chamfer 能作为相对独立的 region 出现，或至少成为可识别的小 region 集合

### Phase 3: 实现 bevel region 分类与凸凹拆分
- 计算每个 region 的宽度、面积、邻接和法线描述子
- 加入组合规则分类 bevel
- 基于边界 sharp edges 的凸凹性对 bevel region 做 convex / concave 拆分
- 实现 corner patch 第二轮并入

完成标准：
- 在你的测试资产上，主要 bevel 区域被正确写入总 mask，且外凸/内凹能稳定分开，主平面不被大面积误抓

### Phase 4: 接入 operator 和 UI
- 新增 operator
- 增加错误处理与汇总报告
- 在 `ui_panel.py` 中增加入口

完成标准：
- 用户从 CAD 清理流程到 bevel face 标记能在 UI 中完整跑通

### Phase 5: 手动验证与阈值收敛
- 导入你的测试文件做人工核对
- 检查 corner、凹槽、孔口、大圆柱面等关键案例
- 收敛第一版默认阈值

完成标准：
- 在至少 2 到 3 个 hard-surface CAD 样本上得到可解释、可重复的结果

## 11. 验证计划

### 11.1 基础功能验证
- 选中 1 个 mesh，执行 operator，确认 attribute 被创建
- 重复执行，确认不会生成重复属性或残留旧值
- 多选多个 mesh，确认批处理稳定

### 11.2 几何正确性验证
- 使用你提供的 `SM_TestBevel.fbx` 作为第一基准样本
- 手动检查这些区域是否被正确标记：
  - 外轮廓大圆角
  - 凹槽边一圈
  - 瓶口根部小 fillet
  - 顶部 lip 周边过渡圈
- 手动检查这些区域是否被正确分流：
  - 外轮廓与外侧圆角应进入 `convex`
  - 凹槽内侧、内孔过渡等应进入 `concave`
- 同时检查这些区域不应被大面积误抓：
  - 大平面主体
  - 圆柱主面
  - 明显属于主造型的大曲面

### 11.3 坏输入验证
- 未选中对象
- 选中非 mesh
- 空 mesh
- 有开放边界的坏网格
- 没有 sharp 基础且自动重建失败

预期：
- 全部直接报错并 `CANCELLED`

### 11.4 数据层验证
- 确认 attribute 类型正确
- 确认 domain 为 `FACE`
- 确认写入值只有预期范围
- 确认 Blender 保存/重开后 attribute 仍然存在

## 12. 主要风险与应对

### 风险 1：CAD patch 边界并未可靠保留到 sharp/split normal
- 表现：region 分割不成立，大块主体面和过渡面粘在一起
- 应对：
  - 第一版明确输入约束，要求先 `Fix CAD Obj`
  - 若样本仍失败，再考虑在第二阶段加入 angle-based fallback

### 风险 2：窄但非 bevel 的装饰面被误判
- 表现：小铭牌、小台阶、独立小 patch 被当作 bevel
- 应对：
  - 强化“至少连接两块主 region”的条件
  - 加入面积比例和邻接规则抑制

### 风险 3：corner patch 或复杂 patch 的凸凹性混杂
- 表现：总 bevel 被识别出来，但 convex / concave 分类冲突或为空
- 应对：
  - 增加第二轮“小角块并入”规则
  - 对无法稳定分类的 patch 保守写入总 bevel，不强行写 convex/concave
  - 在验证样本里专门覆盖多向圆角案例

### 风险 4：大圆滑造型面被误抓
- 表现：主圆柱或大圆角整体进了 bevel mask
- 应对：
  - 宽度阈值使用场景单位，而不是纯相对比例
  - 结合相邻 region 面积比过滤主体曲面

### 风险 5：第一版就试图解决 Unreal 打包，导致方案被提前绑死
- 表现：attribute 命名、域、数值设计受导出实现拖累
- 应对：
  - 这次只输出中间表示
  - Unreal 映射放到后续单独任务

## 13. 推荐实施顺序

推荐按下面顺序实现，能最大化减少返工：

1. 先补 `FACE` 域多 attribute 写入工具。
2. 再做 region 分割，并确认 region 质量。
3. 再做 bevel 分类规则。
4. 再做 convex / concave 分类。
5. 再做 corner patch 并入。
6. 最后接 operator 和 UI。

原因：
- 如果一开始就直接在 operator 里糊分类逻辑，后续调试会非常痛苦。
- 这类几何识别问题，先确认中间结构是否正确，比先追最终 mask 更重要。

## 14. 最终建议

这个功能第一版最合适的定义是：

**“对 Plasticity/CAD 导入的 hard-surface mesh，按 CAD patch/过渡区特征识别 bevel 面 region，并分别写入总 bevel、convex bevel、concave bevel 三张 FACE 域 float attributes。”**

不要把它第一版定义成：

- “恢复原始 bevel 历史”
- “直接导出 Unreal vertex color”
- “适配所有 mesh 来源的一般 bevel 检测器”

前者在你的输入前提下并不成立，后两者会把范围和风险都提前放大。当前最稳的做法，是先把 **中间表示** 做对，再让后续导出和 shader 消费它。
