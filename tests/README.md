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
- Feature Chamfer Tricky-b 标准 180° open U 形由两个同步局部转折拆成三个原生 Bridge 任务回归
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
- 历史 PATCHED 后 dissolve、chamfer FACE attribute 与法线传递 smoke（非当前 Direct Bridge FINALIZE）
- tessellated curved chain 不被固定角度切碎的 grouping 回归
- surface patch pair / degree junction 拆分真实 corner 的 grouping 回归
- Feature Chamfer GN 发布资产 exact/version import、Preview modifier 幂等与 source fingerprint 回归
- Feature Chamfer GN 正式 Preview 保留受控 Boolean Pro 主链并禁止原生 Mesh Boolean 回归
- Feature Chamfer GN 90° miter 连续、极锐角断开后两侧不能从网络另一端重新归入同一 Curve、degree-3/4 junction 保持确定性连续配对的回归
- Feature Chamfer GN Task 2.1：完整 Sharp cube 从目标 Operator 分解为四条共面 `]`/`U` strands，并验证正交旋转变体保持共面 bracket 合同
- Feature Chamfer GN Task 2.2A：正式 Operator 的 smooth degree-2/cyclic chain 不受 Surface Patch/convexity metadata 波动切断；acute miter 仍 fail-closed
- Feature Chamfer GN Task 2.2B：junction 候选以 source-solid endpoint containment 处理等价 U 朝向，优先把圆形端盖埋入 attachment body，且移除固定四 strand 偏好
- Feature Chamfer GN Task 2.2C：正式 Preview 使用 resolution=4 四边 profile，Radius 直接驱动主轴尺寸，保持 Even-Thickness、Boolean Pro 与 closed-manifold cutter
- Feature Chamfer GN 参数 socket 更新、Curve Pipe cutter closed-manifold smoke test
- Feature Chamfer GN topology/live 参数 stale 与无 Sharp 时 Cancel 生命周期回归
- Feature Chamfer GN PREVIEW/FINALIZE shared immutable ChamferPlan、JunctionPort、cyclic metadata、Boundary binding 与 retry shadow contract 回归
- Feature Chamfer Phase 3 public BoundaryGraph open/cyclic/Y/T/X maximal degree-2 decomposition、dirty-index identity 与重复 Edge fail-closed 回归
- Feature Chamfer Phase 3 cyclic-only authoritative Boolean Boundary Face provenance、plan owner/rail mapping；open JunctionPort provenance、incomplete/multi-owner 均 fail-closed
- Feature Chamfer Phase 3 open strand 的 attribute-only start/end `JunctionPort` anchor binding；cyclic Boolean Rail 可 PASS，unknown/wrong/missing/duplicate token 均 fail-closed
- Feature Chamfer Phase 3 production Even-Thickness Pipe → joined cutter 的 plan-local open endpoint FACE token producer smoke
- Feature Chamfer Phase 3 degree-3 相交 Pipe 的 component/token/Patch one-hot Exact Boolean provenance；共享 seam 暂以结构化 `boundary_binding_incomplete` fail-closed
- Feature Chamfer Phase 3 Exact Boolean cutter component/present 与 source patch/present Face attribute propagation smoke（非 runtime integration）
- Feature Chamfer GN endpoint/junction extension、Python tracked Boolean provenance 与 Boundary region classification
- Feature Chamfer GN 历史 complex-region 旧后端 fail-closed 回归（非当前正式 runtime）
- Feature Chamfer batched Phase A：正式 Preview 持久化的 `GN_PREVIEW_PIPE_V1` 必须与实际 owned Curve 的 spline/cyclic 几何一致；测试禁用二次 `_build_preview_feature_graph`，证明 backend 只消费冻结合同
- Feature Chamfer batched Phase B：产品矩阵必须执行真实正序/逆序 Cut probe，要求几何 signature 相等、batch 数一致，且 signature 不得复用 graph/pipe metadata fingerprint 冒充几何证据
- Feature Chamfer 历史 Phase C 回归：旧 setback、DP correspondence、pre-Boolean pairing、normalization 与 exactly-once 合同仅防止旧代码静默回归，不代表当前产品路线或 Bridge 前置门槛
- Feature Chamfer 当前 Phase C 合同：没有交叉的普通 Pipe 直接 Bridge 两侧完整 Loop；遇到 Pipe 交叉时，在 junction 两端切成连续槽段；已确认配对正确但包含多个显著空间转折的长 open 槽段，可继续按两侧共同大转折同步切成连续子段；每段仍使用原生 Bridge，最后 Fill 剩余交叉孔洞
- 槽段两侧 Vertex/Edge 数量可不同，不要求逐边/逐点对应；只在槽段归属不明、跨 junction 混入其他槽、Bridge/Fill 实际失败或最终结果破坏槽外模型时停止，中间重合、零面积、degree、branch、cycle 与 canonicalization 不单独阻止 Bridge
- 旧 Feature Chamfer REGULAR_PATCHED 经统一 Patch Module legacy Adapter dispatch 回归

> 当前正式 Preview 输入只读取显式 `sharp_edge` attribute，不读取 Edit Mode 选区，不回退 Seam/angle select，也不调用 Curve bevel、Mesh bevel 或 Bevel modifier。

Feature Chamfer 历史 batched/Adapter Phase A/B 证据矩阵（仅诊断，不决定当前 Stop/Go）：

```bash
python tools/run_feature_chamfer_batched_matrix.py --repetitions 3
```

该历史 evidence runner 会为每次 full gate 创建唯一 artifact 目录，校验旧
Phase A/B/C、Preview/source/Adapter 与 debug 清理，并写入证据 manifest。
它不代表当前 Direct Bridge 产品门禁；host-side fake-green 合同可独立运行：

```bash
python3 -m unittest tests.test_feature_chamfer_evidence_runner
```

结果：`tests/artifacts/feature_chamfer_batched_matrix/results.json`。开发诊断可用重复 `--case <case_id>` 缩小运行范围；第一阶段 Stop/Go 以 `simple`、`tricky_b`、`mixed` 的 10 cells × 3 repetitions 为准，完整 14 cells 留作第二阶段最终门槛。
> `hst.feature_chamfer_gn PREVIEW` 已改为 Python FeatureGraph/CutterStrands → owned Curve → Even-Thickness Curve Pipe → 受控 Boolean Pro Preview。Cancel 与 redo 负责清理 owned Curve/wrapper。正式 FINALIZE 已接入 evaluated Preview 的 Boundary Edges → 槽段 Bridge → junction Fill；失败必须 fail-closed：source 不变、无坏的最终 Mesh。Bridge、Fill 或最终几何检查能够给出真实问题边界时，同时保留 Preview 并显示红色诊断，供用户显式减小 Radius 后重试；较早的 Preview/身份合同失败只保留已有现场和明确错误提示，不得伪造位置。
> 历史 Object Boolean、槽面删除、rail pairing 与 canonicalization 路线仅保留回归证据，不是当前正式 Finalize runtime，也不得作为 Bridge 前置门槛。
> 当前 Phase C 方向直接消费 Boolean Pro Boundary Edges。没有交叉且形态单一的 Pipe 以两条完整 Loop 一次 Bridge；在 junction 处按 Pipe owner 变化切成“交叉点之间的连续槽段”；已锁定配对但包含多个显著空间转折的长 open 槽段，允许按双方共同大转折继续同步切段。每段仍使用原生 Bridge，最后 Fill Bridge 后剩余的交叉孔洞。不得按距离重排边、使用 fixture 身份、自定义逐点对应、重采样或局部重建；两侧数量可以不同。越宽结果的门禁试验因会拦住 5/8 个对照场景而未接入正式实现。
> 法线问题按用户决定暂缓；正式 FINALIZE 不执行法线恢复，也不接入 Set from Faces、全对象 Data Transfer、试验性烘焙或 Corner 重写。
> Bridge/Fill 后尚未恢复 custom normals 的黑色三角只作为 shading 诊断，不作为孔洞失败。本阶段固定近景只用于检查 Mesh 轮廓、线框和补面位置，不作为法线验收；拓扑验收仍独立要求所有孔洞封闭、无开放边与多面共边。
> 不得使用渲染图的极暗像素计数、黑色连通块或其他颜色阈值推断孔洞；这些只反映图像明暗，不能替代 Mesh 边界、non-manifold 与线框拓扑证据。
> 2026-07-28 全部正式 Bridge 输入经 `1a/1b ...` 人工复核后，Mixed `26a/26b` 与 Tricky-b `32a/32b` 都证明：已配对正确的 open U 形长链若整组交给原生 Bridge，可能在转角处产生扭曲。共同转折分段必须逐处独立生效，不设置累计 360° 或至少四处转折门槛；cyclic Loop 保持完整闭环。两组现由同一正式几何规则命中，禁止 fixture 特判、逐点对应或重采样。新证据为 `/private/tmp/hst-general-turn-split-required10-final-20260728/results.json`（10 cells × 3）、`/private/tmp/hst-general-turn-split-tricky-safe-final-20260728/results.json`（延期 4 cells × 3）与 `/private/tmp/hst-general-turn-split-full-regression-final-20260728/results.json`（147 / 147）；独立审计已通过，状态为 `VERIFIED`，用户真实 UI 复核前仍非 `ACCEPTED`，法线继续暂缓。

## Experimental Pipe Chamfer API Probe

- Blender 5.1.2 实测 artifact：`tests/artifacts/experimental_pipe_chamfer_probe.json`
- Pipe 由显式 Mesh sweep 生成 closed manifold cutter；当前实现不会调用 Blender Curve bevel、Mesh bevel 或 Bevel modifier。
- Boolean `solver=EXACT`、`operand_type=COLLECTION` 与 `material_mode=TRANSFER` 可用；marker material 能传入 cutter-derived Faces。
- 删除 marker Faces 后可由 marker/non-marker 邻接边稳定得到 trim boundaries。
- 本机未安装 `ctx7` CLI，因此本轮 Blender API 结论以真实 background probe 为证据。

## Feature Chamfer GN Probe（历史 SDF 路线，已废弃）

- Blender 5.1.2 实测 artifact：`tests/artifacts/feature_chamfer_gn_probe.json`
- 该 artifact 仅记录 2026-07-19 的历史 probe，不代表当前发布/runtime 路线。
- `Points to SDF Grid → Grid to Mesh` 已确认废弃：体素重建会丢失 Feature/Patch ownership、成对 rails 与 junction ports，不得用于正式 Preview/Finalize。
- 失败复盘：`docs/postmortem/2026-07-19-feature-chamfer-sdf-patch-failure.md`。
- 该历史路线随后继续演进；当前 Phase C 方向以“无交叉 Pipe 完整 Loop Bridge；junction 处分段 Bridge 后 Fill 交叉孔洞”的计划为准。

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
python .\tools\run_feature_chamfer_matrix.py --repetitions 3
```

Blender 未加入 PATH 时：

```powershell
python .\tools\run_feature_chamfer_matrix.py --blender "<path-to-blender>" --repetitions 3
```

- 固定运行 `tests/fixtures/` 中 7 个对象 × radius `{0.01, 0.03}`。
- 每个 cell 从目标 `hst.feature_chamfer_gn` PREVIEW→FINALIZE 开始，并重复 3 次验证 shared plan determinism。
- 分类至少区分 `PRODUCT_SUCCESS`、`RADIUS_LIMIT_DIAGNOSTIC`、`PRODUCT_SUCCESS_WITH_RADIUS_RETRY`、`EXPECTED_UNSUPPORTED`、`REGRESSION_FAILURE`、`SAFETY_PASS`。普通 fail-closed 不计产品成功。
- 每个请求 Radius 都保留独立结果；不得把失败 Radius 改写为成功。若正式 Operator 在复杂孔洞位置安全失败、Preview 与红色问题边界可见，且同一对象在明确更小 Radius 独立得到 `PRODUCT_SUCCESS`，该目标场景可汇总为 `PRODUCT_SUCCESS_WITH_RADIUS_RETRY`。
- 产品矩阵默认另外运行 Radius `0.005` 与 `0.015` 作为独立 retry 证据；它们不覆盖或改写固定的 `0.01 / 0.03` 结果。
- 第一阶段门槛只统计 `simple`、`tricky_b`、`mixed` 的 10 个目标场景，要求 10/10 × 3 repetitions 为直接成功或满足上述严格条件的降低半径后成功；`tricky` 4 cells 单独记录安全结果并延后。
- 汇总：`tests/artifacts/feature_chamfer_matrix/results.json`。
- 每 cell artifact：`tests/artifacts/feature_chamfer_matrix/<case>/`。
- 旧第一阶段自动证据：`tests/artifacts/feature_chamfer_phase1_required_global_curve_final_no_normals/results.json`、`/private/tmp/hst-required10x3-final7-20260727/results.json`、`/private/tmp/hst-required10-strip-final-20260728/results.json` 与 `/private/tmp/hst-turn-split-final-required10-20260728/results.json`；前三份分别被真实 UI 或禁用的逐点对应路线推翻，最后一份使用过拟合 Mixed 的累计转角门槛，也不能继续声明通过。通用逐处规则的新证据为 `/private/tmp/hst-general-turn-split-required10-final-20260728/results.json`：10 cells × 3 全部稳定 `PRODUCT_SUCCESS`，显式验证 Mixed 六切点/七 job 与 Tricky-b 两切点/三 job。延期安全证据为 `/private/tmp/hst-general-turn-split-tricky-safe-final-20260728/results.json`，完整回归为 `/private/tmp/hst-general-turn-split-full-regression-final-20260728/results.json`（147 / 147）。法线暂缓，矩阵中的法线字段只用于确认错误方案未接入，不是产品成功门槛。

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
