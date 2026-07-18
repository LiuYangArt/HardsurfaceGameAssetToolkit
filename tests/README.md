# Blender 回归测试

## 目的

用于在 Blender 升级后快速发现插件的 breaking change，避免只能靠手动逐个点功能。

## 当前覆盖

- addon 注册 smoke test（包含全部 `hst.*` operator 注册检查）
- `_TransferProxy` collection 复用回归
- bake collection low/high 标记 smoke test
- object vertex color 设置 / 从 active 复制 smoke test
- collision 设置 / extract UCX smoke test
- bevel / weighted normal / triangulate modifier smoke test
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
- two-Pipe junction 在 Region split 未稳定时 fail-closed 的回归
- Cutter Collection Exact Difference 与 cutter Face provenance smoke test
- tessellated curved chain 不被固定角度切碎的 grouping 回归
- surface patch pair / degree junction 拆分真实 corner 的 grouping 回归

> 当前实验实现只读取显式 `sharp_edge` attribute，不读取 Edit Mode 选区，不回退 Seam/angle select，也不调用 Curve bevel、Mesh bevel 或 Bevel modifier。
> 多 Pipe 不再先生成 Union Mesh；每根 Pipe 保持独立，并通过 Cutter Collection 一次执行 Exact Difference。`CUTTER_UNION` 枚举为兼容旧 redo 数据保留，UI 显示名已改为 Cutter Set。
> `PATCHED` 仅在 BoundaryGraph 可稳定分类时完成；当前 cube closed-loop probe 会返回 `ambiguous_boundary`，不会用旧 Bevel 结果伪装成功。two-pipe junction 的 Regular/Junction patch 仍是待继续验证的 Stop/Go 项。

## Experimental Pipe Chamfer API Probe

- Blender 5.1.2 实测 artifact：`tests/artifacts/experimental_pipe_chamfer_probe.json`
- Pipe 由显式 Mesh sweep 生成 closed manifold cutter；当前实现不会调用 Blender Curve bevel、Mesh bevel 或 Bevel modifier。
- Boolean `solver=EXACT`、`operand_type=COLLECTION` 与 `material_mode=TRANSFER` 可用；marker material 能传入 cutter-derived Faces。
- 删除 marker Faces 后可由 marker/non-marker 邻接边稳定得到 trim boundaries。
- 本机未安装 `ctx7` CLI，因此本轮 Blender API 结论以真实 background probe 为证据。

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
