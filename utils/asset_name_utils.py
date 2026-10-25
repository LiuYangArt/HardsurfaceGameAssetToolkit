import bpy
import re

from .collection_utils import normalize_unreal_collection_name
from .object_utils import Object


# 统一分隔符、首字母与数字段；name 为用户名称，不猜测单词或替换词义。
def normalize_asset_name(name):
    return normalize_unreal_collection_name(name)


# 去除重复类型前缀；name 为集合或导出资产名，类型由正式导出入口确定。
def strip_asset_prefix(name):
    return re.sub(r"^(?:(?:SM|SK)_)+", "", normalize_asset_name(name), flags=re.IGNORECASE)


# 为同一 Blender 数据域分配唯一名称，避免自动生成含点号的后缀。
# item 为待改名数据；desired 为目标名；items 为同类数据；suffix 为必须放在最后的业务后缀。
def rename_unique(item, desired, items, suffix=""):
    occupied = {other.name.casefold() for other in items if other != item}
    base = desired[:-len(suffix)] if suffix and desired.endswith(suffix) else desired
    candidate = desired
    index = 1
    while candidate.casefold() in occupied:
        candidate = f"{base}_{index:02d}{suffix}"
        index += 1
    item.name = candidate
    return item.name


# 规范直接参与本次操作的 Mesh，并按旧名映射保留每个碰撞体的目标。
# objects 为本次 Mesh 集合；不修改材质、贴图、共享 Mesh 数据名或子集合。
def normalize_mesh_names(objects):
    meshes = [obj for obj in objects if obj.type == "MESH"]
    collisions = [obj for obj in meshes if obj.name.lower().startswith("ucx_") or Object.get_hst_type(obj) == "UCX"]
    models = [obj for obj in meshes if obj not in collisions]
    old_names = {obj: obj.name for obj in models}
    targets = {}
    for collision in collisions:
        tail = collision.name[4:] if collision.name.lower().startswith("ucx_") else collision.name
        matches = [obj for obj, old in old_names.items() if tail.casefold() == old.casefold() or tail.casefold().startswith((old.casefold() + "_", old.casefold() + "."))]
        if matches:
            target = max(matches, key=lambda obj: len(old_names[obj]))
            targets[collision] = (target, tail[len(old_names[target]):].strip("_.") or "01")
        elif len(models) == 1:
            targets[collision] = (models[0], "01")
    for obj in models:
        name = normalize_asset_name(obj.name)
        if name.lower().startswith(("sm_", "sk_")):
            name = name[:2].upper() + "_" + strip_asset_prefix(name)
        rename_unique(obj, name, bpy.data.objects)
    for collision in collisions:
        if collision in targets:
            target, number = targets[collision]
            name = "UCX_" + target.name + "_" + normalize_asset_name(number)
        else:
            name = "UCX_" + normalize_asset_name(re.sub(r"^ucx_", "", collision.name, flags=re.IGNORECASE))
        rename_unique(collision, name, bpy.data.objects)
        Object.mark_hst_type(collision, "UCX")


# 规范资产集合及直接 Mesh；collection 为本次集合，decal 指定是否使用唯一的 _Decal 后缀。
def normalize_collection_asset(collection, decal=False):
    name = strip_asset_prefix(collection.name)
    if decal:
        name = re.sub(r"(?:_Decal)+_([0-9]+)$", r"_\1", name, flags=re.IGNORECASE)
        name = re.sub(r"(?:_Decal)+$", "", name, flags=re.IGNORECASE)
        name += "_Decal"
    rename_unique(collection, name, bpy.data.collections, "_Decal" if decal else "")
    normalize_mesh_names(collection.objects)
    return collection.name


# 生成单一类型前缀的导出名；name 为基名，file_prefix 为用户前缀，asset_type 为 SM 或 SK。
def asset_export_name(name, file_prefix="", asset_type="SM"):
    base = strip_asset_prefix(name)
    prefix = strip_asset_prefix(file_prefix).strip("_") if file_prefix.strip("_") else ""
    if prefix.upper() in {"SM", "SK"}:
        prefix = ""
    separator = "_" if prefix and file_prefix.endswith("_") else ""
    return asset_type + "_" + prefix + separator + base


# 报告无法按结构自动修正的名称；operator 为当前入口，names 为本次名称列表。
def report_name_issues(operator, names):
    invalid = sorted({name for name in names if not re.fullmatch(r"[A-Za-z0-9_]+", name)})
    if invalid:
        operator.report({"WARNING"}, "名称仍含无法自动处理的字符，请手动修改：" + ", ".join(invalid))
