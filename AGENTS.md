# HardsurfaceGameAssetToolkit

这是一个Blender插件，适配blender 5.0+ 
- 使用blender 5.0+ 的api
- blender 位置： "C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe"
- 主要用途是处理从 cad 软件过来的hardsurface模型，变成game-ready资产。 

## 语言风格
- 回复简短、准确、去重；以易读为先。

## 工作方式
- 先定位，再读取；避免直接通读大文件或大日志。
- 先用搜索或文件列表缩小范围，再按需读取相关片段。
- 修改前先查找并复用项目内已有模式；不要凭空发明新结构。
- 优先做最小充分修改；非当前任务不要顺手重构。
- 禁止修改auto_load.py


## 代码实现 (Implementation)

### 3.1 环境与API交互
-   **Blender版本**: 项目基于Blender 5.0 版本开发。
-   **API文档检索**: 使用 `context7 mcp` 检索Blender API文档，以确保对API的准确理解和正确使用。

### 3.2 结构与导入
-   **`import bpy`**: 必须在项目所有Python文件的文件头添加 `import bpy`。
-   **统一导入**: 所有的 `import` 语句都必须放置在文件头部，避免在函数中间进行导入。
-   **模块化设计**: 将通用的、可复用的功能抽象为独立的函数，并将其组织到 `.utils.py` 文件中。每段代码或每个函数体不应过长。

### 3.3 代码规范与可读性
-   **变量命名**: 变量名应具有表达性且易于阅读，避免过度缩写。例如，使用 `obj` 而不是 `o` 来表示对象（objects）。
-   **操作符 (Operator) 逻辑**:
    -   所有自定义的Blender Operator在 `execute` 方法执行主要逻辑之前，应先使用 `invoke` 方法检查上下文（context）是否合适。
    -   此项目使用 `auto_load` 机制，因此**无需**单独注册Operator。
-   **注释规范**:
    -   **功能性函数**: 对于所有非Blender Operator固定方法（如 `execute`, `invoke` 等）的功能性函数，必须添加**块注释 (block comment)** 来标记其用途，并详细说明所有参数的意义。
    -   **语言**: 注释内容使用中文书写，但涉及到的专业名词、API名称或代码专有名词（例如 `Mesh`, `Bounding Box`, `Vertex Group`）请使用英文原文。

## Blender Operator 交互规范
- 新增或修改 Blender operator 的参数交互时，默认先参考项目内已有同类工具，优先复用现有模式。
- 对可重复执行、参数可后调的工具，默认采用 bevel operator 的交互方式：
  `bl_options = {"REGISTER", "UNDO"}`，提供 `draw()`，`invoke()` 中完成必要校验后直接 `return self.execute(context)`。
- 这类参数不应在 operator 执行前弹出阻塞式窗口；应让参数出现在 Blender 左下角的 `Adjust Last Operation` 面板中。
- 除非用户明确要求，或该工具在执行前必须先确认/输入参数，否则不要使用 `invoke_props_dialog`、`invoke_props_popup`、`invoke_confirm` 这类阻塞式交互。
- 如果项目内已有对应的 scene/global 参数同步模式，新增参数时应优先沿用，不要单独发明另一套交互或存储方式。


## Agent 调用入口
- 本项目内置回归测试 skill：`F:/CodeProjects/BlenderAddons/HardsurfaceGameAssetToolkit/agent-skills/hst-blender-regression/SKILL.md`
- 当用户提到“回归测试 / Blender 升级检查 / 哪些功能坏了 / smoke test / headless 测试”时，优先使用该 skill。
- 统一入口命令：`python .\tools\run_blender_tests.py`
- 若需要读取最近一次结果，查看：`F:/CodeProjects/BlenderAddons/HardsurfaceGameAssetToolkit/tests/artifacts/results.json`

## 测试规范
- 测试规范文档：`F:/CodeProjects/BlenderAddons/HardsurfaceGameAssetToolkit/tests/TESTING_POLICY.md`
- 测试说明文档：`F:/CodeProjects/BlenderAddons/HardsurfaceGameAssetToolkit/tests/README.md`
- 新增功能、修 bug、做 Blender 升级兼容时，默认按 `tests/TESTING_POLICY.md` 补 smoke test 或 regression test。
- 已修过的 bug 默认补回归；可 headless 的新 operator 默认补 smoke test。
- 新增测试统一放到：`F:/CodeProjects/BlenderAddons/HardsurfaceGameAssetToolkit/tests/blender_test_driver.py`
- 功能改动若影响核心流程，完成前默认跑：`python .\tools\run_blender_tests.py`

## 验证
- 完成修改前，优先运行最小必要的验证命令；无法验证时明确说明原因。

## Agent 规格对齐与阶段门禁

### 目标入口契约

涉及 UI、Blender Operator、Geometry Nodes 或用户工作流的任务，修改前必须在计划或 tasklist 中明确并核对：

```text
UI 按钮/菜单
→ Operator bl_idname
→ action / invoke / execute
→ 实际 runtime path
→ 用户可见结果
```

- 首轮代码定位必须沿该路径逐段确认；不能只实现旁路 builder、实验 Operator 或离线 probe。
- 若实现过程中发现目标入口与原假设不一致，必须立即停止并更新计划，不得先完成旁路 prototype 后宣称已接入。
- “资产已存在”“底层函数可运行”“artifact 可打开”均不等于目标 Operator 已使用该实现。

### 四层验收

所有用户可见功能必须区分四层证据：

1. `Algorithm`：算法或数据合同正确。
2. `Backend`：Mesh、Curve、Geometry Nodes 等 backend 能生成 artifact。
3. `Operator`：从目标 Operator 入口运行，确认实际 runtime path 使用新 backend。
4. `Visual/Product`：真实文件中的用户可见结果符合产品语义。

低层通过不能代替高层。测试数量、字段存在、topology clean、headless JSON 或离线 `.blend` 只能支持对应层级的声明。

### Stop / Go 硬门禁

- 分阶段计划中的 Stop/Go 是硬约束，不是建议。
- 前一阶段任一必要门槛失败时，下一阶段只能更新设计和诊断，禁止实现或接入正式 runtime path。
- 每个阶段开始前必须写明：目标 Operator、用户操作、预期可见变化、自动证据、Go 条件。
- 每个阶段结束时必须从目标 Operator 做验收并留下可读取 artifact；旁路 probe 不能替代入口验收。

### 状态分级

阶段交付只能使用以下状态：

- `PROTOTYPE`：算法或 backend 局部可运行。
- `INTEGRATED`：目标 Operator 已接入。
- `VERIFIED`：真实文件的数值、拓扑和固定近景通过。
- `ACCEPTED`：用户在真实 UI 中验收通过。

禁止跨级声明完成。交付时必须同时报告当前状态、未通过门槛和本轮明确未做的范围。

### 完成前独立 Spec Audit

影响核心工作流的功能在完成声明前，必须进行独立 spec audit，至少核对：

- diff 是否实际修改目标 runtime path；
- 每项计划门槛是否有直接证据；
- 是否存在越阶段实现或 scope creep；
- 测试是否从目标 Operator 开始；
- 文档阶段状态是否与代码和用户可见行为一致。

发现任一高严重度偏差时，不得给出完成声明，应先恢复正确阶段边界。
