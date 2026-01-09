# 代码重构 Todo List

> Issue #8 - 代码重构  
> 更新时间: 2026-01-09

---

## ✅ 已完成

### Phase 1: utils 包创建

- [x] 创建 `utils/` 包结构（19个模块文件）
- [x] 修复 utils 包导入错误
- [x] 清理 BTMFunctions.py 重复代码

### Phase 1: CommonFunctions.py 迁移

- [x] 第1批：UI/Object/Collection 相关函数
- [x] 第2批：Modifier/VertexColor 相关函数
- [x] 第3批：Import/UV/Mesh 相关函数
- [x] 第4批：Viewport/Scene 相关函数
- [x] 第5批：TD/场景单位 相关函数
- [x] 第6批：misc 工具函数
- [x] 第7批：文件路径函数
- [x] 第8批：BMesh/Material/rotate_quaternion
- [x] 第9批：Transform/Armature 类
- [x] 修复 make_transfer_proxy_mesh 导入缺失
- [x] 修复 mark_convex_edges BMesh 模式错误

**统计**: 删除约1265行 (-35%)

### Phase 2: CommonFunctions.py 业务逻辑整理

- [x] 删除 Object 类重复定义
- [x] 删除 Collection 类重复定义
- [x] 删除 VertexColor/MeshAttributes/Viewport/Outliner/FilePath/Mesh/Modifier 类
- [x] 清理注释掉的废弃代码
- [x] 整理导入语句

**统计**: 删除约1870行 (-78%)

---

## 🔄 进行中

### Phase 3: MeshOps.py 拆分

- [x] 分析函数依赖关系
- [x] 创建 `Operators/` 包结构
- [x] 创建 `cad_ops.py` (5 Operators)
- [x] 创建 `origin_ops.py` (3 Operators)
- [x] 创建 `collection_ops.py` (5 Operators)
- [x] 创建 `uv_ops.py` (3 Operators)
- [x] 创建 `env_ops.py` (4 Operators)
- [x] 创建 `collision_ops.py` (3 Operators)
- [x] 创建 `transform_ops.py` (5 Operators)
- [ ] 创建 `debug_ops.py` (DebugSilhouetteEdges ~500行)
- [ ] 更新 MeshOps.py 删除已迁移代码

**统计**: 新增 7 模块 ~1400 行, 28 Operators

---

## 📋 待办

- [ ] 分析函数依赖关系
- [ ] 创建 `hst_bake_ops.py`
- [ ] 创建 `hst_wearmask_ops.py`
- [ ] 创建 `hst_asset_ops.py`
- [ ] 更新导入引用

### Phase 5: 命名规范化

- [ ] 统一函数命名为 `snake_case`
- [ ] 统一类命名为 `PascalCase`
- [ ] 统一常量命名为 `UPPER_SNAKE_CASE`
- [ ] 更新所有引用

---

## 📊 统计

| 文件 | 原始行数 | 当前行数 | 变化 |
|------|----------|----------|------|
| CommonFunctions.py | 3609 | ~530 | -85% |
| BTMFunctions.py | 421 | ~390 | -7% |
| utils/ | 0 | ~4000 | 19模块 |

---

## 📝 备注

- CommonFunctions.py 现在只保留 FBXExport 类和项目特定业务函数
- 所有工具类（Object, Collection, Mesh 等）已完全迁移至 utils 包
- utils 包作为兼容层，现有代码无需修改仍可正常工作
- 新代码建议直接从 utils 模块导入

