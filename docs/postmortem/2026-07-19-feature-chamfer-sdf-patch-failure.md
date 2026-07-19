# Feature Chamfer SDF Preview → Patch 失败复盘

> 日期：2026-07-19  
> 结论：当前 SDF Finalize 路线失败，`TRACKED_BOOLEAN_SURFACE` 不是 Chamfer；相关 Finalize 不得视为完成。  
> 复现 Blender：`C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe`（5.1.2）  
> 主测试文件：`C:\Users\LiuYang\Desktop\pipe-chamfer\pipe-chamfer-mixed.blend`，对象 `Extruded.002`  
> Curve 对照文件：`C:\Users\LiuYang\Desktop\pipe-chamfer\geo-node.blend`，对象 `Extruded.002`，Node Group `pipecut`

## 1. 失败范围

本复盘只覆盖 `Geometry Nodes SDF cutter → tracked Boolean → 删除槽面/BoundaryGraph → Patch` 尝试。此前 Curve Pipe、Boundary ownership 与假阳性验收问题见：

- `docs/postmortem/2026-07-19-feature-chamfer-false-positive-and-legacy-regression.md`
- `docs/plan/2026-07-19-feature-chamfer-tricky-b-repair-handoff.md`
- `docs/research/2026-07-18-bevel-and-robust-mesh-boolean-research.md`
- `docs/research/2026-07-19-bevel-v2-straight-skeleton-assessment.md`

## 2. 时间线与症状

1. SDF cutter 解决了 Curve Pipe 在 degree-3/4 junction 点接触、大转角 miter 拉伸、cutter 非流形等问题；cutter 本身达到 closed manifold。
2. Python Exact tracked Boolean 获得 100% original/groove provenance，并在删除 groove Faces 后把 Boundary components 分类为 regular/cyclic/end-cap/junction。
3. 第一版复杂 filler 把超大非平面 Boundary loops 投影到 best-fit plane，尝试 CDT，失败后退到 centroid fan。主测试文件产生 17498 个跨模型坏面；拓扑计数仍为零，属于严重假阳性。
4. 为消除坏面，复杂 regions 改为保留 tracked Boolean groove surface。结果为 67026 个局部 groove Faces，topology clean，但几何语义只是圆管 Difference 槽，并非 Chamfer。
5. 用户截图进一步确认：SDF/Boolean 边界顶点极多且不规则，开放 Feature 的 capsule 圆端会留下半圆切口，junction 处只得到融合槽面，不能恢复结构化 chamfer strips/ports。

## 3. 根因

### 3.1 构造语义错误

Chamfer 应从原 Sharp Feature 两侧 Surface 上得到成对 rails，删除原 corner，并在 rails 之间生成受 Radius/Profile 控制的过渡面。圆管或 SDF tube Difference 的自然输出是凹槽。即使 Boolean 完全正确，它也没有自动变成 Chamfer。

### 3.2 SDF 丢失结构信息

`Mesh to Curve → Points to SDF Grid → Grid to Mesh` 能生成稳定体积，但体素重建会丢失 FeatureGraph、左右 Surface ownership、strip 横向参数与 junction ports。提高分辨率只会增加点数，不能恢复这些语义。

### 3.3 从全局 Boundary loop 反推局部 Chamfer 不可行

主测试文件的 4 个 `END_CAP` 与 13 个 `JUNCTION` 已合并成超大 loops。一个 loop 可能围绕多个相隔很远的 Feature branches。CDT/fan 只知道封洞，不知道哪些 rail 应配对、在哪 setback、哪些 profiles 应直通。

### 3.4 开放端圆帽是确定行为

SDF tube 的开放端天然是 capsule/sphere cap。沿 tangent 延长只能处理真正离开 source 的 terminal；不能解决 Surface 中途停止、薄壁、孔/柱邻近或多 branch junction。

### 3.5 验收指标再次选错

`boundary/non-manifold/zero-area = 0` 只能证明拓扑闭合，不能证明结果是 Chamfer。64/64 回归通过仍接受 67026 个槽面，说明测试验证了实现内部合同，没有验证产品几何语义。

## 4. 哪些资产仍可复用

- Sharp FeatureGraph、Surface Patch pair、degree-4 strand pairing。
- GN 参数/Preview 状态机、source fingerprint、失败不破坏 source 的生命周期代码。
- tracked Boolean provenance 与诊断，可继续作为 cutter/Boolean 调试工具。
- BoundaryGraph instrumentation 与 fail-closed 框架。
- 用户两个真实 `.blend`、Blender 5.1.2 命令行入口和现有 probe 工具。

不可复用为正式 Finalize 的部分：

- SDF cutter 生成的 Boolean surface；
- `_triangulate_loop` / `_centroid_fan_fill` 作为复杂 Chamfer filler；
- `TRACKED_BOOLEAN_SURFACE` 作为输出策略；
- 仅基于 topology clean 的成功判定。

## 5. 恢复与防复发

1. 正式路线必须先产出 `FeatureBranch → rail_left/rail_right → strip → setback port`，再允许 junction patch。
2. Preview 与 Finalize 必须共享同一结构化 rails/ports/profile 数据，不能 Preview 挖槽、Finalize 再从槽边猜结构。
3. 用户主文件必须检查局部语义：生成 Face 到 owner Feature 的最大距离、横向 span、超长边、跨无关 Surface Patch、端帽/凹槽残留，并保留固定近景 artifact。
4. 任一复杂 junction 未支持时 fail-closed，保留 Preview 与诊断；不得用通用 Fill 或保留 Boolean 槽伪装成功。
5. 本项目后续统一使用本机 Blender 5.1.2 验证，不再把 Blender 5.0 作为本轮阻塞项或反复向用户确认。

## 6. 当前状态

当前 SDF Finalize 路线判定为 Stop。下一步按 `docs/plan/2026-07-19-feature-chamfer-structured-curve-pipe-handoff.md` 做 Curve Pipe/结构化 rail spike；在 spike 的 Go 条件通过前，不继续扩展复杂 Patch。
