# Curvature Wear Signal 迭代计划

> Iteration Plan, Task List and Technical Direction in Chinese

## 1. 文档目标

本文档用于规划当前 bevel face attribute 方案的下一轮迭代方向。

这次迭代的目标不是继续提高“bevel 面语义识别”的命中率，而是调整问题定义，转向更接近 Substance Painter、Marmoset Toolbag 等烘焙软件的思路：

**先为 mesh 生成稳定、可分离 convex / concave、并且尽量少损失信息的 curvature-style raw signal，再把它写入 mesh attribute 作为后续一切转换与消费的源数据。**

这份文档只规划，不写代码。范围聚焦于：

- 为什么旧方案不稳定
- curvature baker 风格方案的原理参考
- 在 Blender mesh attribute 语境下如何落地
- 下一轮实现的阶段划分与验证标准

本文档不包含：

- Unreal 侧材质节点实现
- 贴图空间 curvature baker 复刻
- 高模到低模烘焙链路
- 所有 mesh 来源的通用曲率解算器

## 2. 问题重定义

### 2.1 旧问题定义

旧方案实际在解的问题是：

**“哪些 face 属于 CAD 导入 mesh 里的 bevel patch。”**

这个定义的问题在于：

- 它强依赖 CAD tessellation 是否保留了足够稳定的 patch 结构
- 它强依赖 sharp / split-normal 边界是否与视觉上的 bevel 区域一致
- 它天然偏向离散分类，而不是连续信号
- 它与最终 shader 消费目标并不完全一致

最终导致的现象是：

- 换一个 mesh，region 结构稍微变一下，结果就崩
- 很容易把算法调成“只对当前样本工作”
- 即便识别正确，也未必是最适合 edge wear 的 mask

### 2.2 新问题定义

新方案要解的问题应改为：

**“如何从 mesh 的法线场 / 几何场中提取稳定的 signed curvature signal，并进一步派生出 convex wear mask 与 concave cavity mask。”**

这个定义更接近实际目标，原因是：

- 最终需要的是稳定的边缘强度场，而不是 face 语义标签
- curvature-style signal 对拓扑变化的容忍度通常比 patch classification 更高
- convex / concave 分离天然可以由 signed signal 表达，而不是后验猜测
- 这条路线更接近 Substance Painter / Marmoset 的生产逻辑

## 3. 对 Substance / Marmoset 思路的参考判断

### 3.1 它们通常不是在做 bevel patch 识别

这类软件做 curvature mask 时，通常不是先判断“哪些面是 bevel 面”，而是从表面信号里提取：

- 哪些位置是局部凸起
- 哪些位置是局部内凹
- 这些变化的强度有多大
- 这些变化出现在什么尺度上

因此它们的结果本质上更像：

**连续曲率信号 + 过滤 + remap**

而不是：

**离散面分类 + 硬阈值挑选**

### 3.2 它们常用的基础信号来源

主流可概括为两类：

#### A. 几何曲率近似

从几何邻域关系直接估计 curvature-like value，例如：

- face normal 差分
- edge dihedral angle
- mean curvature 近似
- Laplacian / 邻域偏移量
- 邻域法线散度

优点：

- 不依赖已有贴图
- 可以直接在 mesh 上算

缺点：

- 对低 tessellation 或离散 patch 容易产生块状感
- 仅使用 face normal 时，信号偏硬，容易受拓扑支配

#### B. 法线场导数

从 custom normals / split normals / baked normal map 出发，分析法线场变化。

优点：

- 更接近最终视觉结果
- 对 CAD 导入模型尤其有价值，因为很多“圆滑感”就存在于 custom normal 里

缺点：

- 在 mesh attribute 路径里，需要把贴图空间思路改写成 mesh-space 采样
- 如果仅有粗糙的顶点法线，局部精度会受限制

### 3.3 它们为什么效果通常更稳

核心原因不是“公式更复杂”，而是问题建模更贴近最终用途：

- 处理对象是连续信号，不是离散类别
- 允许结果是灰度，而不是 0 / 1
- 后面会加平滑、半径、对比度、bias、levels 等控制
- 最终目的是做材质遮罩，不是做 CAD 语义分割

结论：

**可以参考，而且应该参考。**

但参考重点不是复刻某个 baker 的界面或参数，而是把算法目标切换到 curvature-style signal extraction。

## 4. 新方案的核心设计原则

### 4.1 主输出不再是“bevel faces”

下一轮主输出建议改成：

- `CurvatureSigned`
- `CurvatureConvex`
- `CurvatureConcave`
- 可选的 `WearMask`

其中：

- `CurvatureSigned` 是基础信号
- `CurvatureConvex` / `CurvatureConcave` 是拆分后的可消费信号
- `WearMask` 只是基于 convex signal 再做一层风格化，不应替代基础信号

### 4.2 先做基础场，再做风格化

新算法必须拆成两层：

#### Layer 1: 基础 curvature signal

输出尽量物理一致、连续、稳定的 signed signal。

#### Layer 2: 生产可用 mask

在基础 signal 上再做：

- convex / concave 分离
- 宽度控制
- smooth / blur
- contrast / remap
- 高频 / 低频分层

这样做的好处是：

- 基础层更容易验证是否“算对了”
- 风格层更容易针对不同下游需求单独调整
- 不会把“识别错误”和“风格不对”混在一起

### 4.3 尽量不依赖拓扑 patch 语义

下一轮不再把 sharp region 作为主骨架。

sharp / split normal 可以保留为辅助信息，但不应成为整个算法的核心前提。更合理的使用方式是：

- 作为 feature edge 增强信号
- 作为 curvature 信号的局部权重因子
- 作为 debug 参考，而不是主分割基础

### 4.4 必须避免修改原 mesh shading

这是这轮迭代的硬约束。

任何用于分析的中间数据都必须满足：

- 不修改 `edge.smooth`
- 不修改 `use_edge_sharp`
- 不修改 `use_seam`
- 不破坏 custom normals
- 不引入 viewport shading 副作用

## 5. 候选技术路线比较

### 5.1 方案 A：基于 face normal / edge angle 的简化 signed curvature

思路：

- 对每条 edge 计算二面角或法线差
- 把 edge 信号分摊到相邻顶点或相邻面
- 对邻域做加权平均，得到 convex / concave 强度

优点：

- 实现成本低
- 易于调试
- 不依赖 Blender 内部复杂法线接口

缺点：

- 仍然偏离散
- 对 tessellation 密度敏感
- 在 CAD 圆角上容易得到“边线感”，不够像 baker 的连续结果

判断：

- 适合作为第一层原型或 fallback
- 不适合作为最终主方案

### 5.2 方案 B：基于 custom normal / split normal 的 curvature signal

思路：

- 从 loop normal / corner normal 采样表面法线场
- 根据邻域法线变化估计 signed curvature
- 优先直接保存为 `CORNER` 域 raw attribute

优点：

- 最接近 Painter / Marmoset 的法线场处理逻辑
- 更接近用户在 viewport 里看到的真实圆滑效果
- 对 CAD 导入模型更有机会得到稳定结果

缺点：

- Blender 中 loop / custom normal 的采样与传递稍复杂
- 后续从 `CORNER` 到 `POINT` / `FACE` 的聚合规则需要明确定义
- 验证时需要额外检查是否被 custom normal 质量主导

判断：

- 推荐作为本轮主方案

### 5.3 方案 C：混合方案

思路：

- 主信号来自 custom normal / split normal
- 用 edge dihedral / sharp edge / curvature magnitude 作为辅助增强
- 最终做多通道融合

优点：

- 稳定性和可控性最好
- 能同时兼顾 chamfer、fillet、硬边和圆滑边

缺点：

- 参数更多
- 如果一开始就做太复杂，调试难度会急剧上升

判断：

- 适合作为第二阶段增强
- 不适合第一步就全量上

## 6. 推荐路线

### 6.1 主方案

推荐采用：

**方案 B 为主，方案 A 为 fallback，方案 C 作为后续增强。**

具体顺序：

1. 先建立 mesh-space 的 signed curvature 基础信号
2. 优先利用 custom normal / split normal
3. 若某些 mesh 无法可靠提供该信号，再退回几何法线差近似
4. 等基础信号稳定后，再做 wear-specific 风格化

### 6.2 为什么不继续修旧方案

因为旧方案的核心问题不是某个 bug，而是问题建模本身偏了。

继续修旧方案会持续陷入这些局部优化：

- 让 region 更准一点
- 让 corner 合并更稳一点
- 让某个样本不过拟合一点

但这些优化并不能改变它天然脆弱的事实。

相比之下，把目标换成 curvature-style signal，能让算法结构更贴近最终用途。

## 7. 数据模型建议

### 7.1 Attribute 域选择

下一轮不建议继续把主信号放在 `FACE` 域。

原因：

- curvature 是连续场，不是 face 常量
- `FACE` 域太离散，角上和 bevel 过渡区很容易断
- 这会天然削弱“类似 Painter curvature map”的效果

建议选择：

#### 主推荐：`CORNER` 域

优点：

- 与 loop normal / split normal 的原始形态最一致
- 能保留同一个顶点在不同面角上的不同响应
- 是当前阶段最接近“原始测量值”的存储域

缺点：

- 数据量更大
- 可视化与后续聚合都更复杂

#### 派生域：`POINT` 域

用途：

- 用于后续聚合预览
- 用于调试比较
- 用于之后的转换步骤

限制：

- 一旦从 `CORNER` 压缩到 `POINT`，就已经发生了不可逆的信息合并
- 因此不应作为 raw curvature signal 的 canonical 存储域

建议结论：

- 第一轮 curvature-style 迭代应把 `CORNER` 域 raw signal 作为 canonical data model
- `POINT` 域只作为后续派生结果，不作为主存档

### 7.2 Attribute Schema 建议

推荐基础输出：

- `02_CurvatureSignedRaw`
  - `FLOAT`
  - `CORNER`
  - 原始 signed signal，负值表示 concave，正值表示 convex
- `03_CurvatureMagnitudeRaw`
  - `FLOAT`
  - `CORNER`
  - 原始强度绝对值
- `04_CurvatureConvexRaw`
  - `FLOAT`
  - `CORNER`
  - `max(signed, 0)`
- `05_CurvatureConcaveRaw`
  - `FLOAT`
  - `CORNER`
  - `max(-signed, 0)`

第二层原始增强输出建议：

- `06_CurvatureSignedAccumRaw`
  - `FLOAT`
  - `CORNER`
  - 对 signed raw 做局部邻域 graph accumulation / blur 后得到的宽域响应
- `07_CurvatureMagnitudeAccumRaw`
  - `FLOAT`
  - `CORNER`
  - 对 magnitude raw 做局部邻域 graph accumulation / blur 后得到的宽域响应
- `08_CurvatureConvexAccumRaw`
  - `FLOAT`
  - `CORNER`
  - 对 convex raw 做局部邻域 graph accumulation / blur 后得到的宽域响应
- `09_CurvatureConcaveAccumRaw`
  - `FLOAT`
  - `CORNER`
  - 对 concave raw 做局部邻域 graph accumulation / blur 后得到的宽域响应

后续派生输出：

- `POINT` 域聚合版本
- 风格化后的 wear / cavity mask

建议先不要一开始就把 `WearMask` 当主信号。

先把基础 curvature raw signal 做对，再派生其他数据。

## 8. 拟定算法流程

### Step 1: 读取 mesh 的法线场

优先级：

1. custom / split normals
2. loop normals
3. face normals fallback

目标：

- 得到一个尽量贴近视觉表面的法线场

### Step 2: 建立局部邻域

对于每个 corner 建立一圈或多圈邻域。

候选策略：

- 1-ring adjacency
- 基于 edge length 的半径邻域
- 面积 / 边长加权邻域

第一轮建议：

- 先从 1-ring 开始
- 再引入一个简单的距离权重

### Step 3: 计算 signed curvature-like value

候选计算方式：

- 相邻法线差的加权平均
- 邻域法线平均与当前位置法线的偏差
- 局部几何位置与切平面的偏离量
- edge dihedral sign 辅助判定正负

这里最重要的不是追求严格数学曲率，而是：

- 符号稳定
- 强度连续
- 对 bevel / fillet / chamfer 响应合理

### Step 4: 生成基础 signed signal

得到每个 corner 的：

- signed curvature
- raw magnitude

要求：

- 正负号在凸凹区域一致
- 大平面接近 0
- bevel 过渡区形成连续带状响应

### Step 5: 分离 convex / concave

从 signed signal 直接拆分：

- `convex = max(signal, 0)`
- `concave = max(-signal, 0)`

这一步应该是派生，而不是重新分类。

### Step 6: 风格化生成 wear signal

对 convex signal 增加：

- blur / smooth
- remap
- contrast
- width control
- clamp

输出更适合后续做单独派生与风格化的 mask。

### Step 7: 可选频率分离

如果基础结果中包含过多大尺度缓变曲率，可增加：

- micro curvature
- macro curvature

再用偏高频部分驱动 wear。

这样能更接近 Painter 里“只抓局部边缘”的效果。

## 9. 实施步骤计划

### Phase 1: 终止旧目标扩散

- 不再继续增强 bevel face patch 分类逻辑
- 明确旧 operator 的状态为“实验性”
- 不再把它当主路径

完成标准：

- 团队内部对新问题定义达成一致：主目标是 curvature-style wear signal，而不是 bevel 面语义识别

### Phase 2: 建立基础 signal 原型

- 在 `utils` 中实现 raw signed curvature 计算
- 先生成 debug attribute
- 验证正负号是否稳定

完成标准：

- 对至少 2 到 3 个 CAD 样本，能看到合理的凸凹连续信号

### Phase 3: Convex / Concave 拆分与风格化

- 从 signed signal 派生 convex / concave raw split
- 实现基础 remap / smooth / clamp
- 得到第一版可用派生 mask

完成标准：

- convex mask 能稳定覆盖主要外凸磨损边缘
- concave mask 能稳定覆盖主要内凹积灰 / cavity 区域

### Phase 4: 域与聚合策略收敛

- 确认 `CORNER` 域 raw signal 的可读性与稳定性
- 设计从 `CORNER` 到 `POINT` / `FACE` 的聚合规则
- 验证不同聚合规则对视觉结果的影响

完成标准：

- raw / derived 的职责不再混淆
- 数据域选择不再摇摆

### Phase 5: UI 与参数收敛

- 只保留必要参数
- 隐藏过多实验性开关
- 保证默认值在多样本上合理

完成标准：

- 用户不需要为每个 mesh 重新调一遍参数

## 10. 参数设计建议

第一轮只建议开放少量参数：

- `sample_radius`
  - 控制邻域尺度
- `convex_gain`
  - 控制凸信号强度
- `concave_gain`
  - 控制凹信号强度
- `smooth_iterations`
  - 控制平滑程度
- `wear_contrast`
  - 控制 edge wear mask 的对比度

不建议第一轮开放：

- 大量复杂阈值
- 多套算法切换开关
- UI 中暴露所有 debug 选项

## 11. 验证计划

### 11.1 信号层验证

- 平面区域应接近 0
- 明显 convex 倒角应为正
- 明显 concave 槽口应为负
- 响应应连续，而不是零碎面块

### 11.2 视觉目标验证

- 结果应更像 baker 输出的 curvature edge signal
- 不要求严格“识别 bevel faces”
- 要求对 wear 用途有生产价值

### 11.3 样本泛化验证

至少覆盖：

- 规则 chamfer 硬表面
- 带 fillet 的 CAD 模型
- 有凹槽 / 孔口 / 台阶的模型
- 不同 tessellation 密度的导入网格

### 11.4 工程验证

- 不修改原 mesh shading
- 不污染 seam / sharp / smooth
- attribute 重复执行可覆盖
- raw 数据与派生数据结构稳定

## 12. 主要风险与应对

### 风险 1：信号过于响应大尺度曲面

表现：

- 大圆柱、大圆角整体都发亮，不像 edge wear

应对：

- 增加半径控制
- 做高频 / 低频分离
- 用 remap 压掉缓变曲率

### 风险 2：`CORNER` 域数据过重或过于复杂

表现：

- 原始信号保真度高，但调试和使用成本上升

应对：

- 接受 `CORNER` 作为 source of truth 的成本
- 在后续阶段补 `POINT` 聚合版本用于查看和转换

### 风险 3：不同导入来源的 custom normal 质量不稳定

表现：

- 某些 mesh 的 split normal 信号很好，另一些很差

应对：

- 保留几何法线差 fallback
- 设计统一的质量检测与自动切换逻辑

### 风险 4：直接追求“像 Painter 一样”导致过拟合视觉风格

表现：

- 基础信号不干净，只能靠后处理硬修

应对：

- 基础层与风格层严格分开验证
- 先验证 raw signal，再验证 mask 风格

## 13. 推荐实施顺序

推荐顺序如下：

1. 先定义新的输出 schema
2. 再做 raw signed curvature prototype
3. 再做 convex / concave 派生
4. 再做 wear-specific 风格化
5. 最后再决定 UI 与聚合映射

原因：

- 旧方案的问题不在 UI，而在算法目标
- 先把基础信号做对，比先做界面和后续转换更重要

## 14. 最终建议

这轮迭代应明确转向：

**“在 Blender mesh 上生成 `CORNER` 域的 curvature-style raw signed signal，再由此派生 convex / concave 与其他后续格式。”**

而不是继续坚持：

**“稳定识别所有 bevel faces。”**

前者更接近 Substance Painter / Marmoset 的实际生产方法，也更符合你最终在 Unreal 里对 edge wear 的需求。

这意味着下一步的主任务不应该是继续修补旧的 bevel-face operator，而应该是新建一条 **curvature signal pipeline**，把旧 operator 视为一次验证失败的探索分支。

