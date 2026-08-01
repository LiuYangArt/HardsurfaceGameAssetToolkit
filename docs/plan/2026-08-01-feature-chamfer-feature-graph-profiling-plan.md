# Feature Chamfer FeatureGraph 分段性能验证计划

日期：2026-08-01
状态：`PROFILING VERIFIED / RUST COMPACT PROTOTYPE PASS / FORMAL INTEGRATION NOT AUTHORIZED`

## 1. 要回答的问题

在当前正式 UI `Feature Chamfer` 一步式 Operator 中，Mixed 样本的 FeatureGraph 阶段约 `0.591s / 29.2%`。本轮只回答：耗时具体集中在哪些可隔离子阶段，下一步应先优化 Python 数据路径、建立 Rust 数值原型，还是停止该路线。

## 1.1 已完成的 profiling 结论

三次未插桩正式 Operator 与三次插桩运行已完成，结果完全等价。未插桩 FeatureGraph 中位 `0.541568s`，Operator 中位 `1.841912s`。最大可隔离热点是 global combination score exclusive：插桩中位 `0.351563s`，按同边界未插桩折算约 `0.340919s / 62.95%`；另有 containment/BVH query `0.114414s`。该热点同时满足 FeatureGraph 下降至少 35% 与 Operator 理论节省至少 0.20s 的路线门槛。

结论：profiling `PASS`。首轮 Rust 全量回传接口因传输开销为 `STOP`；随后紧凑接口原型仍计算全部 729 项、只回传正式下游所需结果，端到端快 `87.18%`、节省 `0.894533s`，全量审计 729/729 等价，状态为 `PROTOTYPE / PASS`。下一步可另建正式 Operator A/B 计划，但仍未授权接入。证据见 `docs/validation/2026-08-01-feature-chamfer-feature-graph-rust-compact-interface-result.md`。
## 2. 固定合同

- 固定环境：Windows x86-64、当前 Blender 5.2、项目当前正式 runtime。
- 固定样本：`tests/fixtures/feature-chamfer-topology-defect-mixed.blend`。
- 固定对象与参数：`Extruded.002`、Radius `0.01`、正式 UI Operator。
- Oracle：插桩前当前正式 Operator 的 FeatureGraph/ChamferPlan 结构化结果、最终 Mesh fingerprint、计数、健康性与完成状态；先冻结后插桩。
- 执行边界：三次同轮正式 Operator；Blender 启动时间不计。
- 允许：独立 worktree 中的旁路计时插桩、只读调用计数、输入规模统计和机器 JSON。
- 禁止：改变 FeatureGraph 算法、阈值、排序、缓存、BMesh/Bridge/Fill/Boolean、正式入口默认行为；不得接入 Rust 或 Bridge 原型；不得生成或判断图片。

## 3. 分阶段测量

必须拆分且避免重叠计时：

1. BMesh 创建/复制、lookup 与 Sharp Edge 提取；
2. Surface Patch 建图；
3. Edge metadata、vertex adjacency 与局部 pairing；
4. BVH 构建；
5. junction options / search-space 构建；
6. 每个全局组合的评分，其中单列 endpoint containment / BVH 查询；
7. group traversal 与 canonical 排序；
8. FeatureGraph stats/结果序列化；
9. 外层 ChamferPlan、source patch IDs、endpoint token；
10. 未归属时间与插桩开销。

同时记录 Mesh V/E/F、Sharp Edge、Patch、junction、candidate、combination、score 与 BVH query 数量。各子项之和必须可解释正式 `feature_graph` stage；不能只用 profiler 汇总替代正式阶段计时。

## 4. 等价与性能门槛

### Phase 0 — 冻结 oracle

状态起点：`NOT RUN`。
Go：未插桩正式运行结果稳定，结构化 FeatureGraph/Plan 与最终结果可复查。
Stop：无法取得同一正式边界或结果不稳定。

### Phase 1 — 低开销插桩

Go：插桩与 oracle 的 FeatureGraph groups、vertex matching、ChamferPlan、最终 fingerprint/计数/健康性完全一致；计时字段不得进入语义 fingerprint。
Stop：出现第一处语义差异，后续热点判断 `NOT RUN`。

### Phase 2 — 三次正式分段 benchmark

Go：三次有效运行，子项加未归属时间可解释总阶段，中位数与原始明细写入 JSON。单项优化候选还必须满足：

- 单个可隔离热点预计可让 FeatureGraph 中位下降至少 `35%`；
- 按当前正式 Operator 估算可节省至少 `0.20s`；
- 三轮均为同一输入规模，且没有明显异常离群。

低于门槛不进入实现，标 `STOP`；这不是功能失败。

### Phase 3 — 路线判断

- 重复 Mesh/BMesh 扫描、Python 集合转换或排序占主导：建议 Python 原地优化。
- 全局组合评分或 containment/BVH 的纯数值批处理占主导：建议另建 Rust replay/oracle 计划。
- Blender 数据读取或分散小项占主导：停止 FeatureGraph Rust 路线，优先考虑安全缓存或其他阶段。

本轮不实施候选优化；任何实现必须另行授权。

## 5. 状态定义

- `PASS`：正式边界等价，三轮证据完整，并能给出满足门槛的单一候选路线。
- `STOP`：出现明确等价差异，或没有候选达到收益门槛。
- `BLOCKED`：外部条件确实阻止正式验证，且替代路径审计后仍无法进行。
- 前一阶段未通过，后一阶段为 `NOT RUN`。

## 6. 证据路径

- 结果文档：`docs/validation/2026-08-01-feature-chamfer-feature-graph-profiling-result.md`
- 机器摘要：`tests/artifacts/feature_chamfer_feature_graph_profile/summary.json`
- Oracle 与三轮明细：`tests/artifacts/feature_chamfer_feature_graph_profile/`
- 日志：`tests/artifacts/feature_chamfer_feature_graph_profile/logs/`
