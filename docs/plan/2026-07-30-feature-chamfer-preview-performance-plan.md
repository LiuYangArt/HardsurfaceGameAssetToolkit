# Feature Chamfer 一步式性能与架构评估

日期：2026-07-30  
状态：`CORRECTNESS VERIFIED / PERFORMANCE STOP / AWAITING USER ACCEPTANCE`
（2026-07-30 已恢复旧 Preview → Finalize 的几何等价；待用户检查批量 `.blend`）

失败复盘与后续强制门槛：[`2026-07-30-feature-chamfer-performance-rewrite-failure.md`](../postmortem/2026-07-30-feature-chamfer-performance-rewrite-failure.md)

> 纠正：此前的 `VERIFIED` 结论无效。现有门禁只证明输出闭合、无零面积等内部指标，
> 没有证明与旧正式结果的几何或视觉等价。用户在全部测试 `.blend` 中观察到重复面、
> 拉伸面和错误封口；修复并完成逐项旧/新对照前，不得恢复为 `VERIFIED`。

2026-07-30 恢复结论：正式一步入口改为在同一 Undo/Redo 事务内复用已验收的 Preview →
Finalize 几何链，并修复环状 Boundary 切点必须优先两侧同 station 的规则。正式 10-cell 输出的
规范化几何 fingerprint、Mesh 数量、Chamfer Face 数已逐项锁定为旧版基线；批量 `.blend` 已输出，
最终视觉验收只等待用户在 Blender 中检查。

## 1. 结论

现有 Geometry Nodes Preview → Python Finalize 两阶段架构不再作为目标产品路径。用户期望与
旧 Feature Chamfer 一致：执行一次就得到最终 Mesh；Radius、是否保留 Cutter 等选项继续放在
左下角 `Adjust Last Operation`，Redo 重新执行整个事务。

改用 Python 主导是正确方向，但不是把全部几何都手写为 Python 循环。推荐边界为：

- Python/BMesh 负责 FeatureGraph、ChamferPlan、Curve/Cutter 数据生成、Boundary 归属、
  Bridge/Fill 和事务生命周期；
- Blender 的 Manifold Mesh Boolean 继续负责布尔运算，并复刻受控 Boolean Pro 的
  Manifold 分支与输出合同；
- Geometry Nodes 不再承担运行时身份数据编码，不再创建逐 Point/Face/segment 的 nodes；
- 已验证的 Curve Pipe 资产可留作 Cutter 几何组件，或在证明等价后替换为直接 Mesh 生成；
- 最终产品只有一步和一个结果 Object，不保留 Preview/Finalize 状态机。

## 2. 已测基线

Blender 5.1.2、Mixed fixture、Radius 0.01：

| 当前正式路径阶段 | 耗时 |
|---|---:|
| FeatureGraph、Plan、Curve Object | 6.78 秒（优化前） |
| 动态 Geometry Nodes 数据编码 | 79.87 秒 |
| Cutter/Boolean Pro 强制求值 | 0.10 秒 |

动态 Geometry Nodes wrapper 达到 3863 nodes / 5747 links。source Face one-hot 约 53.6 秒，
Curve Point/segment one-hot 约 15.4 秒。因此最慢部分既不是 Curve Pipe 求值，也不是 Boolean，
而是 Python 通过 Blender RNA 逐个创建大量 nodes 和 links。

已经进入正式 runtime 的纯算法优化把 Mixed 的 Curve/Plan 五次中位数从 4.89 秒降到 0.493 秒：
FeatureGraph 约 0.453 秒，Plan 约 0.020 秒。说明这一段不是“Python 天生太慢”，热点来自重复扫描、
重复排序与重复构造；暂时没有 Rust 必要。

补充做的一步式 Python 对照错误地走了旧 Exact Modifier 路径；它不是目标产品基线，也不能用于
估算正式一步式路径的 Boolean 下限。该实验只保留一个有效结论：受控 Curve 资产生成 48 根
Cutter 用时 0.082 秒，直接 Python Mesh 用时 0.013 秒，Cutter 构建本身不是主瓶颈。随后用
Blender 5.1 的 Manifold Modifier 重测同一旧对照：Boolean 从 4.39 秒降到 0.088 秒，总管线从
4.74 秒降到 0.45 秒。旧 Boundary 规则仍失败，因此这组数据只证明 Manifold 性能，不代表产品
正确性；正式实现仍必须复用当前已验收 Direct Bridge 合同。

当前正式 Direct Bridge 在 Preview 数据已经存在时，Mixed Finalize 约 0.27 秒。将当前完整
Preview 与 Finalize 机械串联成一步仍会超过 80 秒，不能作为新实现；必须先删除运行时 node
code generation，再做一步式产品接线。

Artifacts：

- `/private/tmp/hst-preview-benchmark-20260730/results.json`
- `/private/tmp/hst-preview-eval-benchmark-20260730/results2.json`
- `/private/tmp/hst-curve-stage-benchmark-20260730/results.json`
- `/private/tmp/hst-curve-stage-benchmark-optimized2-20260730/results.json`
- `/private/tmp/hst-feature-chamfer-one-step-evaluation-20260730.json`
- `/private/tmp/hst-feature-chamfer-manifold-benchmark-20260730.json`

`hst-feature-chamfer-one-step-evaluation-20260730.json` 是被否决的 Exact 对照，仅用于证明
Cutter 构建成本；不得作为目标 Boolean 性能或产品正确性证据。
`hst-feature-chamfer-manifold-benchmark-20260730.json` 才是 Manifold 性能对照，但因仍使用旧
Boundary 规则，也不得作为产品正确性证据。

## 3. 为什么现有 GN 数据路径不成立

Geometry Nodes 的视觉 Boolean 很便宜，但 Finalize 为了找回每条 segment、station、Pipe owner、
source Surface Patch，在 Boolean 前后展开了大量 one-hot Named Attributes。这实际上是在 node
graph 里搭了一套临时数据库，成本随 Face/Point/segment 线性增长，而且这些数据只服务于随后
的 Python 拓扑重建。

这不是 Geometry Nodes 擅长的问题。继续做固定超大资产会引入容量上限；改成紧凑 ID 又无法
自然表达 Boolean 后的多 owner；把重数据延迟到 Finalize 仍保留了错误的两阶段交互。正确做法是
让 Python 在同一个事务里直接持有 plan 与 Cutter 身份，在 Boolean 后读取实际 Boundary 并完成
Bridge/Fill，不经过成千上万个临时 node attributes。

## 4. 目标产品行为

1. 用户选中一个闭合 Mesh，执行一次 Feature Chamfer；
2. Operator 读取 Sharp Edge，完成分析、Cutter、Boolean、Bridge/Fill；
3. 成功后保留原 Object 不变，选择独立结果 Object；
4. `Adjust Last Operation` 提供 Radius，以及可选的“保留 Cutter”诊断开关；
5. 修改参数时通过 Blender Redo 事务重建结果，不存在 Preview/Finalize/Cancel 按钮或状态；
6. 失败时不留下伪成功 Mesh；几何错误保留明确诊断并允许用户在左下角修改 Radius 重试。

## 5. 实施路径与硬门槛

### Phase A — 一步式 Python backend

复用当前已验收的 FeatureGraph、ChamferPlan、Curve Pipe、Boolean Pro 与 Direct Bridge 几何
规则，但把跨阶段 one-hot provenance 改为 Python 运行时合同。Boolean 部分必须对照资产中
Boolean Pro 的真实 Manifold Difference 分支，而不是旧 Python Exact Modifier：

- plan、segment station、owner surface pair 直接保存在内存结构中；
- Cutter 生成时保留 component/port 身份，Boolean 后只扫描真实 Boundary；
- source 与 Cutter 均为 closed manifold 时直接使用 Manifold solver；输入不满足时明确失败，
  不自动改用 Exact/Float；
- 复刻 Boolean Pro 在本 Operator 实际使用到的 Difference 输入组织、Intersecting Edges、
  New Faces、Boundary Edges、空结果检查、材质与法线处理；Boolean Pro 的通用 Slice/Union/
  Intersect/多 Object UI 分支不属于本工具实际 runtime，不复制到 Python；
- 通过 plan 拓扑、Boolean 传播的 compact owner 以及明确的 source Patch 身份完成绑定；
- 不创建 Preview modifier、owned Curve、动态 node group 或 source 上的 Preview 状态；
- 结果生成采用事务式 replace，支持 Redo/Undo，source 始终不变。

Go：10-cell 产品矩阵几何签名、closed manifold、zero-area、自交、Chamfer face/normal 合同与当前
已验收输出一致；正式入口一次执行得到结果；不存在按 Face/Point/segment 线性增长的 nodes。

Stop：任何 fixture 特判、nearest-only 归属猜测、复杂对象跳过/降级、固定 owner 容量、或以旧
失败后端代替当前已验收 Direct Bridge。

### Phase B — 性能优化

- 合并 Cutter Mesh，减少 Object/Modifier/RNA 往返；
- 对无相交 Cutter 批次保留现有图着色，统计真正 Boolean 批次数；
- 评估 Python 侧一次 Manifold multi-input 与按 overlap batch 的 Manifold；只有与 Boolean Pro
  几何和 Boundary outputs 等价才选择更快方案；
- 同一次 Redo 内复用已构造的 Mesh identity 表，避免再次扫描 source；
- 用批量 Mesh API 写入顶点、面和 compact attributes；不改用 Rust，除非 Python 纯计算重新成为
  已测主瓶颈。

性能目标：Mixed 正式一步执行冷运行 ≤ 2 秒；常见 simple case ≤ 1 秒。Manifold 对照的 Boolean
约 0.09 秒，因此剩余预算用于分析、边界身份绑定、Bridge/Fill 和 Blender 数据转换。

### Phase C — 正式入口验收

- 面板只保留一步式主按钮，不再显示动态 Preview/Finalize 和 Cancel；
- Operator 使用 `REGISTER, UNDO`、`invoke → execute`、`draw`，参数位于左下角；
- 正式 10-cell 产品矩阵 × 3、完整 Blender regression、GUI Redo/Undo、用户可见结果全部通过；
- 独立规格审计确认 runtime、测试、文档与用户行为一致后，状态升为 `VERIFIED`。

## 6. 风险

最大的风险不是性能，而是 Direct Bridge 当前依赖 GN Boolean 输出的细粒度 segment/station one-hot。
迁移时必须先建立等价的 Python Boundary binding，再移除旧链；不能先删 GN 再靠空间最近猜测补洞。
旧的一步式后端走了不同的 FeatureGraph、Exact Modifier 与 Boundary 规则，在 Mixed 上触发
Boundary 歧义，明确不能直接复活；这个失败不能归因于 Boolean Pro 的 Manifold 分支。

本轮保留 Curve/Plan 优化并停止固定 GN 资产方案。正式实现以“一步式 Python backend +
Boolean Pro 等价 Manifold Difference + 当前已验收 Direct Bridge 规则”为唯一主线。

## 7. 失效证据与重新验收条件

- 失效事实：旧、新相同 fixture/radius 的 Mesh 数量、几何 fingerprint、Chamfer Face 数和 Bridge job 数均不一致；用户反馈已证明差异是破坏性视觉回归，不是允许的拓扑重排。
- 根因：当前紧凑身份路径不能表达 Boolean junction 的多 owner；按 Pipe 投影重建 segment 时又把越界 station 夹到端点，导致错误或重复 Bridge 归属。
- 假绿原因：当前产品矩阵只验证输出存在、闭合、无零面积/非流形/自交及内部合同，没有运行旧正式路径作为 oracle，也没有固定相机的视觉差异门槛。
- 重新 Go：同一 fixture/radius 独立运行旧 Preview → Finalize 与一步式入口，比较规范化几何、Chamfer 区域、边界连通和法线；任一差异超出明确容差都必须标为 regression failure。视觉层只批量交付 `.blend` 供用户在 Blender 中检查。
- 重新 `VERIFIED`：全部正式测试 `.blend` 的旧/新等价门槛、完整回归、GUI Undo/Redo 和用户可见结果均通过，并完成独立规格审计。

当前重新验收结果（正确性恢复，不代表性能计划完成）：

- 10-cell × 3：每个 cell 的最终几何 fingerprint、Vertex/Edge/Face 和 Chamfer Face 数与旧版一致；
- 一步入口：单次执行得到最终 Mesh，临时 Preview 状态在事务结束前清理；
- `Keep Cutter`：保留可见 Cutter Object；
- 正确性自动层级已到 `VERIFIED`；按项目规则，用户打开批量 `.blend` 确认前不声明 `ACCEPTED`。
- 性能 Phase A/B 仍为 `STOP`：当前正确性恢复路径会临时建立旧 Preview 数据，不满足“不创建 Preview runtime”的目标；Mixed 目前约 97–176 秒，也未达到性能目标。任何后续提速都必须先通过上述旧版几何基线，不能再以不同几何换取速度。

Artifacts：

- `/private/tmp/hst-preview-finalize-parity-required10-authoritative-20260730/results.json`
- `/private/tmp/hst-one-step-transaction-targeted-20260730/results.json`
- `tests/artifacts/feature_chamfer_gn_gui_undo.json`
