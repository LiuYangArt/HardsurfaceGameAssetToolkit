# Collection Unreal 命名功能方案

## 目标

为选中 Object 直接所属的 Collection 提供批量 Unreal 风格命名，并让 Prop、Decal、Bake Low、Bake High 标记工具可选地复用同一规则。

## 用户入口

1. Utilities 侧栏新增“Rename Collections for Unreal”按钮。
2. 按钮只读取当前选中的 Object；收集所有直接所属 Collection，去重后一次处理。
3. 不递归处理父级、子级或兄弟 Collection。
4. Prop、Decal、Bake Low、Bake High 的 Adjust Last Operation 面板新增“Rename for Unreal”开关，默认关闭。
5. 开关关闭时保持原有命名行为；开启时先规范基础名，再追加既有业务后缀。

## 命名规则

- 空格、短横线、下划线、点号及其连续组合统一为单个下划线。
- 每个非数字片段转为首字母大写、其余小写；数字保持不变。
- 示例：`pipe-cap-a` → `Pipe_Cap_A`，`pipe-01-a` → `Pipe_01_A`，`uv-pipe` → `Uv_Pipe`。
- Blender 数字后缀视为普通片段：`pipe-cap.001` → `Pipe_Cap_001`。
- 已符合规则且不冲突的名称保持不变。
- 若目标名称被其他 Collection 占用，依次追加 `_001`、`_002`。
- Prop/Decal/Bake 联动时，先移除既有 Bake/LOD 后缀，再规范基础名，最后追加 `_Decal`、`_Low` 或 `_High`；最终名称同样使用下划线编号解决冲突。

## 代码结构

- `utils/collection_utils.py`：纯字符串规范化、唯一名称计算、单个 Collection 重命名、从 Object 收集直接 Collection。
- `operators/collection_ops.py`：独立批量 Operator；Prop/Decal Toggle 接入。
- `bake_ops.py`：Bake Low/High Toggle 接入。
- `ui_panel.py`：Utilities 增加独立按钮。
- 不新增全局设置，不修改 `auto_load.py`。

## 交互与安全

- 所有相关 Operator 使用 `REGISTER + UNDO`。
- `invoke()` 只校验必要上下文，然后直接执行，不弹阻塞窗口。
- Toggle 只作用于本次被标记的目标 Collection。
- 独立批量操作若没有选中 Object，明确取消并提示。
- 返回处理数量；同一 Collection 被多个 Object 引用时只处理一次。

## 验证

1. `collection_unreal_rename_smoke`：规则矩阵、多对象、多 Collection、直接归属去重、父子不递归、合规名不变、冲突 `_001/_002`。
2. `collection_marker_optional_rename_regression`：四个标记入口默认关闭保持旧行为；开启后规范基础名并保留业务后缀；类型与对象标记不回归。
3. 先运行上述两个 case，再运行完整 `python .\tools\run_blender_tests.py`。
4. 本功能不需要图片或视觉判定；headless 状态断言即为正式入口验证。
