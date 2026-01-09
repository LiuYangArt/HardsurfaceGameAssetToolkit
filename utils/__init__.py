# -*- coding: utf-8 -*-
"""
HardsurfaceGameAssetToolkit Utils Package
=========================================

此包包含所有工具函数，按功能域组织为独立模块。
"""

import bpy

# UI 工具
from .ui_utils import message_box, switch_to_eevee

# 对象操作
from .object_utils import (
    filter_type,
    filter_name,
    clean_user,
    set_visibility,
    rename_meshes,
    Object,
)

# Collection 操作
from .collection_utils import (
    get_collection,
    check_collection_exist,
    Collection,
)

# Modifier 操作
from .modifier_utils import (
    check_modifier_exist,
    remove_modifier,
    get_objects_with_modifier,
    apply_modifiers,
    Modifier,
)

# 顶点色操作
from .vertex_color_utils import (
    cleanup_color_attributes,
    add_vertexcolor_attribute,
    set_active_color_attribute,
    get_vertex_color_from_obj,
    vertexcolor_to_vertices,
    set_object_vertexcolor,
    get_color_data,
    VertexColor,
)

# UV 操作
from .uv_utils import (
    rename_uv_layers,
    add_uv_layers,
    check_uv_layer,
    has_uv_attribute,
    scale_uv,
    uv_unwrap,
    uv_average_scale,
    uv_editor_fit_view,
    culculate_td_areas,
    get_texel_density,
    UV,
)

# 材质操作
from .material_utils import (
    get_materials,
    get_object_material,
    get_object_material_slots,
    get_material_color_texture,
    get_scene_material,
    find_scene_materials,
    import_material,
    Material,
)

# Mesh 几何操作
from .mesh_utils import (
    mark_sharp_edges_by_split_normal,
    are_normals_different,
    mark_sharp_edge_by_angle,
    mark_convex_edges,
    set_edge_bevel_weight_from_sharp,
    Mesh,
)

# 变换操作
from .transform_utils import (
    rotate_quaternion,
    get_selected_rotation_quat,
    Transform,
)

# 导入/导出工具
from .import_utils import (
    import_node_group,
    import_world,
    import_object,
    remove_node,
    make_transfer_proxy_mesh,
)

from .export_utils import (
    FBXExport,
    filter_static_meshes,
    filter_collections_selection,
    filter_collection_types,
)

# 骨骼操作
from .armature_utils import Armature

# 文件/路径操作
from .file_utils import (
    make_dir,
    normalize_path,
    fix_ue_game_path,
    fix_ip_input,
    make_ue_python_script_command,
    write_json,
    read_json_from_file,
    copy_to_clip,
    FilePath,
)

# BMesh 工具
from .bmesh_utils import BMesh

# Viewport 操作
from .viewport_utils import (
    check_screen_area,
    new_screen_area,
    viewport_shading_mode,
    Viewport,
)

# Outliner 操作
from .outliner_utils import Outliner

# Mesh 属性操作
from .mesh_attributes_utils import MeshAttributes

# 其他工具函数
from .misc_utils import (
    set_default_scene_units,
    convert_length_by_scene_unit,
    text_capitalize,
    clean_collection_name,
    rename_alt,
    find_largest_digit,
    reset_transform,
    prep_select_mode,
    restore_select_mode,
    set_collision_object,
    name_remove_digits,
    rename_prop_meshes,
    check_vertex_color,
    filter_collection_by_visibility,
)

# 导出所有符号
__all__ = [
    # UI
    "message_box",
    "switch_to_eevee",
    # Object
    "filter_type",
    "filter_name",
    "clean_user",
    "set_visibility",
    "rename_meshes",
    "Object",
    # Collection
    "get_collection",
    "check_collection_exist",
    "Collection",
    # Modifier
    "check_modifier_exist",
    "remove_modifier",
    "get_objects_with_modifier",
    "apply_modifiers",
    "Modifier",
    # VertexColor
    "cleanup_color_attributes",
    "add_vertexcolor_attribute",
    "set_active_color_attribute",
    "get_vertex_color_from_obj",
    "vertexcolor_to_vertices",
    "set_object_vertexcolor",
    "get_color_data",
    "VertexColor",
    # UV
    "rename_uv_layers",
    "add_uv_layers",
    "check_uv_layer",
    "has_uv_attribute",
    "scale_uv",
    "uv_unwrap",
    "uv_average_scale",
    "uv_editor_fit_view",
    "culculate_td_areas",
    "get_texel_density",
    "UV",
    # Material
    "get_materials",
    "get_object_material",
    "get_object_material_slots",
    "get_material_color_texture",
    "get_scene_material",
    "find_scene_materials",
    "import_material",
    "Material",
    # Mesh
    "mark_sharp_edges_by_split_normal",
    "are_normals_different",
    "mark_sharp_edge_by_angle",
    "mark_convex_edges",
    "set_edge_bevel_weight_from_sharp",
    "Mesh",
    # Transform
    "rotate_quaternion",
    "get_selected_rotation_quat",
    "Transform",
    # Import
    "import_node_group",
    "import_world",
    "import_object",
    "remove_node",
    "make_transfer_proxy_mesh",
    # Export
    "FBXExport",
    "filter_static_meshes",
    "filter_collections_selection",
    "filter_collection_types",
    # Armature
    "Armature",
    # File
    "make_dir",
    "normalize_path",
    "fix_ue_game_path",
    "fix_ip_input",
    "make_ue_python_script_command",
    "write_json",
    "read_json_from_file",
    "copy_to_clip",
    "FilePath",
    # BMesh
    "BMesh",
    # Viewport
    "check_screen_area",
    "new_screen_area",
    "viewport_shading_mode",
    "Viewport",
    # Outliner
    "Outliner",
    # MeshAttributes
    "MeshAttributes",
    # Misc
    "set_default_scene_units",
    "convert_length_by_scene_unit",
    "text_capitalize",
    "clean_collection_name",
    "rename_alt",
    "find_largest_digit",
    "reset_transform",
    "prep_select_mode",
    "restore_select_mode",
    "set_collision_object",
    "name_remove_digits",
    "rename_prop_meshes",
    "check_vertex_color",
    "filter_collection_by_visibility",
]
