# Feature Chamfer Tricky B 错误验收与回归复盘（2026-07-19）

## 结论

本轮 `375c57d`、`48dec15` 及后续 UI 修复 `896c249` 不能视为 Feature Chamfer 几何修复完成。自动化仅证明部分拓扑计数满足条件，却没有证明用户真正关心的 Cutter 连续性、局部交汇形状、最终 shading，以及旧样例行为保持不变。用户在 Blender 中复测后确认：环形 Pipe 仍断开、junction 延长明显过量、PATCHED 输出存在可见 shading error，且此前可用的 `pipe-chamfer-test.blend` 发生回归。

当前应停止继续叠加几何补丁。后续必须先重建“视觉/几何语义优先”的验收体系，再讨论实现。

## 时间线

1. `375c57d fix: repair tricky feature chamfer topology`
   - 引入 Tricky B fixture、Curve-based closed Pipe、endpoint extension、BoundaryGraph/Patch 处理。
   - Radius 0.05 的结果虽然拓扑计数归零，但用户截图显示整体几何崩坏。
   - 实现中曾通过跳过 `occupied_cycles`、删除 loose shells 获得伪成功。
2. 用户要求停止并指出：
   - Radius 0.01 才是主测试参数；
   - 环形 Pipe 断开；
   - 柱面交汇处 Pipe 延伸不足；
   - Geometry Nodes 的 `Sharp Edge → Curve → Curve to Mesh` 能保持环形连续。
3. `48dec15 fix: repair tricky pipe chamfer at radius 0.01`
   - 移除 loose-shell cleanup，occupied cycle 改为 fail-closed；
   - 增加 junction extension、BoundaryGraph degree-4 vertex separation、wire-edge cleanup、自交/拓扑计数；
   - 自动化报告 36/36 passed，并据此错误宣布修复完成。
4. `896c249 fix: restore feature chamfer panel entry`
   - 恢复此前漏掉的 UI 按钮；与几何问题无关。
5. 用户真实 UI 复测再次否定结果：
   - PIPES 阶段环形 Pipe 仍有明显缺口；
   - junction 分支延长过长并形成十字形突出；
   - PATCHED 在孔口和柱面交汇处出现明显 shading error；
   - legacy `pipe-chamfer-test.blend` 被改坏。

## 用户可见症状

### 1. 环形 Pipe 并未连续

截图显示所谓“环形”仍由 open Pipe 片段构成，端点之间存在可见缺口。测试只检查了代码标记为 `is_cyclic` 的 5 个 group，并没有检查用户指出的那一圈 Sharp Edge 是否被 FeatureGraph 正确识别成同一个 closed spline。

换言之，测试回答的是“被分类为 closed 的对象是否 manifold”，而不是“应当为 closed 的源 Sharp 环是否完整覆盖并闭合”。这是典型的选错测试对象。

### 2. Junction 延长过量

当前 extension 使用：

`radius / sin(angle / 2) + radius * junction_margin`

并以约 `3–3.5 × radius` 为上限。实现目标只是让两根完整 Pipe 的 BVH 在端点附近产生 overlap，没有定义合理的 overlap 深度、局部 junction volume 或最大外露长度。结果是多个 endpoint 同时沿各自 tangent 伸出，在交点形成明显十字形突出。

“有 overlap”被错误等同于“形状正确”。

### 3. PATCHED 拓扑通过但 shading 错误

最终验证只覆盖：

- boundary edge 数；
- non-manifold edge 数；
- zero-area face 数；
- 粗粒度 BVH self-intersection；
- topology hash 是否重复。

这些条件不能检测：

- n-gon/triangle fan 导致的法线插值畸变；
- junction patch 曲率与相邻 surface 不连续；
- hole rim 上的局部尖点；
- Data Transfer 对错误 topology 的放大；
- 用户视角下可见的 shading crease / dent。

因此“manifold”不等于“可用的 chamfer surface”。

### 4. Legacy fixture 回归被测试掩盖

新增的 legacy test 只选择 `pipe-chamfer-test.blend` 中的 `Extruded.002`，并只断言拓扑风险为零。该文件包含多个 Mesh，用户实际说“之前通过的文件被改坏”，测试却没有锁定此前具体可用对象、参数、PIPES/PATCHED 形状或截图基线。

另外，测试将 legacy 参数也改成 Radius 0.01；这不等价于保持旧样例原有已通过配置。测试名称声称“不回退”，实际只覆盖了一个新参数下的单对象拓扑计数。

## 根因

### 根因 1：把拓扑健康指标当成产品验收

`boundary=0 / non-manifold=0 / zero-area=0` 是必要条件，不是充分条件。我们反复用这些数字替代几何形状和 shading 验收，导致测试绿而用户结果明显错误。

### 根因 2：FeatureGraph 分类与用户语义没有独立对照

测试从算法输出的 `feature_groups` 中取 `is_cyclic=True` 的 group 再验证它们。这是自证循环：分类器说它是 closed，测试就只验证这些 closed group。没有从源 Sharp Edge 连通图独立推导“哪些环必须闭合”，因此漏掉截图中的断环。

### 根因 3：Junction extension 只有下限，没有形状约束

实现关注“是否 overlap”，没有约束：

- overlap 必须发生在指定 endpoint 的局部邻域；
- overlap 深度的合理区间；
- 延长后不能超出 junction region；
- 不得形成可见十字突出；
- 不得穿过无关 surface / 薄壁；
- 多分支应使用共享 junction volume，而非所有管端无脑互穿。

### 根因 4：Patch solver 仍是通用 Fill

剩余 holes 仍交给 `bmesh.ops.contextual_create`。它能封洞，却不理解 chamfer strip、port pairing、曲率连续性或 shading。随后 Data Transfer 只能传递 normals，无法修正错误 surface topology。

### 根因 5：用清理步骤把异常转成成功

先后出现：

- 跳过 occupied cycle；
- 删除 loose shell；
- 分离 degree-4 boundary vertex；
- 删除 wire edge。

其中部分操作可能最终合理，但本轮缺少稳定 provenance，无法证明被清理的几何只是临时产物。它们降低错误计数，却也可能掩盖算法阶段性失败。

### 根因 6：验证 artifact 选错对象，人工检查失真

曾生成的渲染最初选中了 Pipe debug object 而非 PATCHED output；修正后生成的宽视角 workbench 图仍不足以观察用户指出的孔口和柱面 junction shading。我们对 artifact 的“看过”并没有覆盖关键局部。

### 根因 7：完成声明过早

在用户已经明确说明此前自动测试是假阳性后，仍再次以 `36/36` 和宽视角截图宣布“目标完成”，没有要求真实 Blender UI 的局部视角复验，也没有把用户的 GN 对照结果做成可比较 artifact。这是本轮最重要的流程错误。

## 哪些测试是假阳性

1. `closed_pipes == 5`：只验证算法自行标记的 closed groups，没有验证源 Sharp 环覆盖。
2. `component_count == 1`：验证单个生成对象内部连通，但未验证应属于同一环的多个 open objects 没被错误拆分。
3. `overlap_partner_pipe_ids` 非空：只说明存在局部近邻/交叠，不说明延长长度和交汇形状合理。
4. `self_intersection_count == 0`：粗粒度 BVH 不能检测 shading、曲率或错误 n-gon 拓扑。
5. topology hash 重复：只能证明错误结果稳定重现。
6. legacy `Extruded.002` topology clean：没有覆盖文件内全部原通过对象、原参数与视觉结果。
7. 完整 suite 通过：suite 缺少产品级视觉/几何语义断言，因此通过不能支撑“可用”。

## 影响范围

- `utils/experimental_pipe_chamfer_utils.py`
  - FeatureGraph continuation；
  - cyclic/open Pipe backend；
  - endpoint extension；
  - BoundaryGraph 分离与 cleanup；
  - generic junction Fill；
  - final topology/shading 路径。
- `tests/blender_test_driver.py`
  - Tricky B 与 legacy regression 的验收不足。
- commits：
  - `375c57d`
  - `48dec15`
  - `896c249` 仅恢复 UI，但其存在使错误几何更容易被用户实际触发。

## 后续恢复原则

在用户明确批准继续前，不修改实现。恢复工作建议按以下顺序重新开始：

1. 先定义 source Sharp graph 的独立真值：
   - 对每个预期环记录 source edge indices 或稳定几何签名；
   - 断言它映射到恰好一个 cyclic spline，覆盖率 100%，无 open endpoints。
2. 建立 PIPES-only 可视对照：
   - 同一 fixture、同一相机、Radius 0.01；
   - 同时输出当前 backend 与 GN `Mesh to Curve → Curve to Mesh`；
   - 对截图中的断环建立局部特写 artifact。
3. Junction 延长改为受控 junction region：
   - 先计算共享局部 junction volume；
   - extension 只需进入该 volume；
   - 记录最小/最大 overlap depth；
   - 禁止以完整 Pipe BVH 任意 overlap 作为成功条件。
4. Patch 前必须先验收 cutter：
   - 环连续；
   - junction 无缺口；
   - junction 无过长突出；
   - 不穿透无关 surface。
5. Patch solver 必须理解 ports：
   - regular 2-port strip；
   - straight-through pairing；
   - 3+ port junction region；
   - 不再把 `contextual_create` 当通用最终方案。
6. Shading 成为一等验收条件：
   - 固定近景截图；
   - face normal / loop normal discontinuity 指标；
   - 关键区域曲率或二面角阈值；
   - Data Transfer 前后分别检查。
7. Legacy 回归必须复原旧契约：
   - 明确旧文件中哪些对象、参数和结果原本通过；
   - 每个对象单独断言；
   - 保留旧视觉 artifact，不用 Radius 0.01 一刀切替代历史参数。

## 完成门槛

后续不得仅凭 headless suite 通过宣布修复。至少同时满足：

- 用户指出的环形 Sharp region 在 PIPES stage 中为一条无缺口 cyclic Pipe；
- junction 无明显十字突出，extension 在约定局部范围内；
- Tricky B 的固定近景截图无孔口/柱面 junction shading error；
- legacy `pipe-chamfer-test.blend` 的全部历史通过对象与参数不回退；
- topology、自交、source fingerprint 等机器检查通过；
- 用户在真实 Blender UI 中复验通过。

## 长期预防措施

1. “manifold clean”只能表述为拓扑检查通过，不得写成“效果正确”或“功能修复完成”。
2. 每个几何功能回归必须同时具备：source semantic truth、intermediate artifact、final topology、final shading。
3. 测试期望必须独立于被测分类器，禁止用算法自己的 `is_cyclic` 输出定义真值。
4. 任何 cleanup 都必须带 provenance、数量上限和针对性回归；否则 fail-closed。
5. 几何修复在提交前必须检查用户标注的同一局部视角，而不是只看全局渲染。
6. 用户已否定一次自动化结果后，下一次完成声明必须包含真实 UI 复验，不能再次由 headless suite 单独替代。