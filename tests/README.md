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
- Feature Chamfer 失败后保留 Adjust Last Operation 参数面板回归
- decal project smoke test
- quickweight smoke test
- AO bake operator headless smoke test
- wearmask AO proxy 拓扑回归（确保 proxy 捕获 bevel 后几何，并被 Data Transfer 正确引用）
- asset origin / snap transform / reset to origin smoke test
- Safe Ngon CAD pipeline 的 topology repair、UV/Material/Attribute 保留、重复运行与临时资源清理回归
- Safe Ngon Clean 前 custom normals 恢复与有效性回归
- Fix CAD Obj → Prepare CAD Mesh 的 Multi-user 隔离与 topology 幂等回归
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
- Feature Chamfer GN 参数 socket 更新、SDF cutter closed-manifold smoke test
- Feature Chamfer GN topology/live 参数 stale 与无 Sharp 时 Cancel 生命周期回归
- Feature Chamfer GN endpoint/junction extension、Python tracked Boolean provenance 与 Boundary region classification
- Feature Chamfer GN terminal、junction、cyclic、end-cap Patch 与真实 fixture closed-manifold Finalize
- 旧 Feature Chamfer REGULAR_PATCHED 经统一 Patch Module legacy Adapter dispatch 回归

> 当前实验实现只读取显式 `sharp_edge` attribute，不读取 Edit Mode 选区，不回退 Seam/angle select，也不调用 Curve bevel、Mesh bevel 或 Bevel modifier。
> 新的 `hst.feature_chamfer_gn` 已完成 Preview / Finalize / Cancel Preview；Finalize 从同一 GN modifier 提取 extended SDF cutter，执行 Python tracked Boolean、显式 Boundary region Patch，并生成独立 output。任何 stale、provenance、region 或 final topology gate 失败都会保留 source/Preview 并 fail-closed。
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

## Feature Chamfer GN Finalize Probe

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
