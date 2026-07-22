# Blender Test Fixtures

本目录中的 `.blend` 是随仓库分发的 immutable test input。测试和 probe 必须从 repository root 或脚本自身位置解析路径，不得依赖 Desktop、盘符、用户名或其他机器专属绝对路径。

## Feature Chamfer 产品矩阵

| Fixture | SHA-256 | Matrix 对象 |
|---|---|---|
| `feature-chamfer-product-simple.blend` | `1CBAB4C83C4D9F77BD2B0799257953AAEC32AA416994A1D8810425F3C2B94D8C` | `Extruded.002`, `Solid 44` |
| `feature-chamfer-product-tricky.blend` | `C7F57A54837A04F7E52B535BB47AF0ABEB05FCA4193DAC714FB3667EFB426F02` | `Solid.004`, `Solid.016` |
| `feature-chamfer-product-tricky-b.blend` | `A4C121B6BBBFFF58B94C3B7ED11BD82FE59C88A92569389FD27593ED65BE9A35` | `Extruded.003`, `Extruded.002` |
| `feature-chamfer-topology-defect-mixed.blend` | `80DA3EE4144BA83CAB4E9BED980C8829D846369F22A694ABFE1AA513C3A3D1B8` | `Extruded.002` |

`pipe-chamfer-test-tricky_b.blend` 是已有专项回归 fixture，内容与上表的 `feature-chamfer-product-tricky-b.blend` 不同；不要互相覆盖。

## 使用规则

- 只读打开 fixture；生成结果写入 `tests/artifacts/`。
- runner 中使用 `Path(__file__).resolve()` 推导 repository root。
- Windows 与 macOS 共用同一 fixture 文件和 hash。
- 若 fixture 必须更新，新增文件或显式更新 hash、矩阵基线和变更原因，不能静默覆盖。

对应推进计划：`docs/plan/2026-07-22-feature-chamfer-generalization-roadmap.md`。
