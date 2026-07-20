# Feature Chamfer GN Preview 集成偏航复盘

> 日期：2026-07-20  
> 影响入口：`hst.feature_chamfer_gn` / UI `Feature Chamfer GN Preview`  
> 结论：实现完成了部分 FeatureGraph、Curve Pipe 和 Rail spike，却没有把新 Curve backend 接入目标 Preview Operator；随后又越过未通过的 Phase 2 门槛实现 Strip/Junction/Finalize 原型，并错误宣称计划完成。

## 1. 用户可见症状

用户点击 `Feature Chamfer GN Preview` 后，画面与改动前一致：

- Preview 仍使用旧 `GN_HSTFeatureChamferSDFPreview` / SDF Boolean 链；
- 新的 Python FeatureGraph、CutterStrands 与 Even-Thickness Pipe 没有进入该 Preview；
- 新 Strip/Junction 只存在于离线 artifact，运行时会创建后删除，用户不可见；
- 唯一正式入口变化发生在第二次点击 Finalize：隐藏 preflight 可能返回 `CANCELLED`。

因此“测试和 probe 有大量新结果”没有转化成用户请求的可见 Operator 行为。

## 2. 影响范围

### 可复用

- Phase 0 complex Patch fail-closed；
- Even-Thickness 与 `Poly-Curve Info` 受控资产、fingerprint 和构建脚本；
- maximum-weight strand matching、逐 Edge Patch ownership、degree-3 regression；
- Python Curve Pipe backend 与 Phase 1 probe；
- Rail A/B spike 的诊断数据和失败样本。

### 必须撤回或隔离

- 正式 `hst.feature_chamfer_gn FINALIZE` 中的 structured preflight；
- `build_structured_feature_chamfer_artifacts`；
- 越阶段 StripPort/JunctionRecord/Junction Mesh 及其自证式 PASS 测试；
- junction center-fan/投影排序 filler；
- 文档中 Phase 3–6 已完成、已接入 Preview/Finalize 的表述。

### 尚未实现

- `hst.feature_chamfer_gn PREVIEW` 调用 Python FeatureGraph；
- Python CutterStrands 转为受生命周期管理的 Curve Object/Collection；
- Preview GN 消费该 Curve 数据并调用 Even-Thickness；
- 新 Preview 的用户可见对照与 Operator acceptance test；
- Preview/Finalize 消费同一 records。

## 3. 时间线

1. 按计划实现 Phase 0 fail-closed。
2. 在实验 Pipe 模块实现任意 degree matching，并把 Even-Thickness 资产复制到 `Presets.blend`。
3. 用真实主文件的 headless probe 验证 Pipe artifacts，但没有先确认目标 Preview Operator 的实际调用链。
4. 进入 Rail A/B spike；source-surface 输出 51/51 records，但严格 geometry guard 仅通过 17/51。
5. 违反 Phase 2 Stop 条件，继续实现 strips、ports 和 junction mesh；用 topology/自定义 guard 判为 PASS。
6. 把 structured preflight 插入正式 Finalize，但 Preview 仍走旧节点组，且 Finalize 仍消费旧 Patch pipeline。
7. 以 68/68 tests、JSON 和离线 `.blend` artifact 宣称计划实施完成。
8. 用户从真实 UI 点击目标 Operator，立即发现没有任何可见变化，暴露入口错位。

## 4. 根因

### 4.1 没有先锁定目标入口

计划讨论的对象是 `hst.feature_chamfer_gn`，但实现主力落在 `experimental_pipe_chamfer_utils.py` 与 `hst.experimental_pipe_chamfer` 的 backend。没有在开工前写下并验证：

```text
用户点击哪个按钮？
该按钮调用哪个 Operator？
Operator 的 PREVIEW 分支调用哪个函数/Node Group？
本阶段完成后用户第一眼应看到什么变化？
```

结果是底层算法有进展，产品入口没变化。

### 4.2 把“资产已复制”误当成“Preview 已使用”

`Presets.blend` 中出现 Even-Thickness Node Group，只证明资产存在。旧 Preview loader 仍校验并导入 SDF/Boolean Pro 主链；没有任何运行时连接把 Python Curves 输入新资产。

这是 interface verification 缺失：验证了 implementation 的局部存在，没有验证 caller 经过正确 seam 使用它。

### 4.3 违反 Stop/Go 阶段纪律

计划明确要求 Phase 2 任一 rail 不能稳定配对，就先修 rail，不进入 junction。真实结果只有 17/51 guard PASS，却继续写 Phase 3–6。

阶段名称被当作开发顺序建议，没有被当作硬约束；没有一份机器或人工 checklist 阻止后续代码进入正式入口。

### 4.4 自动测试验证了旁路，不是目标行为

新增测试大多直接调用底层 builder 或读取内部 stats：

- matching test 证明算法能配对；
- asset test 证明 Node Group 能导入；
- rail contract test 证明字段存在；
- junction guard test 证明自定义 guard 返回 PASS。

它们没有调用 `bpy.ops.hst.feature_chamfer_gn(action="PREVIEW")` 后验证：

- modifier 是否使用新 backend；
- Python Curve strands 是否存在并被 GN 消费；
- old SDF chain 是否不再作为默认 Preview；
- viewport geometry 是否发生预期变化。

这是典型的代理指标替代产品验收。

### 4.5 过度信任 headless artifact

离线 `.blend` 和 JSON 适合诊断，但它们可以绕开 UI 生命周期、Operator action dispatch、modifier ownership 和 Preview state。artifact 可打开不等于用户按钮已接入。

### 4.6 完成声明没有逐条对照计划

完成前虽然运行了完整回归，却没有逐条检查：

- Phase 1 的正式 Preview 是否使用新 Curve backend；
- Phase 2 是否达到 Go；
- Phase 3–5 是否满足数值与视觉门槛；
- Phase 6 是否真的接回 UI。

测试数量替代了规格追踪，导致严重假阳性完成声明。

### 4.7 审查发生得太晚

代码审查是在用户指出入口无变化后才进行。如果在 Phase 1 结束时做一次 spec review，`ensure_gn_feature_chamfer_preview()` 仍指向旧 SDF 的事实会立刻阻止后续工作。

## 5. 为什么现有保护没有拦住

- 回归 suite 偏重“不崩溃、topology clean、字段存在”，缺少目标 Operator 的可见 acceptance。
- 计划有 Stop/Go 文字，但没有阶段状态表和禁止进入下一阶段的审查动作。
- `verification-before-completion` 验证了命令结果，却没有先确认“这个命令验证的是不是用户请求的行为”。
- 真实主文件 probe 直接调用 backend，绕过 `hst.feature_chamfer_gn`。
- 文档实施结果由实现者自行追加，没有独立 spec audit。

## 6. 恢复措施

1. 撤回越阶段 Operator/Finalize、StripPort、Junction Mesh 与相关自证测试。
2. 保留 Phase 0、FeatureGraph、受控资产和 Curve Pipe probes。
3. 把当前状态恢复为 Phase 1B：正式 GN Preview 接入未开始。
4. 先实现唯一 Preview seam：Python Curve Object/Collection → Even-Thickness GN → Boolean Preview。
5. 新增从 `bpy.ops.hst.feature_chamfer_gn(action="PREVIEW")` 开始的 Operator acceptance test。
6. 保存目标按钮运行后的固定近景，而不是只保存 backend artifact。
7. Phase 1 经用户可见验证后，才继续 Phase 2；Phase 2 达到 100% 前禁止 junction。

恢复计划已写入：`docs/plan/2026-07-19-feature-chamfer-structured-curve-pipe-handoff.md` 第 9 节。

## 7. 长期预防措施

### 7.1 每个任务建立“入口契约”

在修改前必须写明：

```text
Target UI: Feature Chamfer GN Preview
Operator: hst.feature_chamfer_gn
Action: PREVIEW
Runtime path: invoke → execute → preview builder → modifier/node group
Visible outcome: Python grouped Curves drive Even-Thickness Boolean Preview
```

首次代码定位必须沿这条路径完成；后续实现不得迁移到旁路入口而不明确说明。

### 7.2 使用四层验收矩阵

| 层级 | 回答的问题 | 允许支持的声明 |
|---|---|---|
| Algorithm test | matching/rail 数学是否成立？ | 算法局部通过 |
| Backend probe | Curve/GN 是否能生成 geometry？ | backend 可行 |
| Operator acceptance | 用户按钮是否走新 backend？ | 功能已接入 |
| Visual/product acceptance | 结果是否真的是目标 Chamfer？ | 效果可用 |

禁止用低层绿色结果替代高层声明。

### 7.3 Stop/Go 变成硬门禁

每个阶段结束必须记录：

- 门槛逐项 PASS/FAIL；
- 证据路径；
- 当前允许修改的模块；
- 下一阶段是否解锁。

任一必需项 FAIL，后续阶段只能写设计文档，不能写实现或接正式入口。

### 7.4 “用户可见差异”是阶段必需证据

UI/几何任务每阶段至少提供一个由目标 Operator 产生的 artifact，并回答：

- 改动前后哪里不同；
- 为什么这个差异来自新路径；
- 如何证明不是旧 backend；
- 用户从哪个动作能复现。

如果回答是“用户看不出来”，则不能称为 Operator 阶段完成。

### 7.5 完成前做独立 spec audit

完成声明前必须由独立审查视角检查：

1. diff 是否修改了目标 runtime path；
2. 每个计划门槛是否有直接证据；
3. 是否有 scope creep 或越阶段实现；
4. 测试是否从产品入口开始；
5. 文档状态是否与代码一致。

这次审计发现的问题本应在 Phase 1 后就暴露。

### 7.6 明确使用 verification skill 的前置问题

在运行测试前，先问：

> 哪条命令或 artifact 能直接证明用户描述的动作已经改变？

如果答案只是底层函数或离线 probe，就只能声明 prototype，不得声明功能完成。

### 7.7 完成声明分级

统一使用以下状态：

- `PROTOTYPE`：底层算法或 backend 可运行；
- `INTEGRATED`：目标 Operator 已接入；
- `VERIFIED`：真实文件数值和近景通过；
- `ACCEPTED`：用户在真实 UI 验收通过。

不得从 `PROTOTYPE` 直接跳到“完成”。

## 8. 新增硬规则

针对后续 Feature Chamfer 工作，以下规则视为项目约束：

1. 目标入口固定为 `hst.feature_chamfer_gn`，除非用户明确改变范围。
2. Phase 1B 完成前，不再修改正式 Finalize。
3. Phase 2 100% guard 前，不实现 StripPort/JunctionSolver。
4. 禁止 junction center fan、通用 Fill 或保留 Boolean groove 作为 Chamfer 成功路径。
5. 每次阶段交付必须同时给出 Operator acceptance test 和目标按钮产生的近景 artifact。
6. 任何“完成”声明必须列出当前分级状态和未通过门槛。

## 9. 当前状态

当前状态为：

```text
Phase 0: VERIFIED
Phase 1A FeatureGraph/asset/backend: PROTOTYPE
Phase 1B GN Preview integration: NOT STARTED
Phase 2 rails: STOP (17/51 guarded)
Phase 3–6: NOT STARTED; current prototypes must be reverted/isolated
```

这次问题不是方向完全不可用，而是把可复用 prototype 错当成正式集成，并越过阶段门槛。恢复不需要从零开始，但必须先清理错误入口和声明，再从目标 Operator 的 Preview seam 重新推进。