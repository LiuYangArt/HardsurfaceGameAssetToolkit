# HardsurfaceGameAssetToolkit

这是一个Blender插件，适配blender 5.0+ 
- 使用blender 5.0+ 的api

## 语言风格
- 回复简短、准确、去重；以易读为先。

## 工作方式
- 先定位，再读取；避免直接通读大文件或大日志。
- 先用搜索或文件列表缩小范围，再按需读取相关片段。
- 修改前先查找并复用项目内已有模式；不要凭空发明新结构。
- 优先做最小充分修改；非当前任务不要顺手重构。


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

## 验证
- 完成修改前，优先运行最小必要的验证命令；无法验证时明确说明原因。
