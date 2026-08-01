# Feature Chamfer Bridge 链清理分阶段优化方案

日期：2026-08-01  
状态：`PROPOSED / NOT STARTED`  
目标入口：UI `Feature Chamfer` → `hst.feature_chamfer_gn`  
代表样本：`tests/fixtures/feature-chamfer-topology-defect-mixed.blend` / `Extruded.002` / Radius `0.01`

## 1. 结论

本方案先优化 Feature Chamfer Bridge 链清理中的 Python 无修改路径；只有剩余耗时仍达到 Rust 启动门槛，才优化纯数值计算。无论是否进入 Rust 阶段，都不把 Blender `BMesh`、Bridge、Fill 或拓扑修改迁移到 Rust。

第一目标是利用现有清理结果建立无修改快速路径：当一条 side chain 的 `merged_vertex_count == 0` 且 `dissolved_vertex_count == 0` 时，清理前后坐标和拓扑未改变，直接记录最大几何偏差为 `0.0`，跳过双向折线偏差计算。

仅当这一步完成后，剩余已修改 chain 的偏差计算仍明显占时，第二目标才是用 Rust 批量替换：

- `_point_to_segment_distance()`
- `_polyline_maximum_deviation()`

它们负责验证清理前后折线的几何偏差，当前在 Mixed 样本中约执行 36.8 万次点到线段距离计算。160 条 side chain 中约 121 条没有实际修改，先消除这些无效计算，才能准确判断原生加速是否值得承担构建和发布成本。

Python 路径永久保留：

- Windows：默认优先使用 Rust 原生模块；
- macOS / Linux：默认使用 Python；
- Windows 原生模块缺失或 ABI 不兼容：使用 Python；
- 原生模块已经成功加载、但执行时发生异常或返回非法结果：直接报错，不静默切回 Python。

Python 实现既是跨平台后端，也是 Rust 实现的正确性 oracle。

## 2. 当前基线

测量环境：

- Blender 5.2.0 LTS；
- Blender Python 3.13，扩展后缀 `.cp313-win_amd64.pyd`；
- AMD Ryzen 9 9950X；
- Mixed / `Extruded.002` / Radius `0.01`；
- 正式一步式 Operator。

现有 profile 的主要耗时：

| 阶段 | 代表耗时 | 说明 |
|---|---:|---|
| Feature Chamfer Operator | 约 2.0–2.5 秒 | 运行波动较大，需以同轮 A/B 为准 |
| Bridge / Fill | 约 0.86–1.05 秒 | 当前最大阶段之一 |
| Bridge 链清理 | 约 0.40–0.43 秒 | 160 条 side chain |
| 折线最大偏差验证 | 约 0.33 秒 | Bridge 链清理的主要纯计算热点 |
| 自交检查 | 约 0.09 秒 | 本方案不改 |
| Boolean | 约 0.32–0.34 秒 | 本方案不改 |

160 条 side chain 中，约 121 条最终没有发生合并或 dissolve。第一版先用 Python 快速路径消除这些 chain 的偏差验证，不改变任何清理判断。Rust 是否启动由优化后的剩余耗时决定，不再预设为必做阶段。

Mixed 当前 dissolve 后结果已由用户人工确认无可见问题。旧测试中的拓扑计数未同步，不作为本方案的阻塞条件；本方案仍要求 Python 与 Rust 在同一当前代码、同一输入下结果一致。

## 3. 范围

### 3.1 第一阶段包含

1. 冻结 Mixed / Radius 0.01 当前结果与分阶段耗时；
2. 对没有发生 merge/dissolve 的 chain 跳过双向折线偏差计算；
3. 保持已修改 chain 的原 Python 验证完整不变；
4. 添加快速路径命中、未命中和结果等价测试；
5. 重新测量 Mixed，并以剩余耗时决定是否启动 Rust。

### 3.2 条件启动的 Rust 阶段

仅在 Python 快速路径通过后，Bridge 链清理中位耗时仍 `>= 0.15 秒`，或剩余偏差内核中位耗时仍 `>= 0.10 秒` 时包含：

1. 建立独立 Rust crate，编译为 Blender Python 可导入的 Windows `.pyd`；
2. 只将仍需验证的已修改 chain 坐标打包为连续数组，一次调用 Rust；
3. Rust 批量计算 source/cleaned 折线的双向最大偏差；
4. Python 根据 Rust 返回结果继续执行原有合同检查；
5. 保留完整 Python 实现和显式后端选择；
6. 添加 Python/Rust 等价测试、fallback 测试和 Mixed benchmark；
7. 只有结果一致且明显提速后，才允许接入正式入口的 `auto` 模式。

### 3.3 不包含

- 不在 Rust 中持有或修改 `BMesh`；
- 不迁移 `bmesh.ops.remove_doubles`、`dissolve_verts`、Bridge 或 Fill；
- 不修改清理阈值、共线规则、chain 排序或 dissolve 语义；
- 不修改 FeatureGraph、Cutter、Boolean、自交检查或补面 dissolve；
- 不为通过性能门槛更改用户可见几何；
- 不修改 `auto_load.py`；
- 第一版不提供 macOS/Linux 原生二进制；
- 不把原生模块执行错误伪装成正常 fallback。

## 4. 架构

```text
BMesh / Bridge job
    │
    ├─ Python 提取并排序 source/cleaned chain 坐标
    │
    ├─ merged == 0 且 dissolved == 0
    │      └─ maximum deviation = 0.0，跳过距离计算
    │
    └─ chain 确实被修改
           ├─ backend = python
           │      └─ 现有 Python 几何偏差计算
           │
           └─ Rust 阶段已通过且 native 可用
                  └─ 一次批量调用 Rust
                         └─ 返回已修改 chain 的 maximum deviation

Python 统一执行：
阈值判定 → BMesh 拓扑修改 → Bridge/Fill → 结果发布
```

原生后端只处理值类型数据，不接收 `bpy`、`bmesh`、`mathutils.Vector` 或 Blender 内存指针。

## 5. 原生接口合同

建议内部模块名：`_hst_feature_chamfer_native`。  
建议使用 PyO3 构建 Python extension，而不是裸 `ctypes` DLL。

第一版只暴露一个批量入口，概念接口如下：

```text
polyline_maximum_deviation_batch(
    source_coordinates,
    source_offsets,
    cleaned_coordinates,
    cleaned_offsets,
    cyclic_flags,
) -> deviations
```

数据约束：

- coordinates 为连续 `float64` XYZ；
- offsets 定义每条 chain 在坐标数组中的区间；
- cyclic_flags 与 chain 数量相同；
- 返回值按输入顺序一一对应；
- 空链、单点链、NaN、Inf、越界 offset 必须明确报错；
- Rust 内部不得自行改变精度、容差或排序；
- 输出必须是有限、非负 `float64` 或与 Python 一致的 `inf`；
- 一次处理本次 Operator 的全部待验证 chain，避免细粒度跨语言调用。

第一版优先保持与 Python 相同的运算顺序和 `float64` 语义。SIMD、并行和空间索引属于后续独立优化，每次只能引入一种变化并重新做等价验证。

## 6. 后端选择与 fallback

建立单一后端适配层，业务代码不得散落平台判断。

建议支持三种测试模式：

| 模式 | 行为 |
|---|---|
| `auto` | Windows 尝试加载 native；不可用则 Python。macOS/Linux 直接 Python |
| `python` | 强制 Python，用作 oracle 和跨平台验证 |
| `native` | 强制 native；缺失或不兼容直接失败，用于 CI 和 benchmark |

`auto` 只允许在“能力不可用”时 fallback：

- 平台没有原生构建；
- 模块文件不存在；
- Python ABI 或架构不匹配；
- import 阶段确认模块不可用。

以下情况禁止 fallback：

- native 已成功 import 后计算异常；
- native 返回长度错误、NaN、负数或其他合同违规；
- native 与 Python shadow comparison 不一致；
- 原生进程崩溃。

后端选择应写入 Operator 统计，例如：

- `bridge_cleanup_backend`；
- `bridge_cleanup_native_available`；
- `bridge_cleanup_fallback_reason`；
- `bridge_cleanup_kernel_seconds`；
- `bridge_cleanup_batch_count`。

fallback 原因只记录能力信息，不吞掉非预期错误。

## 7. 构建与分发

### 7.1 Windows

当前 Blender 5.2 使用 CPython 3.13，第一版目标为：

- Windows x86-64；
- Blender Python 3.13；
- `cp313-win_amd64.pyd`；
- Rust stable；
- release 构建；
- MSVC 工具链。

构建脚本必须：

1. 明确使用 Blender 对应 Python ABI；
2. 输出到独立 build/artifact 目录；
3. 不覆盖源码；
4. 记录 Rust、Cargo、Python、Blender 和目标架构版本；
5. 在干净环境中可重复构建；
6. 将 Cargo `target/`、临时 wheel 和调试符号按项目发布策略处理。

### 7.2 macOS / Linux

第一版不要求 Rust 工具链或原生模块。插件安装后必须直接使用 Python 路径，功能完整可用。

未来若发布对应原生构建，应作为新的独立任务处理平台 ABI、签名、架构和打包，不改变现有 fallback 合同。

### 7.3 插件发布

原生文件应视为可选能力，不应让插件注册依赖它。插件导入、面板显示和其他工具不能因为 native 缺失而失败。

## 8. 分阶段执行

### Phase 0 — 冻结当前 Python oracle

状态：`NOT STARTED`

只运行 Mixed / Radius 0.01，记录：

- 正式 Operator 总耗时；
- Bridge/Fill 总耗时；
- Bridge 链清理总耗时；
- 偏差内核调用次数、chain 数、坐标数和耗时；
- 每条 chain 的输入坐标、cyclic 标记和 Python deviation；
- 合并和 dissolve 决策；
- 当前最终结果的必要诊断与 `.blend`。

至少三次运行。当前已人工接受的 dissolve 后结果作为产品基线；本阶段不要求恢复旧拓扑计数。

Go：能够重放全部偏差输入，并稳定得到相同 Python 决策。  
Stop：输入无法独立提取，或计时仍把 BMesh 修改混入纯计算内核。

### Phase 1 — Python 无修改快速路径

状态：`PROTOTYPE`

在正式 Python 路径中加入单一短路条件：只有 `merged_vertex_count == 0` 且 `dissolved_vertex_count == 0` 时，才把 `maximum_deviation` 直接记为 `0.0`。已修改 chain 仍完整执行现有双向偏差验证。

必须证明：

- 快速路径命中数与无修改 chain 数完全一致；
- 命中前后的有序坐标相同，偏差定义上必然为零；
- 所有 merge/dissolve 决策、Bridge/Fill 记录、Mesh 健康性和用户可见结果不变；
- Mixed / Radius 0.01 至少三次同轮基线/优化 A/B；
- 分开记录快速路径命中数、剩余偏差调用数与耗时。

Go：结果等价，且 Bridge 链清理中位耗时明显下降。  
Stop：快速路径覆盖任何已修改 chain，或结果/清理决策出现差异。

Rust 启动判断：

- Bridge 链清理中位耗时 `< 0.15 秒`，且剩余偏差内核中位耗时 `< 0.10 秒`：Rust 状态为 `NOT NEEDED`，结束本轮；
- 任一指标达到或超过上述门槛：允许进入 Phase 2；
- 不允许仅凭优化前的 `0.40–0.43 秒`直接启动 Rust。

### Phase 2 — Rust 旁路原型

状态：`PROTOTYPE`

只处理 Phase 1 后仍需验证的已修改 chain，实现 Rust 批量内核，但不接正式入口。用 Phase 0/1 保存的数据离线比较：

- 每条 deviation；
- 最终阈值布尔判断；
- 极端输入：open/cyclic、短链、退化 segment、空或非法数据；
- Rust 调用开销；
- 单线程 release 性能。

离散判断必须完全一致。浮点数首先要求逐值一致；若编译器运算差异导致末位变化，只能依据 Python 自身重复运行和实际阈值距离预先确定容差，不能看到失败后任意放宽。

Go：

- 全部 replay 样本判断一致；
- Rust 内核中位耗时至少降低 70%；
- 单次批量调用，无逐 chain/逐点 Python↔Rust 往返；
- native 缺失时 Python replay 完整通过。

Stop：

- 需要改变清理阈值或计算语义；
- 加速后内核仍超过约 0.15 秒；
- 跨语言打包成本抵消大部分收益；
- 两轮修正后仍无法稳定复现 Python 决策。

### Phase 3 — Bridge 清理 A/B 集成

状态仍为 `PROTOTYPE`。

在同一份当前代码中分别强制 `python` 与 `native`，只跑 Mixed / Radius 0.01。两条路径必须产生相同：

- 每条 chain 的清理决策；
- merged/dissolved 计数；
- Bridge job 与 Fill 记录；
- Chamfer Face 标记和必要产品诊断；
- 用户可见结果；
- Operator 完成状态。

性能门槛：

| 指标 | Go |
|---|---:|
| 偏差内核 | 相比 Python 中位数下降 ≥ 70% |
| Bridge 链清理 | 相比 Python 中位数下降 ≥ 50% |
| 正式 Operator | 同轮 A/B 中位数至少下降 0.20 秒，或下降 ≥ 10% |
| 性能回退 | 三次运行不得有一轮明显慢于 Python |

Go：正确性与性能同时通过。  
Stop：只快但决策不同，或结果相同但总 Operator 没有实质下降。

### Phase 4 — 正式入口集成

只有 Phase 3 通过后才进入 `INTEGRATED`：

1. 正式入口默认使用 `auto`；
2. Windows 原生模块可用时必须有证据证明实际调用 native；
3. Windows 移除/重命名原生模块后必须完整走 Python；
4. 强制 `native` 且模块缺失时必须明确失败；
5. 注入 native 运行异常，证明不会静默 fallback；
6. macOS/Linux 不安装 native 也能注册插件并完成 Feature Chamfer；
7. 保留 Python 强制模式，便于诊断和回归。

集成后仍先只跑 Mixed。通过后再运行最小相关回归，最后才扩展完整矩阵。

### Phase 5 — 扩展验证

满足正式入口门槛后：

- Mixed 两个 Radius；
- simple 与 tricky_b 代表对象；
- Feature Chamfer 相关 smoke/regression；
- GUI Adjust Last Operation、Undo/Redo、Keep Cutter；
- 规格审计：UI、Operator、后端统计、构建产物与文档指向同一 runtime。

自动化最高状态为 `VERIFIED`。涉及最终视觉结果时，批量交付 `.blend` 由用户手动确认；不生成或判断图片。

## 9. 测试要求

至少覆盖：

1. Python 单元/重放测试；
2. Rust crate 测试；
3. Python 与 Rust 参数化等价测试；
4. `auto/python/native` 三种模式；
5. Windows native 可用和缺失两种安装状态；
6. native import 失败与 native 执行失败的不同处理；
7. Mixed 正式 Operator A/B benchmark；
8. 未安装 Rust、Cargo 或编译工具的用户仍可运行插件；
9. 原生模块不影响插件注册和其他 Operator；
10. 未知原生异常保留错误上下文并直接抛出。

性能测试必须使用 release 原生模块；debug 构建不能作为结论。

## 10. 产物

建议目录：

```text
tests/artifacts/feature_chamfer_rust_bridge_cleanup/
```

至少包含：

- `environment.json`：Blender/Python/Rust/CPU/commit/fixture；
- `python_oracle.json`：批量输入、输出和清理决策；
- `native_comparison.json`：逐 chain 对比；
- `timings.json`：Python/native 分阶段三次结果；
- `fallback_matrix.json`：平台、模块状态和选择结果；
- `logs/`：构建与 Blender 运行日志；
- `result-python.blend`：Phase 1 达到性能门槛后交付；若进入并通过 Phase 3，再增加 `result-native.blend`；
- `audit.md`：每阶段 Stop/Go 记录。

## 11. 风险

### 11.1 Python ABI

Blender 升级可能更换 Python 次版本，现有 `.pyd` 随即不可加载。该情况必须自动使用 Python，并在统计中记录 ABI 不匹配。

### 11.2 浮点差异

Rust 编译器优化、FMA 或 SIMD 可能改变末位结果。第一版不启用会改变运算语义的优化；阈值附近的判断必须与 Python 一致。

### 11.3 跨语言复制成本

若每条 chain 单独调用或反复创建 Python 对象，可能抵消收益。接口必须批量化，后续可再评估 buffer protocol/NumPy 零拷贝，但不得在第一版同时扩大复杂度。

### 11.4 原生崩溃

Python 异常可捕获，但 Rust panic、内存错误或非法指针可能终止 Blender。Rust 边界禁止 `unsafe`，除非有单独审计、必要性证明和测试。panic 必须转为 Python 异常。

### 11.5 发布体积与维护

新增原生文件会增加构建、签名和版本矩阵。第一版只承诺 Windows x86-64 + Blender 5.2/Python 3.13；其他平台始终有 Python 功能路径。

## 12. 后续候选，不属于本轮

若本轮通过但总耗时仍不理想，再单独评估：

1. 将短边簇、共线 dissolve 候选计算移入 Rust，Python 只执行 BMesh 修改；
2. FeatureGraph 全局组合评分及独立 Rust BVH；
3. 对折线距离使用空间索引、SIMD 或受控并行。

每项都必须重新建立 Python oracle、旁路原型和单独性能门槛，禁止与第一版一次性混做。

## 13. 完成定义

Python 快速路径路线只有同时满足以下条件，才能声明 `VERIFIED`：

1. 正式入口实际使用无修改快速路径，且 Phase 1 正确性与性能门槛通过；
2. 无修改 chain 才能命中，已修改 chain 继续执行完整偏差验证；
3. Mixed、相关代表样本、回归和 GUI 行为通过；
4. 正式 runtime、测试、artifact 和文档一致；
5. 若剩余耗时低于 Rust 启动门槛，明确记录 Rust 为 `NOT NEEDED`，不把未实现 native 视为缺项。

若 Phase 1 触发 Rust 启动门槛，则还必须满足：

1. Windows 正式入口实际调用 Rust，并达到 Phase 3 性能门槛；
2. Python 与 Rust 清理决策和用户可见结果一致；
3. macOS/Linux、Windows native 缺失和 ABI 不匹配时 Python 路径完整可用；
4. native 执行错误不会被 silent fallback 掩盖；
5. release 构建可重复，产物版本信息可追溯。

用户确认最终批量 `.blend` 后，状态才可从 `VERIFIED` 升为 `ACCEPTED`。
