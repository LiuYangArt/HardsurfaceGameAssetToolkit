# HardsurfaceGameAssetToolkit

这是一个Blender插件，适配blender 5.0+ 
- 使用blender 5.0+ 的api
- blender 位置： win 系统下 "C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe"  mac 下自行查找，已安装可用版本。
- 主要用途是处理从 cad 软件过来的hardsurface模型，变成game-ready资产。 

## 语言风格
- 回复简短、准确、去重；以易读为先。

## 工作方式
- 先定位，再读取；避免直接通读大文件或大日志。
- 先用搜索或文件列表缩小范围，再按需读取相关片段。
- 修改前先查找并复用项目内已有模式；不要凭空发明新结构。
- 优先做最小充分修改；非当前任务不要顺手重构。
- 禁止修改auto_load.py
- 性能重构必须先把“效果不变”和“性能目标”拆成两个同时成立的硬门槛。旧结果必须作为 oracle；新路径在单个最复杂代表样本上达到结果等价且明显提速前，只能是旁路 `PROTOTYPE`，禁止接正式入口。
- “退回旧实现 / 包装旧流程 / 恢复正确性”只能声明 `RECOVERY`，不得记为性能任务进度、不得声明计划完成。若新架构失败，立即恢复正式入口并停止集成；后续时间只能用于独立原型，不得反复重写回归证据来包装失败路线。
- 性能任务开工前必须冻结一个最复杂样本的旧结果与阶段耗时；首个开发门槛只跑该样本。未同时满足结果等价和阶段预算，不得扩展到完整矩阵、GUI、完整回归或大规模文档更新。
- 每 60 分钟或每次路线失败后必须重新核对：正式 runtime 是否仍是目标架构、最复杂样本是否等价、耗时是否实质下降。任一答案为否，状态保持 `STOP` 并向用户报告，禁止继续消耗数小时后才暴露偏航。
- 禁止在测试、诊断和验收流程中生成、渲染、读取或判断 PNG、JPEG、截图等图片；图片不得作为 PASS、Stop / Go 或完成证据。
- 需要视觉验证时，只输出包含最终结果和必要诊断标记的 `.blend`，明确请求用户在 Blender 中手动检查并反馈；Agent 不得代替用户看图并判定通过。
- 同一轮有多个待视觉验证项时，必须一次性批量生成并集中交付全部 `.blend` 和检查清单，不得逐项生成、逐项请求反馈。


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
- 项目内置 Edge 可视化 skill：`.agents/skills/hst-edge-visualizer/SKILL.md`。
- 当用户要求把 residual、unconsumed 或难以观察的 Edge 做成红/绿/蓝粗线时，优先使用该 skill 输出可检查 `.blend`；禁止生成近景图。

## 测试规范
- 测试规范文档：`F:/CodeProjects/BlenderAddons/HardsurfaceGameAssetToolkit/tests/TESTING_POLICY.md`
- 测试说明文档：`F:/CodeProjects/BlenderAddons/HardsurfaceGameAssetToolkit/tests/README.md`
- 新增功能、修 bug、做 Blender 升级兼容时，默认按 `tests/TESTING_POLICY.md` 补 smoke test 或 regression test。
- 已修过的 bug 默认补回归；可 headless 的新 operator 默认补 smoke test。
- 新增测试统一放到：`F:/CodeProjects/BlenderAddons/HardsurfaceGameAssetToolkit/tests/blender_test_driver.py`
- 功能改动若影响核心流程，完成前默认跑：`python .\tools\run_blender_tests.py`

## 验证
- 完成修改前，优先运行最小必要的验证命令；无法验证时明确说明原因。

## 用户可见功能的验收规则

- 涉及 UI、Blender Operator 或 Geometry Nodes 的任务，必须从用户入口核对到实际 runtime 和用户可见结果，不能以旁路 probe 或底层 artifact 代替正式入口验收。
- 区分算法、backend、正式 Operator、最终视觉/产品四层证据；低层通过不能替代高层。
- 分阶段计划中的 Stop / Go 是硬门槛；前一阶段未通过时，不得跨阶段接入或声明完成。
- 阶段状态使用 `PROTOTYPE`、`INTEGRATED`、`VERIFIED`、`ACCEPTED`，不得跨级声明。
- 核心工作流在完成前做独立规格审计，确认正式 runtime、测试入口、文档状态和用户可见行为一致。
- 最终视觉/产品层只能由用户打开批量交付的 `.blend` 后手动验收；收到用户反馈前，最高只能声明 `VERIFIED`，不得声明 `ACCEPTED`。
