# Blender 回归测试

## 目的

用于在 Blender 升级后快速发现插件的 breaking change，避免只能靠手动逐个点功能。

## 当前覆盖

- addon 注册 smoke test（包含全部 `hst.*` operator 注册检查）
- 遗留 `Scene.hst_params` PointerProperty 安全替换的 UI 崩溃回归
- `_TransferProxy` collection 复用回归
- bake collection low/high 标记 smoke test
- object vertex color 设置 / 从 active 复制 smoke test
- collision 设置 / extract UCX smoke test
- bevel / weighted normal / triangulate modifier smoke test
- Feature Chamfer tricky_b / Extruded.002 真实 fixture PATCHED 拓扑回归
- Feature Chamfer degree-4 Feature strand pairing 回归
- Feature Chamfer degree-3 maximum-weight strand matching 回归
- Feature Chamfer Even-Thickness Curve Pipe asset exact/version/fingerprint 与 backend smoke test
- Feature Chamfer Boolean/source-surface rail A/B 统一 RailPairRecord contract smoke test
- Feature Chamfer open Rail 单调、scale-invariant correspondence / terminal constraint regression
- Feature Chamfer mixed fixture 目标 Operator PREVIEW→FINALIZE terminal topology 回归
- Feature Chamfer 失败后保留 Adjust Last Operation 参数面板回归
- decal project smoke test
- quickweight smoke test
- AO bake operator headless smoke test
- wearmask AO proxy 拓扑回归（确保 proxy 捕获 bevel 后几何，并被 Data Transfer 正确引用）
- asset origin / snap transform / reset to origin smoke test
- prop / decal collection 标记 smoke test
- isolate collection 空选择回归（active collection 不应被当作显式选择）
- static mesh FBX export smoke test
- current Scene only FBX export regression test
- CAT MeshGroup instance FBX export regression test
- bake collection FBX export smoke test
- Marmoset Toolbag 5 bake scene bridge pairing / loader generation smoke test
- static mesh GLB export smoke test
- rename bones smoke test
- cleanup UE SKM smoke test
- experimental Pipe Chamfer 的 Object-only Sharp FeatureGraph smoke test
- 多条独立 manifold Pipe 生成与“禁止 Blender Bevel”回归
- two-Pipe junction 的 redo-compatible 诊断与 source 不变回归
- 未 Apply 的单 Object / 多 Object Cutter Boolean Preview smoke test
- Boolean Apply 后通过 FACE provenance 只删除槽面、保留原面回归
- 清理上一轮 Boolean Preview 后首次 OPEN_BOUNDARY 即成功的 dependency-graph 同步回归
- Pipe 两侧边链执行 Bridge Edge Loops、剩余洞口执行 Fill 的 watertight smoke test
- PATCHED 后 dissolve 为 chamfer n-gon、FACE attribute 标记与原 Mesh custom normal transfer smoke test
- tessellated curved chain 不被固定角度切碎的 grouping 回归
- surface patch pair / degree junction 拆分真实 corner 的 grouping 回归
- Feature Chamfer GN 发布资产 exact/version import、Preview modifier 幂等与 source fingerprint 回归
- Feature Chamfer GN 正式 Preview 保留受控 Boolean Pro 主链并禁止原生 Mesh Boolean 回归
- Feature Chamfer GN 90° miter 连续、极锐角断开、三根正交 branch 与 degree-3/4 deterministic strand pairing 回归
- Feature Chamfer GN Task 2.1：完整 Sharp cube 从目标 Operator 分解为四条共面 `]`/`U` strands，并验证正交旋转变体保持共面 bracket 合同
- Feature Chamfer GN Task 2.2A：正式 Operator 的 smooth degree-2/cyclic chain 不受 Surface Patch/convexity metadata 波动切断；acute miter 仍 fail-closed
- Feature Chamfer GN Task 2.2B：junction 候选以 source-solid endpoint containment 处理等价 U 朝向，优先把圆形端盖埋入 attachment body，且移除固定四 strand 偏好
- Feature Chamfer GN Task 2.2C：正式 Preview 使用 resolution=4 四边 profile，Radius 直接驱动主轴尺寸，保持 Even-Thickness、Boolean Pro 与 closed-manifold cutter
- Feature Chamfer GN 参数 socket 更新、Curve Pipe cutter closed-manifold smoke test
- Feature Chamfer GN topology/live 参数 stale 与无 Sharp 时 Cancel 生命周期回归
- Feature Chamfer GN endpoint/junction extension、Python tracked Boolean provenance 与 Boundary region classification
- Feature Chamfer GN complex region fail-closed（旧 Finalize 验收已隔离，等待后续阶段重新接入）
- 旧 Feature Chamfer REGULAR_PATCHED 经统一 Patch Module legacy Adapter dispatch 回归

> 当前实验实现只读取显式 `sharp_edge` attribute，不读取 Edit Mode 选区，不回退 Seam/angle select，也不调用 Curve bevel、Mesh bevel 或 Bevel modifier。
> `hst.feature_chamfer_gn PREVIEW` 已改为 Python FeatureGraph/CutterStrands → owned Curve → Even-Thickness Curve Pipe → 受控 Boolean Pro Preview。Cancel 与 redo 负责清理 owned Curve/wrapper。旧 Finalize 不再作为当前阶段验收；复杂 region 保持 fail-closed。
> 多 Pipe 不再先生成 Union Mesh；每根 Pipe 保持独立，并通过 Cutter Collection 执行 Exact Difference。默认 `Boolean Preview` 保留未 Apply 的 Boolean Modifier，便于手动调整 solver 参数；只有检测到近似垂直 terminal face 的 Pipe 端点才延长一个 radius，surface continuation 与 ambiguous 端点不延长。`CUTTER_UNION` 枚举为兼容旧 redo 数据保留，UI 显示名已改为 Cutter Set。
> 进入 `OPEN_BOUNDARY` 及后续阶段时才 Apply Boolean；Apply 前给原 Faces 写入 `hst_pipe_original_face`，Apply 后只删除未继承该标记的槽面，避免 BVH 距离误删原模型大面。
> `PATCHED` 按 Pipe ID 与 source Surface Patch ID 配对两侧 boundary rail，先执行 Bridge Edge Loops，再对剩余闭合洞口执行 Fill；无法形成闭合洞时 fail-closed，不会用旧 Bevel 结果伪装成功。
> PATCHED 后会 dissolve chamfer 内部共面 Edge，写入 FACE Boolean attribute `hst_pipe_chamfer`，并用 `POLYINTERP_LNORPROJ` Data Transfer 从隐藏的原 Mesh 传递 custom normals。

## Experimental Pipe Chamfer API Probe

- Blender 5.1.2 实测 artifact：`tests/artifacts/experimental_pipe_chamfer_probe.json`
- Pipe 由显式 Mesh sweep 生成 closed manifold cutter；当前实现不会调用 Blender Curve bevel、Mesh bevel 或 Bevel modifier。
- Boolean `solver=EXACT`、`operand_type=COLLECTION` 与 `material_mode=TRANSFER` 可用；marker material 能传入 cutter-derived Faces。
- 删除 marker Faces 后可由 marker/non-marker 邻接边稳定得到 trim boundaries。
- 本机未安装 `ctx7` CLI，因此本轮 Blender API 结论以真实 background probe 为证据。

## Feature Chamfer GN Probe

- Blender 5.1.2 实测 artifact：`tests/artifacts/feature_chamfer_gn_probe.json`
- 发布 cutter 使用原生 `Points to SDF Grid → Grid to Mesh`，fixture 上 closed manifold。
- 发布资产直接迁移 fixture 的 `pipecut + Boolean Pro + nested Node Groups`，不再替换成原生 Mesh Boolean。
- `Boolean Pro.New Faces / Slice Faces` 在当前 fixture 配置为空；`Boundary Edges` 可保存但主要是 loose Edge，尚不能安全驱动 Patch，Finalize 继续 fail-closed。
- 统一 probe：设置 `HST_ADDON_ROOT` 后用 Blender background 执行 `tools/probe_feature_chamfer_gn.py`。
- Boolean Pro 输出专项 probe：`tools/probe_boolean_pro_provenance.py`。

## Feature Chamfer Structured Curve Phase 1 Prototype

> Status: PROTOTYPE only. This does not prove that hst.feature_chamfer_gn PREVIEW uses the new Curve backend.

- 入口：`tools/probe_feature_chamfer_curve_phase1.py`。
- 结果：`tests/artifacts/feature_chamfer_curve_phase1_probe.json`。
- 固定读取 `pipe-chamfer-mixed.blend::Extruded.002`，验证 Python strand matching、
  受控 Even-Thickness GN backend、每 strand manifold guard 与 source fingerprint。
- Even-Thickness 与 `Poly-Curve Info` 已复制到 `preset_files/Presets.blend`，
  由 exact name/version/fingerprint guard 幂等导入。

## Feature Chamfer Rail Phase 2 Stop-State Probe

> Status: STOP. The real-file rail guard is 17/51; this does not unlock Strip/Junction implementation.

- 入口：`tools/probe_feature_chamfer_rail_phase2.py`。
- 结果：`tests/artifacts/feature_chamfer_rail_phase2_probe.json`。
- 同时输出 `BOOLEAN_INTERSECTION_ORACLE` 与 `SOURCE_SURFACE_OFFSET` 的
  `RailPairRecord`，记录 coverage、unresolved group IDs 和 width error。
- Phase 2 只有 coverage=100%、ambiguous=0 且 width error 通过 radius 容差后才能 Go。

## Feature Chamfer GN Finalize Probe（历史 artifact，当前不作为验收）

- 入口：`tools/probe_feature_chamfer_finalize.py`。
- 结果：`tests/artifacts/feature_chamfer_gn_finalize_fixture_probe.json`。
- 可打开的最终 Mesh：`tests/artifacts/feature_chamfer_gn_finalize_fixture.blend`。
- Finalize 渲染预览：`tests/artifacts/feature_chamfer_gn_finalize_fixture.png`。
- 覆盖 cutter extension、tracked Boolean、Boundary region、junction/end-cap filler 与 final manifold 风险。

## 运行方式

### 自动查找 Blender

```powershell
python .\tools\run_blender_tests.py
```

### 指定 Blender 路径

```powershell
python .\tools\run_blender_tests.py --blender "C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe"
```

或先设置环境变量：

```powershell
$env:BLENDER_EXE = "C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe"
python .\tools\run_blender_tests.py
```

## 输出

- 终端打印每个测试用例的通过/失败状态
- 详细结果写入：`tests/artifacts/results.json`

## Feature Chamfer 产品矩阵

通用化 roadmap 使用独立矩阵 runner，结果语义与完整回归的 pass/fail 分开：

```powershell
python .\tools\run_feature_chamfer_matrix.py --repetitions 2
```

Blender 未加入 PATH 时：

```powershell
python .\tools\run_feature_chamfer_matrix.py --blender "<path-to-blender>" --repetitions 2
```

- 固定运行 `tests/fixtures/` 中 7 个对象 × radius `{0.01, 0.03}`。
- 每个 cell 从目标 `hst.feature_chamfer_gn` PREVIEW→FINALIZE 开始。
- 分类为 `PRODUCT_SUCCESS`、`EXPECTED_UNSUPPORTED`、`REGRESSION_FAILURE`、`SAFETY_PASS`；fail-closed 不计产品成功。
- 汇总：`tests/artifacts/feature_chamfer_matrix/results.json`。
- 每 cell artifact：`tests/artifacts/feature_chamfer_matrix/<case>/`。

## 设计原则

- 优先测高风险回归点，而不是追求所有功能一次性全覆盖
- 尽量断言中间状态：collection、proxy、modifier、拓扑、attribute
- 失败时明确告诉你是哪类功能坏掉了

## 后续建议扩展

后面可以继续加：

- 关键 operator 注册 smoke 列表
- bake collection / export / decal / rigging smoke tests
- headless 导出产物断言
- GitHub Actions 中的 Blender smoke job
## 规范

- 测试新增/维护规范：`F:/CodeProjects/BlenderAddons/HardsurfaceGameAssetToolkit/tests/TESTING_POLICY.md`
- 以后新功能、修 bug、Blender 升级兼容，默认按该规范补 smoke/regression 测试。

## Experimental structured artifacts (not accepted)

- `tests/artifacts/feature_chamfer_rail_phase2_probe.json` and the companion `.blend` are diagnostic prototypes only.
- They do not come from the target `hst.feature_chamfer_gn PREVIEW` runtime path.
- Strip/Junction PASS statistics must not be used as Operator or product acceptance.
- See `docs/postmortem/2026-07-20-feature-chamfer-preview-integration-drift.md`.
