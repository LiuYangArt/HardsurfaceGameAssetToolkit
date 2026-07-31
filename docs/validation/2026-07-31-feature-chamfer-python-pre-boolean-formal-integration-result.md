# Feature Chamfer Python Boolean 前生产正式集成结果

日期：2026-07-31

环境：macOS / Blender 5.1.2

状态：`INTEGRATED / VERIFIED`（仅限 Boolean 前生产）；完整性能任务仍为 `STOP`

## 1. 本次实际替换

- 一步式正式入口不再为 source Patch、Cutter Pipe、segment membership、station 和 station² 动态创建逐 owner 的 Boolean 前 Geometry Nodes。
- Python 直接在临时 source/Cutter Mesh 上批量写入同一批属性；正式 wrapper 只用 3 个固定输入节点和 3 条连线把它们送进原有 Boolean Pro。
- Boolean Pro、Boolean 后动态身份整理和 Bridge/Fill 均保持原实现；没有失败时退回旧慢路径的 silent fallback。
- 正式操作结束或失败时，临时 Mesh、Object、Curve、modifier 和 owned Node Group 均会清理。

## 2. 代表样本硬门槛

样本：`feature-chamfer-topology-defect-mixed.blend` / `Extruded.002` / Radius 0.01。

| 项目 | 正式入口结果 |
|---|---:|
| 规范化 fingerprint | `f991142edfcad15a27e8e81d24609c1bd00812aa3054fad0f5968bfbc37ba107` |
| Vertex / Edge / Face | 3922 / 8054 / 4134 |
| Chamfer Face | 3454 |
| Boundary / non-manifold / zero-area | 0 / 0 / 0 |
| Python Boolean 前 producer | 0.021 秒 |
| 完整 Preview 建立 | 1.702 秒 |
| Boolean 后读取及 Bridge/Fill | 2.927 秒 |
| 正式一步式总耗时 | 4.635 秒 |

结论：结果等价门槛和本次 producer 阶段预算通过；2 秒产品总门槛未通过。正式入口当前已经是目标的
Python Boolean 前架构，但 Boolean 后动态身份整理仍存在，不能把本次集成写成完整性能优化完成。

## 3. 回归与清理

- Python 语法检查通过。
- Blender 5.1.2 全量自动回归 156/156 通过。
- 覆盖正式一步入口、代表样本冻结 oracle、四边 Cutter、重复执行、Radius 重建、Keep Cutter、取消、重命名 owner、Undo 合同与异常事务回滚。
- 自动验证未生成、渲染、读取或判断图片；产品视觉状态仍未达到 `ACCEPTED`。

## 4. 后续唯一主线

继续单独验证并替换 Boolean 后动态身份整理。下一阶段必须继续使用同一代表样本和冻结 oracle，先证明
最终结果不变，再要求正式一步式总耗时中位数不超过 2.00 秒、单次不超过 2.50 秒；未同时满足前不得扩展集成。
