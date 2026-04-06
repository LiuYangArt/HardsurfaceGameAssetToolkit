# Blender Trimsheet Alpha 矩形切片 Operator 实施计划

> Implementation Plan, Task List and Thought in Chinese

## 1. 文档目标

本文档用于规划一个 Blender 5.0+ 的 operator。用户先手动选中一个已经配置好带 alpha 贴图材质的 plane mesh，然后执行该 operator。operator 需要先检查材质是否合法，再根据贴图中的透明区域自动识别独立图片元素，把每个元素输出为一个独立的矩形 mesh 片，并保证每个片的 pivot/origin 位于几何中心。

本文档只规划，不写代码。范围严格限制为“矩形片切分”，不包含真实轮廓裁边、自动抠图、语义分组、复杂 UI 或 Geometry Nodes 方案。

## 2. 需求收敛

### 2.1 输入前提
- 用户选中一个 `MESH` 对象。
- 该对象本质上是一个平面基底，承担“空间基准”和“材质来源”的作用。
- 该对象已经有材质，并且材质里已经引用了一张带 alpha 的 texture。
- 该对象的 UV 约定为填满第一象限，也就是使用 `[0, 1] x [0, 1]` 的完整区域。

### 2.2 输出目标
- 根据透明区域，把贴图中的每个独立元素转成一个独立矩形 mesh 片。
- 每个矩形片都保留与原图相对应的 UV 区域，因此继续采样同一张 atlas。
- 每个矩形片的 origin 位于自身中心。
- 结果对象默认继承原 plane 的材质。

### 2.3 明确不做
- 不做精确轮廓裁边。
- 不做白底/黑底自动抠图。
- 不做跨元素的“语义合并”。
- 不做非矩形 plane 或任意拓扑输入的宽松支持。
- 不做 fallback 材质推断链路。

## 3. Blender 5.0+ API 依据

以下 API 足以支撑本功能：

### 3.1 图像读取
- `bpy.types.Image.pixels`
- `bpy.types.Image.size`
- `bpy.types.Image.channels`
- `bpy.types.Image.alpha_mode`

用途：
- 读取整张图片的 RGBA 像素缓冲。
- 获取贴图宽高。
- 判断是否具备 alpha 通道语义。

参考：
- [Blender API: bpy.types.Image](https://docs.blender.org/api/current/bpy.types.Image.html)

### 3.2 材质检查
- `bpy.types.Material.use_nodes`
- `bpy.types.Material.node_tree`
- `bpy.types.Material.blend_method`
- `bpy.types.Material.alpha_threshold`

用途：
- 验证材质是否为节点材质。
- 检查是否能定位到 `Image Texture` 节点。
- 验证材质是否至少具备 alpha 渲染配置基础。

参考：
- [Blender API: bpy.types.Material](https://docs.blender.org/api/current/bpy.types.Material.html)

### 3.3 几何与对象控制
- `bpy.types.Object.location`
- `bpy.types.Object.bound_box`
- `bpy.types.Object.dimensions`
- `bpy.types.Object.matrix_world`
- `bpy.ops.object.origin_set`
- `bpy.ops.object.mode_set`

用途：
- 把 UV 中的矩形映射回 plane 的局部/世界坐标。
- 在需要时使用标准 origin 操作。

参考：
- [Blender API: bpy.types.Object](https://docs.blender.org/api/current/bpy.types.Object.html)
- [Blender API: bpy.ops.object](https://docs.blender.org/api/current/bpy.ops.object.html)

### 3.4 Mesh / BMesh 构建
- `bpy.types.Mesh.uv_layers`
- `bpy.types.Mesh.materials`
- `bmesh.ops.create_grid`
- `bmesh.ops.delete`
- `bmesh.ops.remove_doubles`
- `bmesh.ops.contextual_create`

用途：
- 创建结果 mesh。
- 设置 UV 和材质。
- 在需要时做简单的 BMesh 构建或清理。

参考：
- [Blender API: bpy.types.Mesh](https://docs.blender.org/api/current/bpy.types.Mesh.html)
- [Blender API: bmesh.ops](https://docs.blender.org/api/current/bmesh.ops.html)

## 4. 方案比较

### 4.1 方案 A：分析 alpha 后直接生成新 quad

流程：
- 读取材质贴图 alpha。
- 做连通域分析。
- 每个连通域求一个像素级矩形包围盒。
- 把矩形映射成 plane 上的一个独立 quad。

优点：
- 拓扑最干净。
- 结果就是用户真正想要的独立矩形片。
- 最容易保证 origin 居中。
- 不依赖大量编辑模式 `ops`，更适合插件稳定运行。

缺点：
- 本质上是“基于 plane 和 texture 生成新片”，不是“真切原 plane”。

判断：
- 推荐，且与当前目标最一致。

### 4.2 方案 B：把原 plane 切成密集网格后删除透明区

流程：
- 先按像素或块级别切原 plane。
- 再根据 alpha 删除透明面。
- 最后分离结果并清理。

优点：
- 直觉上像“真的在切 plane”。

缺点：
- 网格量大，复杂度和分辨率强绑定。
- 对矩形输出目标而言完全多余。
- 后期清理和分离的稳定性差。

判断：
- 不推荐。

### 4.3 方案 C：追踪真实轮廓后再输出

优点：
- 为未来精确轮廓裁边铺路。

缺点：
- 当前需求明显不需要。
- 处理洞、轮廓简化、抗锯齿边界都会增加复杂度。

判断：
- 暂不纳入本轮。

## 5. 推荐技术方案

### 5.1 Operator 合约

建议把这个 operator 定义成一个严格输入契约的工具，而不是宽松的“尽量猜用户意图”工具。这样更稳，也更符合当前插件风格。

建议的执行前提：
- 当前必须有一个激活对象。
- 激活对象必须是 `MESH`。
- 只接受一个主要输入对象，不支持多选批处理。
- 输入对象必须有至少一个材质槽。
- 能从材质节点树中找到有效的 image texture。
- 图像必须具备 alpha 信息。

如果任一条件不成立，operator 直接 `CANCELLED` 并给出明确报错。

### 5.2 材质合法性检查

材质检查建议分三层：

第一层，基础存在性：
- 对象有材质槽。
- 激活材质不为空。
- `material.use_nodes == True`
- `material.node_tree` 存在

第二层，贴图定位：
- 能定位到一个 `Image Texture` 节点，且 `node.image` 不为空。
- 优先使用实际接入主 shader 的那张图，不要盲目取节点树里第一个 image node。

第三层，alpha 可用性：
- `image.channels >= 4`
- 图像 alpha 不是全 1
- 材质具备 alpha 显示相关设置，例如 `blend_method` 不是完全不透明的错误配置

注意：
- `Image.alpha_mode` 只能说明 alpha 解释方式，不等同于图里真的有透明区域。
- 真正可靠的判断仍然应包含对像素 alpha 的采样检查。

### 5.3 图像分析策略

核心目标不是恢复精确轮廓，而是识别“每个独立元素的矩形范围”。因此建议流程如下：

1. 读取整张图像的 alpha 数据。
2. 根据 `alpha_threshold` 做二值化。
3. 把 alpha 大于阈值的像素视为“实心区域”。
4. 在二维像素网格中做连通域分析。
5. 对每个连通域求 axis-aligned bounding box。

这里建议把阈值和最小区域面积都设计成 operator 属性：
- `alpha_threshold`
- `min_region_pixels`

这样后续面对抗锯齿边缘和小噪点时，用户有调整空间。

### 5.4 连通域定义

建议默认使用 8 邻域，而不是 4 邻域。

原因：
- 对抗锯齿边缘更宽容。
- 对细字、斜线、图标边缘的识别更稳定。

但要明确一个事实：
- 如果一个“语义元素”内部本来就是断开的，例如几段文字彼此完全不连，算法会把它拆成多个连通域。

当前版本不建议做语义合并，这属于下一轮需求。

### 5.5 像素矩形到 UV 的映射

每个连通域得到像素包围盒后，需要把它转成 UV 矩形：

- `u0 = min_x / image_width`
- `u1 = (max_x + 1) / image_width`
- `v0 = min_y / image_height`
- `v1 = (max_y + 1) / image_height`

需要特别注意两点：

1. `Image.pixels` 的行序与 V 方向  
必须在实现时用 2x2 或 4x4 彩色测试图做一次实测确认，否则极容易上下翻转。

2. 包围盒边界是否外扩  
为了防止透明边缘裁得过紧，建议支持一个可选的像素 padding：
- `padding_pixels`

默认可以从 1 像素开始，避免抗锯齿边缘被裁掉。

### 5.6 UV 矩形到 plane 空间的映射

这一层是本功能的关键前提，所以必须写死输入契约：

- 输入对象应被视为“矩形 plane 基底”。
- 它的局部空间应能用一个二维矩形来表达。
- UV `[0,1]` 对应 plane 的完整面域。

推荐的处理思路：
- 基于 plane 的局部包围盒或四角点，建立 `UV -> local XY` 映射。
- 对于每个 UV 矩形，在 plane 局部空间里得到对应的局部矩形。

为了避免把问题做大，建议第一版额外加入一个保守前提：
- 输入 plane 最好是单面或标准矩形平面，不支持复杂拓扑 plane。

如果检测到对象明显不是这种输入，直接报错并终止。

### 5.7 结果 mesh 生成策略

第一版最稳的方案不是“切原 mesh”，而是“为每个矩形区域生成一个新的 quad object”。

推荐做法：
- 每个区域单独创建 mesh datablock 和 object。
- 每个对象只有 4 个顶点和 1 个四边形面。
- 局部几何直接以自身中心为原点生成。
- 对象的世界变换放到对应矩形中心位置。

这样做的好处：
- origin 天然在中心。
- 不需要先创建再调用 `origin_set` 修正。
- 不依赖编辑模式和选择上下文。

只有在实现中发现局部生成方式会破坏某些预期时，才退回到：
- 先生成几何
- 再用 `bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='MEDIAN')`

### 5.8 材质与 UV 继承

每个结果片应默认继承原材质，这样它们都继续采样同一张 atlas。

建议规则：
- 新对象沿用原 plane 的主材质。
- 新对象的 UV 只有一个主 UV 层。
- 该 UV 层的四个角直接对应各自矩形的 `u0/v0/u1/v1`。

如果源对象有多材质槽或多个 UV 层，第一版建议明确只继承“当前主材质 + 主 UV 层”。

### 5.9 结果命名与组织

建议给结果对象统一命名，例如：
- `<原对象名>_decal_001`
- `<原对象名>_decal_002`

建议支持一个简单选项：
- 保留原 plane
- 或执行成功后隐藏原 plane

第一版不建议自动删除原 plane，保留更安全。

### 5.10 执行结果反馈

operator 完成后应向用户报告：
- 识别出的连通域数量
- 实际生成的片数量
- 被忽略的小噪点数量
- 使用的 alpha 阈值和最小区域阈值

这样用户能快速判断是材质、阈值还是贴图本身的问题。

## 6. 模块落点建议

结合当前仓库结构，建议如下拆分：

### 6.1 Operator
- 放在 [operators/decal_ops.py](D:/ArtPresets/Blender/BlenderConfig/extensions/vscode_development/HardsurfaceGameAssetToolkit/operators/decal_ops.py)

理由：
- 语义上属于 decal / texture-to-decal 处理。
- 当前仓库已经有 decal 相关 operator。

### 6.2 新增工具模块

建议新增一个轻量图像分析工具模块，例如：
- `utils/image_utils.py`

职责：
- 从材质节点中提取图像
- 读取 alpha
- 二值化
- 连通域分析
- 输出像素包围盒

现有 `material_utils.py` 可以负责材质定位，但不建议把连通域分析直接塞进去。

### 6.3 复用现有工具
- [utils/material_utils.py](D:/ArtPresets/Blender/BlenderConfig/extensions/vscode_development/HardsurfaceGameAssetToolkit/utils/material_utils.py)
- [utils/uv_utils.py](D:/ArtPresets/Blender/BlenderConfig/extensions/vscode_development/HardsurfaceGameAssetToolkit/utils/uv_utils.py)
- [utils/bmesh_utils.py](D:/ArtPresets/Blender/BlenderConfig/extensions/vscode_development/HardsurfaceGameAssetToolkit/utils/bmesh_utils.py)

## 7. 详细任务拆解

### Phase 1：输入契约和错误处理
- 定义 operator 的输入对象约束。
- 明确报错文案。
- 明确哪些情况直接取消执行。

### Phase 2：材质与图像提取
- 从激活对象读取主材质。
- 在节点树中定位 image texture。
- 提取图片对象、尺寸、像素、alpha 状态。

### Phase 3：alpha 二值化和连通域分析
- 实现 alpha 阈值二值化。
- 实现 8 邻域连通域分析。
- 加入最小像素区域过滤。
- 产出每个区域的像素包围盒。

### Phase 4：plane 空间映射
- 明确 plane 的局部矩形范围。
- 实现像素矩形 -> UV 矩形 -> 局部矩形的映射。
- 验证 `V` 轴方向是否正确。

### Phase 5：结果 quad 生成
- 为每个区域创建独立 mesh/object。
- 写入四个顶点、一个面和对应 UV。
- 继承材质。
- 保证局部原点位于几何中心。

### Phase 6：结果整理
- 统一命名。
- 处理 collection 放置。
- 可选隐藏原 plane。
- 输出汇总报告。

### Phase 7：验证与回归
- 用简单测试图验证像素行序和 UV 方向。
- 用你提供的 atlas 验证分片数量和定位。
- 复核 origin 是否真的在每片中心。
- 检查材质继承后显示是否正确。

## 8. UI / 属性建议

第一版建议只给少量必要参数：

- `alpha_threshold`
  - 用途：控制透明判定阈值
  - 默认建议：`0.1` 或 `0.25`

- `min_region_pixels`
  - 用途：过滤小噪点
  - 默认建议：`16` 或 `32`

- `padding_pixels`
  - 用途：给矩形外扩 1~2 像素，保留抗锯齿边缘
  - 默认建议：`1`

- `hide_source_plane`
  - 用途：是否在生成后隐藏原 plane
  - 默认建议：`False`

不建议第一版加入：
- 复杂预览
- 多种材质查找策略
- 连通域合并策略
- 自动分类输出多个 collection

## 9. 手动测试计划

### 9.1 极小测试图

先准备一张非常小的 RGBA 测试图，例如 4x4：
- 左上和右下放不同颜色块
- 其余透明

测试目的：
- 验证 `Image.pixels` 的读取方向
- 验证 `V` 轴是否上下翻转
- 验证包围盒转 UV 是否准确

预期结果：
- 生成两个独立片
- 每片采样位置与贴图区域严格对应

### 9.2 规则 atlas 测试

准备若干规则矩形 decal：
- 横条
- 竖条
- 小图标
- 留出明显透明边距

测试目的：
- 验证多连通域切片
- 验证矩形片尺寸是否正确
- 验证 origin 是否居中

### 9.3 实战 atlas 测试

直接用你给的这类 trimsheet / decal atlas 测：
- 文本条
- logo
- 多个矩形牌
- 小图标

测试目的：
- 看是否会把噪点误识别为独立区域
- 看长条元素是否被正确识别
- 看小元素是否需要提高 `min_region_pixels`

### 9.4 非法输入测试

逐项验证这些场景：
- 未选中对象
- 选中非 mesh
- 无材质
- 材质无节点
- 找不到 image texture
- 图像无 alpha
- 图像 alpha 全不透明
- 输入对象不是简单 plane

预期结果：
- 全部直接报错取消，不产生脏数据。

## 10. 主要风险与应对

### 风险 1：像素行序和 UV 的 `V` 方向不一致
- 表现：结果上下翻转。
- 应对：实现阶段必须先做极小测试图验证，不要靠记忆硬写。

### 风险 2：文字或复杂图形被拆成多个连通域
- 表现：一个视觉元素被拆成多个片。
- 应对：第一版接受该行为，并在文档中明确它是“按连通域”而不是“按语义元素”切分。

### 风险 3：半透明边缘裁切过紧
- 表现：边缘发毛或内容被吃掉。
- 应对：提供 `alpha_threshold` 和 `padding_pixels`。

### 风险 4：输入 plane 不是标准矩形基底
- 表现：映射后尺寸或位置异常。
- 应对：第一版严格校验输入，宁可拒绝执行，也不做不可靠 fallback。

### 风险 5：大图读取性能
- 表现：超大 atlas 在 Python 层扫描偏慢。
- 应对：第一版通常仍可接受；必要时后续再考虑 NumPy 或更快的数据遍历方式。

## 11. 推荐实施顺序

推荐按下面顺序实现，能最大化减少返工：

1. 先做材质检查和图像提取。
2. 再做极小测试图的 alpha 读取验证。
3. 再做连通域和像素包围盒。
4. 再做像素矩形到 UV / plane 的映射。
5. 再做结果 quad 生成和材质继承。
6. 最后补 UI 参数、命名和汇总报告。

这样做的原因是：
- 一旦像素方向和映射关系确认，后续工作就基本是机械实现。
- 如果这一步没先钉死，后面所有几何结果都会错位。

## 12. 最终建议

这个功能现在最合适的定义是：

“基于选中 plane 的 alpha atlas 自动生成独立矩形 decal 片。”

不要把它定义成：

“对原 plane 做真实切割。”

前者是用户真正想要的结果，也最符合插件开发里的稳定性和可维护性；后者会把实现复杂度拉高，但不会带来实际收益。
