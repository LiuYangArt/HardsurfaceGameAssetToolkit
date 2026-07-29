# Blender Test Fixtures

本目录中的 `.blend` 是随仓库分发的 immutable test input。测试和 probe 必须从 repository root 或脚本自身位置解析路径，不得依赖 Desktop、盘符、用户名或其他机器专属绝对路径。

## Feature Chamfer 产品矩阵

| Fixture | SHA-256 | Matrix 对象 |
|---|---|---|
| `feature-chamfer-product-simple.blend` | `1CBAB4C83C4D9F77BD2B0799257953AAEC32AA416994A1D8810425F3C2B94D8C` | `Extruded.002`, `Solid 44` |
| `feature-chamfer-product-tricky.blend` | `C7F57A54837A04F7E52B535BB47AF0ABEB05FCA4193DAC714FB3667EFB426F02` | `Solid.004`, `Solid.016` |
| `feature-chamfer-product-tricky-b.blend` | `A4C121B6BBBFFF58B94C3B7ED11BD82FE59C88A92569389FD27593ED65BE9A35` | `Extruded.003`, `Extruded.002` |
| `feature-chamfer-topology-defect-mixed.blend` | `80DA3EE4144BA83CAB4E9BED980C8829D846369F22A694ABFE1AA513C3A3D1B8` | `Extruded.002` |

`pipe-chamfer-test-tricky_b.blend` 是已有专项回归 fixture，内容与上表的 `feature-chamfer-product-tricky-b.blend` 不同；不要互相覆盖。

## 使用规则

- 只读打开 fixture；生成结果写入 `tests/artifacts/`。
- runner 中使用 `Path(__file__).resolve()` 推导 repository root。
- Windows 与 macOS 共用同一 fixture 文件和 hash。
- 若 fixture 必须更新，新增文件或显式更新 hash、矩阵基线和变更原因，不能静默覆盖。

当前推进计划：`docs/plan/2026-07-25-feature-chamfer-pipe-edge-loop-bridge-plan.md`。第一阶段优先验证 `simple`、`tricky_b`、`mixed` 三个 fixture，共 10 个目标场景。每个请求 Radius 都必须保留独立结果；原 Radius 失败不能改写成成功。若复杂孔洞在原 Radius 安全失败、source 不变、无坏输出、Preview 与红色问题边界可见，并且同一对象由正式 Operator 在明确更小 Radius 独立成功，则该场景可记为 `PRODUCT_SUCCESS_WITH_RADIUS_RETRY`。禁止 Operator 自动或静默降低 Radius。`tricky` 的 4 个 cell 允许安全失败并延后到第二阶段，但必须单独报告；可定位的几何失败显示红色位置，较早的合同失败保留已有现场并给出明确提示。完整产品范围最终仍是 14 个 cell。

法线恢复本阶段暂缓，正式输出不接入已知错误的法线处理。黑色三角只作为 shading 诊断，不得直接当作孔洞；是否真正缺面仍由边界、non-manifold 和线框拓扑检查判定。

当前产品操作语义：无交叉且形态单一的 Pipe 直接 Bridge 槽口两侧完整 Loop；即使原本
连续的 Pipe，与另一根 Pipe 交叉时也要在 junction 处切成连续槽段。已锁定配对但包含
巨大 U 形和多个共同显著转折的长 open 槽段，允许在共同转折处复用既有 Boundary Vertex
同步切成连续子段；每段仍调用原生 Bridge，最后 Fill 剩余交叉孔洞。禁止逐点对应、
重采样、局部重建、距离猜 Pipe 与 fixture 特判。
Cutter Curve 与 Boolean cyclic 槽必须保持完整闭环；仅在 Boolean 完成且两条完整 Boundary
Loop 已配对后，Bridge 预处理可以按冻结 Pipe 合同的共同环绕 station 划成局部开放弧段。
该逻辑分段不得修改 Cutter、切槽结果或原 Boundary Edge 全集。
fixture 清单不代表当前通过率；验收状态只以正式产品矩阵 artifact 为准。
当前全局 Curve 规则下的旧第一阶段自动 scope 位于
`tests/artifacts/feature_chamfer_phase1_required_global_curve_final_no_normals/results.json`：
其中 `mixed` 两个 cell 虽被自动分类为 `PRODUCT_SUCCESS`，但用户真实 UI 复核发现部分
Bridge 选错槽段左右 Edge Loop，产生跨槽长斜面、扭曲面和错误 chamfer 轮廓，因此这 2 个
结果及当时的第一阶段通过结论已作废。2026-07-27 的后续修复同样被用户对 Mixed 下方
U 形槽的真实 UI 复核推翻，不再作为正式证据。共同大转折分段修复后的正式 10 cells × 3
证据位于 `/private/tmp/hst-turn-split-final-required10-20260728/results.json`；该证据曾证明
Mixed `26a/26b` 在两个 Radius 由六个共同转折拆成七个连续原生 Bridge job，但随后被
Tricky-b `32a/32b` 的标准 180° open U 形扭曲推翻为过拟合，不能继续声明第一阶段通过。
通用规则必须逐处处理双方同步局部大转折，不使用累计角度、最少转折数或 fixture 身份。
`tricky` 的 4 个延后场景均连续 3 次
`SAFETY_PASS`，结果位于 `/private/tmp/hst-turn-split-tricky-safe-20260728/results.json`。
最终完整项目回归 146/146 位于 `/private/tmp/hst-turn-split-final-full-regression-20260728/results.json`。
通用逐处规则的新证据位于 `/private/tmp/hst-general-turn-split-required10-final-20260728/results.json`：
10 cells × 3 全部稳定 `PRODUCT_SUCCESS`；Mixed `26a/26b` 六切点/七 job，Tricky-b
`32a/32b` 两切点/三 job，均由同一正式规则命中。延期安全证据位于
`/private/tmp/hst-general-turn-split-tricky-safe-final-20260728/results.json`，完整回归
147 / 147 位于 `/private/tmp/hst-general-turn-split-full-regression-final-20260728/results.json`。
该证据与独立审计只证明 open 分段达到 `VERIFIED`。2026-07-29 的真实 UI 复核又发现
Tricky-b `Extruded.002` Radius `0.01` 的 cyclic 整环原生 Bridge 存在局部累计错位，整体状态
已回退为 `INTEGRATED`；本轮只验收该 Radius，不运行该对象的 `0.03`。
本轮同时运行其余 8 个第一阶段 cell 作为回归门禁；长期 10-cell 产品矩阵范围保持不变。
cyclic Bridge 预处理现已在正式 Operator runtime 中完成并达到 `VERIFIED`：目标 Radius
`0.01` 连续 3 次成功，26（`86/27`）与 31（`122/31`）均分为四段且原 Edge 精确、互斥、
完整覆盖；其余 8 cells × 3 全部稳定成功，完整项目回归 `150 / 150`。证据分别位于
`/private/tmp/hst-cyclic-target-matrix-final4-20260729/results.json`、
`/private/tmp/hst-cyclic-other-eight-final-20260729/results.json` 与
`/private/tmp/hst-cyclic-full-regression-final3-20260729/results.json`。用户真实 UI 复核前不声明
`ACCEPTED`。

2026-07-29 Bridge 前输入清理继续使用同一 `tricky_b / Extruded.002 / 0.01` 产品 fixture。
用户确认 runtime 组 37 与 40 配对正确；正式实现按左右侧分别 Merge 极近点并 Dissolve
无支路严格共线 Vertex。组 37 清理 `22/7 → 21/7`，组 40 清理 `21/20 → 20/20`，两组
零长度输入归零且 source 不变。新目标矩阵位于
`/private/tmp/hst-bridge-cleanup-target2-20260729/results.json`，其余 8-cell 回归位于
`/private/tmp/hst-bridge-cleanup-other8-20260729/results.json`，固定近景位于目标目录的
`evidence/runtime_37_wire.png` 与 `evidence/runtime_40_wire.png`。清理安全合同覆盖跨侧极近点、
open 端点、第三条 Edge、轻微折角和偏线超阈值；完整回归 `152 / 152` 位于
`/private/tmp/hst-bridge-cleanup-full-regression-final-20260729/results.json`，延期 tricky
4 cells × 3 的稳定安全失败位于 `/private/tmp/hst-bridge-cleanup-tricky-safe-20260729/results.json`。

用户真实 UI 随后证明组 40 在 `Radius × 1e-6` 下仍扭曲，而手动 `0.01 cm` Merge 后正常；
旧目标和完整回归 artifact 因此不能继续证明视觉修复。正式相对阈值现改为 `Radius × 0.01`，
并受单侧链中位 Edge 长度 `1%` 的上限约束；在该 fixture 中为 `1e-4` Blender unit，用于清理旧规则遗漏的 `6.59e-5` 极短边；新的产品矩阵、
近景和完整回归完成前状态为 `INTEGRATED`。

用户确认 Tricky-b 清理修复后，`simple / Extruded.002` 两个 Radius 又暴露 cyclic 双环共同
切点回归：正式实际输入 3/4/7/8 中，一侧同一 station 邻域存在两个不连续 plateau，旧数值
排序选中了远离另一侧槽边的切点，造成后半圈长短弧错配。修复必须先锁定既有 Pipe、槽段、
owner pair 与 station 邻域，再以两侧 Boundary 的局部空间邻接关系消歧，并按同一相邻
station 区间生成每个 Bridge job；禁止安全停止、跳过或整环回退。完成正式入口和全范围
回归前状态为 `INTEGRATED / STOP`。

该回归现已修复并达到 `VERIFIED`。simple `Extruded.002` Radius `0.01 / 0.03` 各连续
3 次正式成功，3/4/7/8 的两侧 station 区间一致且弧长比小于 `1.04`，输出闭合、无零面积
或反面；第一阶段 10 cells × 3 全部稳定 `PRODUCT_SUCCESS`，完整项目回归 `154 / 154`。
证据位于 `/private/tmp/hst-simple-cyclic-final-10cells-20260729/results.json` 与
`/private/tmp/hst-simple-cyclic-final-regression2-20260729/results.json`。用户真实 UI 验收前
不声明 `ACCEPTED`。
