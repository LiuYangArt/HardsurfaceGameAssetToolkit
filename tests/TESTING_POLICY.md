# Blender 测试规范

## 目的

让新功能、修复、Blender 升级适配都走同一套可复用的回归规则，避免只靠手动点功能。

## 统一入口

- 运行命令：`python .\tools\run_blender_tests.py`
- 指定 Blender：`python .\tools\run_blender_tests.py --blender "C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe"`
- 结果文件：`F:/CodeProjects/BlenderAddons/HardsurfaceGameAssetToolkit/tests/artifacts/results.json`
- agent skill：`F:/CodeProjects/BlenderAddons/HardsurfaceGameAssetToolkit/agent-skills/hst-blender-regression/SKILL.md`

## 适用范围

以下情况默认要考虑补测试：

- 新增 operator
- 修改已有 operator 主流程
- 修改 collection / object type 标记规则
- 修改 bake / transfer / export / rigging / origin / collision 相关逻辑
- 为 Blender 新版本做兼容修复
- 修复已经出现过的回归 bug

## 默认要求

### 1. 修 bug 要补回归

- 只要是已定位的功能 bug，默认补至少一个回归测试。
- 测试名直接描述症状或功能，不要写成模糊名字。
- 优先覆盖这次真实坏掉的路径，不要只测旁路。

### 2. 新功能要补 smoke test

- 新功能若可 headless 跑，默认补 smoke test。
- smoke test 至少断言：operator 能执行 + 关键结果存在。

### 3. 升级兼容要补断言

- 如果是 Blender API 行为变化导致的问题，测试里要断言最终依赖的行为结果。
- 不要只断言“没有报错”。

## 测试分层

### A. registration smoke

用于检查：
- addon 能 register
- `bpy.types.Scene` 上的关键属性已注册
- `hst.*` operator 都能被找到

### B. workflow smoke

用于检查关键流程可跑通，例如：
- bake collection 标记
- vertex color 设置/复制
- decal project
- quickweight
- origin / transform
- collision / UCX
- export

### C. regression test

用于检查历史 bug 不再复发，例如：
- `_TransferProxy` collection 复用
- AO bake proxy 拓扑必须与 Data Transfer 目标一致
- bake collection 类型兼容旧/新枚举

## 断言规范

优先断言中间状态，不只断言最终 `FINISHED`：

- collection type
- object type
- modifier 是否存在、目标是否正确
- color attribute / mesh attribute 是否存在
- proxy 是否复用、是否命名正确
- topology 是否符合预期
- 导出文件是否生成、是否非空
- parent / transform / bone rename 是否符合预期

避免：

- 只检查 operator 返回 `FINISHED`
- 只打印日志，不做断言
- 依赖 viewport / popup / 手动交互

## 新增测试时的实现规则

- 测试统一加在：`F:/CodeProjects/BlenderAddons/HardsurfaceGameAssetToolkit/tests/blender_test_driver.py`
- 保持 headless 可运行。
- 复用现有 helper：`make_collection`、`make_test_mesh`、`select_objects` 等。
- 每个 case 尽量自包含，依赖 `reset_scene()` 后的空场景。
- 新 case 加到 `main()` 的 `context.run_case(...)` 列表。
- 名称格式统一：`xxx_smoke` 或 `xxx_regression`。
- 失败信息要直接指出坏在哪里。

## 不建议自动化的内容

以下内容默认不要优先放进回归，除非已证明 headless 稳定：

- 强依赖 viewport area / local view / UI popup 的流程
- 强依赖外部程序或人工确认的流程
- 明显需要交互式观察效果的纯视觉检查

这类功能可以先补：
- 更底层的 helper 测试
- 可机器读取的中间产物断言
- 明确的失败日志或导出物

## 提交流程要求

功能改动完成后默认顺序：

1. 改代码
2. 补/改回归测试
3. 运行最小必要验证
4. 若改动影响核心流程，运行完整：`python .\tools\run_blender_tests.py`
5. 更新 `tests/README.md` 中的覆盖清单（如果新增了测试类别）

## 文档入口

- 测试说明：`F:/CodeProjects/BlenderAddons/HardsurfaceGameAssetToolkit/tests/README.md`
- 测试规范：`F:/CodeProjects/BlenderAddons/HardsurfaceGameAssetToolkit/tests/TESTING_POLICY.md`
- agent skill：`F:/CodeProjects/BlenderAddons/HardsurfaceGameAssetToolkit/agent-skills/hst-blender-regression/SKILL.md`
