# -*- coding: utf-8 -*-
"""Marmoset Toolbag 5 bake scene bridge helpers."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

import bpy

from ..const import HIGHB_SUFFIX, HIGH_SUFFIX, LOWB_SUFFIX, LOW_SUFFIX
from .collection_utils import Collection

TOOLBAG_EXE_NAME = "Toolbag.exe"
DEFAULT_BAKE_SUBDIR = Path("Bake") / "Marmoset"

VERTEX_COLOR_MASK_CHANNELS = {
    "NONE": 0,
    "R": 1,
    "G": 2,
    "B": 3,
    "A": 4,
}


@dataclass(frozen=True)
class MarmosetBakePair:
    base_name: str
    low_collection: bpy.types.Collection
    high_collection: bpy.types.Collection


@dataclass(frozen=True)
class MarmosetBakePaths:
    bake_root: Path
    fbx_dir: Path
    texture_dir: Path
    loader_path: Path
    scene_path: Path


# 生成 bake collection 的匹配 key。
# 参数:
#     collection_name: Blender Collection 名称。
# 返回:
#     去除 Blender 自动数字后缀和 _low / _high 后缀后的 base name。
def make_bake_base_name(collection_name: str) -> str:
    name = re.sub(r"\.\d{3}$", "", collection_name)
    for suffix in (LOW_SUFFIX, HIGH_SUFFIX, LOWB_SUFFIX, HIGHB_SUFFIX):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


# 收集当前 scene collection 树中的所有 Collection。
# 参数:
#     root_collection: 当前 Scene 的根 Collection。
# 返回:
#     包含 root 与所有子 Collection 的列表。
def collect_scene_collections(root_collection: bpy.types.Collection) -> list[bpy.types.Collection]:
    collections = [root_collection]
    for child_collection in root_collection.children:
        collections.extend(collect_scene_collections(child_collection))
    return collections


# 按 BAKE_LOW / BAKE_HIGH 标记收集并配对 Collection。
# 参数:
#     scene: 当前 Blender Scene。
# 返回:
#     MarmosetBakePair 列表。
# 异常:
#     ValueError: 缺少 low / high 或出现重复 base name 时抛出明确错误。
def collect_marmoset_bake_pairs(scene: bpy.types.Scene) -> list[MarmosetBakePair]:
    collections = collect_scene_collections(scene.collection)
    low_collections = Collection.filter_hst_type(collections, "BAKE_LOW")
    high_collections = Collection.filter_hst_type(collections, "BAKE_HIGH")

    low_by_base = _index_unique_collections(low_collections, "low")
    high_by_base = _index_unique_collections(high_collections, "high")
    if not low_by_base and not high_by_base:
        raise ValueError("No BAKE_LOW / BAKE_HIGH collections found")

    missing_high = sorted(set(low_by_base) - set(high_by_base))
    missing_low = sorted(set(high_by_base) - set(low_by_base))
    errors = []
    if missing_high:
        errors.append("Missing high collection for: " + ", ".join(missing_high))
    if missing_low:
        errors.append("Missing low collection for: " + ", ".join(missing_low))
    if errors:
        raise ValueError("; ".join(errors))

    return [
        MarmosetBakePair(base_name, low_by_base[base_name], high_by_base[base_name])
        for base_name in sorted(low_by_base)
    ]


# 生成不重复的 base name -> Collection 字典。
# 参数:
#     collections: 已按 HST 类型过滤的 Collection 列表。
#     role_name: 错误提示中的角色名，例如 low / high。
# 返回:
#     base name 到 Collection 的映射。
def _index_unique_collections(collections, role_name: str) -> dict[str, bpy.types.Collection]:
    indexed = {}
    duplicates = []
    for collection in collections:
        base_name = make_bake_base_name(collection.name)
        if base_name in indexed:
            duplicates.append(base_name)
        indexed[base_name] = collection
    if duplicates:
        raise ValueError(f"Duplicate {role_name} bake collection base name: {', '.join(sorted(set(duplicates)))}")
    return indexed


# 解析 Toolbag 可执行文件路径，允许用户传安装目录。
# 参数:
#     toolbag_path: 用户偏好设置中的文件或目录路径。
# 返回:
#     规范化后的 Toolbag.exe Path。
def resolve_toolbag_executable(toolbag_path: str) -> Path:
    path = Path(bpy.path.abspath(toolbag_path)).expanduser()
    if path.is_dir():
        path = path / TOOLBAG_EXE_NAME
    return path


# 计算 Marmoset bake bridge 的输出路径。
# 参数:
#     blend_file_path: 当前 .blend 文件路径，可为空。
#     artifact_root: 测试或调用方指定的输出根目录。
# 返回:
#     MarmosetBakePaths。
def make_marmoset_bake_paths(blend_file_path: str, artifact_root: str | None = None) -> MarmosetBakePaths:
    if artifact_root:
        bake_root = Path(bpy.path.abspath(artifact_root))
        blend_stem = Path(blend_file_path).stem if blend_file_path else "untitled"
    else:
        if not blend_file_path:
            raise ValueError("Save the .blend file or set an artifact root before sending to Marmoset")
        blend_path = Path(bpy.path.abspath(blend_file_path))
        bake_root = blend_path.parent / DEFAULT_BAKE_SUBDIR
        blend_stem = blend_path.stem

    fbx_dir = bake_root / "FBX"
    texture_dir = bake_root / "Textures"
    loader_path = bake_root / "loader.py"
    scene_path = bake_root / f"{blend_stem}_bake.tbscene"
    return MarmosetBakePaths(bake_root, fbx_dir, texture_dir, loader_path, scene_path)


# 导出单个 bake collection FBX，显式保留 vertex color。
# 参数:
#     collection: 目标 bake Collection。
#     file_path: FBX 输出路径。
def export_bake_collection_fbx(collection: bpy.types.Collection, file_path: Path) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    original_selection = bpy.context.selected_objects.copy()
    original_active = bpy.context.active_object
    hidden_objects = []

    try:
        bpy.ops.object.select_all(action="DESELECT")
        export_objects = [obj for obj in collection.all_objects if obj.type == "MESH"]
        if not export_objects:
            raise ValueError(f"Bake collection has no mesh objects: {collection.name}")

        for obj in export_objects:
            if obj.hide_get():
                hidden_objects.append(obj)
                obj.hide_set(False)
            obj.select_set(True)
        bpy.context.view_layer.objects.active = export_objects[0]

        bpy.ops.export_scene.fbx(
            filepath=str(file_path),
            use_selection=True,
            use_active_collection=False,
            use_visible=False,
            axis_forward="-Z",
            axis_up="Y",
            global_scale=1.0,
            apply_unit_scale=True,
            apply_scale_options="FBX_SCALE_NONE",
            colors_type="LINEAR",
            object_types={"MESH"},
            use_mesh_modifiers=True,
            mesh_smooth_type="FACE",
            use_triangles=True,
            use_tspace=True,
            bake_space_transform=True,
            path_mode="AUTO",
            embed_textures=False,
            batch_mode="OFF",
            use_metadata=False,
            use_custom_props=False,
            bake_anim=False,
        )
    finally:
        for obj in hidden_objects:
            obj.hide_set(True)
        bpy.ops.object.select_all(action="DESELECT")
        for obj in original_selection:
            if obj.name in bpy.context.scene.objects:
                obj.select_set(True)
        if original_active and original_active.name in bpy.context.scene.objects:
            bpy.context.view_layer.objects.active = original_active


# 导出所有配对 Collection 到 FBX。
# 参数:
#     pairs: bake 配对列表。
#     paths: Marmoset 输出路径集合。
# 返回:
#     loader 脚本使用的 group 字典列表。
def export_marmoset_bake_fbx(pairs: list[MarmosetBakePair], paths: MarmosetBakePaths) -> list[dict]:
    paths.fbx_dir.mkdir(parents=True, exist_ok=True)
    groups = []
    for pair in pairs:
        low_path = paths.fbx_dir / f"{pair.base_name}_low.fbx"
        high_path = paths.fbx_dir / f"{pair.base_name}_high.fbx"
        export_bake_collection_fbx(pair.low_collection, low_path)
        export_bake_collection_fbx(pair.high_collection, high_path)
        groups.append(
            {
                "base_name": pair.base_name,
                "low_fbx": str(low_path),
                "high_fbx": str(high_path),
                "texture_path": str(paths.texture_dir / pair.base_name),
            }
        )
    return groups


# 生成 Toolbag loader.py 文本。
# 参数:
#     groups: bake group 路径与名称配置。
#     scene_path: Toolbag scene 保存路径。
#     texture_size: 输出贴图尺寸。
#     output_bits: 输出 bit depth。
#     output_samples: bake samples。
#     bevel_width_mm: Toolbag Bevel shader 最大宽度。
#     bevel_samples: Toolbag Bevel shader samples。
#     vertex_color_mask: 0=None, 1=R, 2=G, 3=B, 4=A。
# 返回:
#     可由 Toolbag.exe 执行的 Python 脚本文本。
def build_marmoset_loader_script(
    groups: list[dict],
    scene_path: Path,
    texture_size: int,
    output_bits: int,
    output_samples: int,
    bevel_width_mm: float,
    bevel_samples: int,
    vertex_color_mask: int,
) -> str:
    config = {
        "scene_path": str(scene_path),
        "texture_size": int(texture_size),
        "output_bits": int(output_bits),
        "output_samples": int(output_samples),
        "bevel_width_mm": float(bevel_width_mm),
        "bevel_samples": int(bevel_samples),
        "vertex_color_mask": int(vertex_color_mask),
        "groups": groups,
    }
    config_json = json.dumps(config, indent=2, ensure_ascii=False)
    return f'''# Auto-generated by HardsurfaceGameAssetToolkit.
import os
import traceback

import mset

CONFIG = {config_json}


def iter_children_recursive(scene_object):
    for child in scene_object.getChildren():
        yield child
        yield from iter_children_recursive(child)



def setup_bevel_material(target_parent, material_name):
    material = mset.Material(material_name)
    material.setSubroutine("surface", "Bevel")
    surface = material.getSubroutine("surface")
    surface.setField("Bevel Width (mm)", CONFIG["bevel_width_mm"])
    surface.setField("Bevel Angle", 90.0)
    surface.setField("Bevel Samples", CONFIG["bevel_samples"])
    surface.setField("Bevel Hard Edges", True)
    surface.setField("Bevel Same Surface Only", False)
    surface.setField("Vertex Color Mask", CONFIG["vertex_color_mask"])
    material.assign(target_parent, True)
    return material


def setup_scene():
    mset.newScene()
    baker = mset.BakerObject()
    baker.outputWidth = int(CONFIG["texture_size"])
    baker.outputHeight = int(CONFIG["texture_size"])
    baker.outputBits = int(CONFIG["output_bits"])
    baker.outputSamples = int(CONFIG["output_samples"])
    baker.outputPath = os.path.join(os.path.dirname(CONFIG["scene_path"]), "Textures")
    os.makedirs(baker.outputPath, exist_ok=True)

    for group_config in CONFIG["groups"]:
        group = baker.addGroup(group_config["base_name"])
        high_parent = group.findInChildren("High")
        low_parent = group.findInChildren("Low")
        if high_parent is None or low_parent is None:
            raise RuntimeError("Toolbag did not create High / Low targets for " + group_config["base_name"])

        baker.importModel(group_config["low_fbx"])
        baker.importModel(group_config["high_fbx"])
        for child in iter_children_recursive(low_parent):
            child.visible = True
        for child in iter_children_recursive(high_parent):
            child.visible = True
        setup_bevel_material(high_parent, "HST_Bevel_" + group_config["base_name"])

    os.makedirs(os.path.dirname(CONFIG["scene_path"]), exist_ok=True)
    mset.saveScene(CONFIG["scene_path"])


try:
    setup_scene()
except Exception:
    traceback.print_exc()
    raise
'''


# 写入 Toolbag loader.py。
# 参数:
#     loader_path: 输出脚本路径。
#     script_text: loader 脚本文本。
def write_loader_script(loader_path: Path, script_text: str) -> None:
    loader_path.parent.mkdir(parents=True, exist_ok=True)
    loader_path.write_text(script_text, encoding="utf-8")


# 将 UI channel 值转换为 Toolbag int mask。
# 参数:
#     channel: NONE / R / G / B / A。
# 返回:
#     Toolbag Bevel shader Vertex Color Mask 数值。
def resolve_vertex_color_mask(channel: str) -> int:
    try:
        return VERTEX_COLOR_MASK_CHANNELS[channel]
    except KeyError as error:
        raise ValueError(f"Unsupported vertex color mask channel: {channel}") from error
