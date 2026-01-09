# 代码重构进度报告

> 更新时间: 2026-01-09

## 概述

本项目正在进行代码重构（Issue #8），目标是将散落在各处的工具函数整合到统一的 `utils` 包中，减少重复代码，提高可维护性。

---

## 当前进度

### 统计数据

| 指标 | 原值 | 当前值 | 变化 |
|------|------|--------|------|
| **CommonFunctions.py** | 3609 行 | ~2430 行 | -1265 行 (-35%) |
| **BTMFunctions.py** | 421 行 | ~390 行 | -30 行 |
| **utils 包** | 0 | ~4000 行 | 19 模块 |
| **Git 提交** | - | 15 次 | - |

### 已完成工作

- [x] 创建 `utils/` 包结构（19个模块文件）
- [x] 修复 utils 包导入错误
- [x] 清理 BTMFunctions.py 重复代码
- [x] CommonFunctions.py 迁移（9批，删除约1265行）

### utils 包模块

| 模块 | 功能 |
|------|------|
| `ui_utils.py` | 消息框、渲染引擎切换 |
| `object_utils.py` | 对象筛选、重命名、可见性 |
| `collection_utils.py` | Collection 操作 |
| `modifier_utils.py` | Modifier 操作 |
| `vertex_color_utils.py` | 顶点色操作 |
| `uv_utils.py` | UV 操作 |
| `material_utils.py` | 材质操作 |
| `mesh_utils.py` | Mesh 几何操作 |
| `transform_utils.py` | 变换操作 |
| `import_utils.py` | 资源导入 |
| `export_utils.py` | 导出操作 |
| `bmesh_utils.py` | BMesh 工具 |
| `viewport_utils.py` | Viewport 操作 |
| `outliner_utils.py` | Outliner 操作 |
| `mesh_attributes_utils.py` | Mesh 属性操作 |
| `file_utils.py` | 文件/路径操作 |
| `armature_utils.py` | Armature 操作 |
| `misc_utils.py` | 杂项工具 |

---

## 后续计划

### Phase 2: CommonFunctions.py 剩余工作

CommonFunctions.py 中剩余的代码（约2430行）主要是项目特定的业务逻辑，暂不迁移：

- `Object` 类：mark_hst_type, filter_hst_type 等
- `Collection` 类：项目特定的 Collection 筛选逻辑
- `FBXExport` 类：导出逻辑
- `UV` 类：UV 显示逻辑
- 各种 filter 函数：filter_collection_by_visibility 等

### Phase 3: MeshOps.py 拆分（暂停）

MeshOps.py 包含约2077行，可拆分为：

- `mesh_clean_ops.py`: 顶点清理、重复顶点合并
- `mesh_uv_ops.py`: UV 相关 Operator
- `mesh_origin_ops.py`: 原点设置 Operator
- `mesh_cad_ops.py`: CAD 网格准备

### Phase 4: HSTOps.py 拆分（暂停）

HSTOps.py 包含约1047行，可拆分为：

- `hst_bake_ops.py`: Bake 相关 Operator
- `hst_wearmask_ops.py`: Wearmask 相关 Operator
- `hst_asset_ops.py`: Asset 管理 Operator

### Phase 5: 命名规范化

统一函数和类命名风格：

| 风格 | 示例 |
|------|------|
| 函数 | `snake_case` |
| 类 | `PascalCase` |
| 常量 | `UPPER_SNAKE_CASE` |

---

## Git 提交历史（最近）

```
498b6b5 refactor: CommonFunctions.py 第九批迁移
3d6340b refactor: CommonFunctions.py 第八批迁移
51e254b refactor: 删除 reset_transform 重复定义
ee5b95d refactor: CommonFunctions.py 第六批迁移
1e737b5 fix: 修复 mark_convex_edges 中的 BMesh 模式错误
6ab3254 fix: 修复 make_transfer_proxy_mesh 导入缺失
9ae4109 refactor: CommonFunctions.py 第五批迁移
c29ac3e refactor: CommonFunctions.py 第四批迁移
cb5d690 refactor: CommonFunctions.py 第三批迁移
```

---

## 如何使用 utils 包

```python
# 新代码：直接从 utils 模块导入
from .utils.object_utils import Object, filter_type
from .utils.collection_utils import Collection
from .utils.modifier_utils import Modifier, apply_modifiers

# 现有代码：仍可通过 CommonFunctions 导入（兼容层）
from .Functions.CommonFunctions import *
```
