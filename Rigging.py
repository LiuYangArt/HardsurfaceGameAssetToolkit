import bpy
import re

from .Functions.CommonFunctions import Collection, Object, filter_type
from mathutils import Vector


def setup_ue_rig_scene():
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.length_unit = 'METERS'
    scene.unit_settings.scale_length = 0.01
    bpy.context.space_data.clip_start = 1
    bpy.context.space_data.clip_end = 10000
    bpy.context.space_data.shading.color_type = 'OBJECT'
    bpy.context.space_data.shading.light = 'MATCAP'

def set_ue_armature_display(object):
    """
    Set the display type of armature objects to WIRE and show axes.
    :param objects: List of objects to modify.
    """

    if object.type == 'ARMATURE':
        object.data.display_type = 'WIRE'
        object.show_in_front = True
        object.data.show_axes = True
        object.data.relation_line_position = 'HEAD'

        return object
    else:
        return None


class SetSceneUnitForUnrealRigOperator(bpy.types.Operator):
    bl_idname = "hst.set_scene_unit_for_unreal_rig"
    bl_label = "Set Scene Unit For Unreal Rig"
    bl_description = "设置场景单位以便骨骼fbx导出到UE时单位正确"

    def execute(self, context):


        setup_ue_rig_scene()

        return {"FINISHED"}
    
def find_parent_empty_type(obj):
    """
    Recursively find the parent of type 'EMPTY' for the given object.
    :param obj: The Blender object to start from.
    :return: The parent EMPTY object if found, else None.
    """
    parent = obj.parent
    while parent is not None:
        if parent.type == "EMPTY":
            return parent
        parent = parent.parent
    return None
    

class CleanupUESKMOperator(bpy.types.Operator):
    bl_idname = "hst.cleanup_ue_skm"
    bl_label = "Cleanup UE SKM"

    def execute(self, context):
        setup_ue_rig_scene()
        selected_objects = bpy.context.selected_objects
        skeleton_objs=[]
        amature_objs = []
        #检查是否是UE骨骼模型
        for obj in selected_objects:
            if obj.type == "EMPTY":
                if obj.children:
                    for child in obj.children:
                        if child.type == "ARMATURE":
                            if obj not in skeleton_objs:
                                skeleton_objs.append(obj)
                                break
            elif obj.type == "ARMATURE":
                parent=find_parent_empty_type(obj)
                if parent is not None:
                    if parent not in skeleton_objs:
                        skeleton_objs.append(parent)
            elif obj.type == "MESH":
                parent=find_parent_empty_type(obj)
                if parent is not None:
                    if parent.children:
                        for child in parent.children:
                            if child.type == "ARMATURE":
                                if parent not in skeleton_objs:
                                    skeleton_objs.append(parent)
                                    break
        for obj in skeleton_objs:
            if obj.scale == Vector((0.0100, 0.0100, 0.0100)): #UE骨骼默认导入的scale， 用于二次确认
                bpy.ops.object.select_all(action='DESELECT')
                for child in obj.children:
                    child.select_set(True)
                    if child.type == "ARMATURE":
                        if child not in amature_objs:
                            amature_objs.append(child)
                bpy.ops.object.parent_clear(type='CLEAR')
                bpy.data.objects.remove(obj, do_unlink=True)
        for armature in amature_objs:
            set_ue_armature_display(armature)
            

        return {"FINISHED"}



class QuickWeightOperator(bpy.types.Operator):
    bl_idname = "hst.quickweight"
    bl_label = "QuickWeight"
    bl_description = "将选中模型的所有顶点权重刷到当前激活的骨骼上"

    @classmethod
    def poll(cls, context):
        """
        检查是否可以执行该操作。
        """
        active_obj = context.active_object
        # 1. 激活物体必须是骨架
        if not active_obj or active_obj.type != 'ARMATURE':
            return False

        # 2. 必须处于姿态模式或编辑模式
        if active_obj.mode not in {'POSE', 'EDIT'}:
            return False
        
        # 3. 必须有一个激活的骨骼 (姿态骨骼或编辑骨骼)
        if active_obj.mode == 'POSE' and not context.active_pose_bone:
            return False
        if active_obj.mode == 'EDIT' and not context.active_bone:
            return False

        # 4. 必须至少选择一个网格物体
        selected_meshes = [obj for obj in context.selected_objects if obj.type == 'MESH']
        if not selected_meshes:
            return False
            
        return True

    def execute(self, context):
        active_obj = context.active_object
        mesh_objects = [obj for obj in context.selected_objects if obj.type == 'MESH']
        
        if not mesh_objects:
            self.report({'WARNING'}, "没有选中任何网格物体")
            return {'CANCELLED'}

        bone_name = None
        # 2. 根据模式获取骨骼名称
        if active_obj.mode == 'POSE':
            bone_name = context.active_pose_bone.name
        elif active_obj.mode == 'EDIT':
            bone_name = context.active_bone.name

        if not bone_name:
             self.report({'WARNING'}, "没有找到激活的骨骼")
             return {'CANCELLED'}

        for mesh_obj in mesh_objects:
            # 检查是否已存在指向此骨架的修改器
            has_modifier = False
            for mod in mesh_obj.modifiers:
                if mod.type == 'ARMATURE' and mod.object == active_obj:
                    has_modifier = True
                    break
            
            # 如果不存在，则添加一个新的
            if not has_modifier:
                mod = mesh_obj.modifiers.new(name="Armature", type='ARMATURE')
                mod.object = active_obj
                self.report({'INFO'}, f"为 {mesh_obj.name} 添加了 Armature Modifier")

            # 检查物体中是否已存在同名顶点组
            vertex_group = mesh_obj.vertex_groups.get(bone_name)
            if not vertex_group:
                # 如果不存在，则创建新顶点组
                vertex_group = mesh_obj.vertex_groups.new(name=bone_name)
            
            # 将网格的所有顶点以1.0的权重指定给该顶点组
            all_vertex_indices = [v.index for v in mesh_obj.data.vertices]
            
            vertex_group.add(all_vertex_indices, 1.0, 'REPLACE')

        self.report({'INFO'}, f"权重已成功赋予到骨骼: {bone_name}")
            
        return {"FINISHED"}



class RenameBonesOperator(bpy.types.Operator):
    bl_idname = "hst.rename_bones"
    bl_label = "Rename Bones"

    def execute(self, context):
        """
        批量重命名选中骨架对象（Armature）中的所有骨骼：
        1. 所有骨骼名称转为小写。
        2. 对于有 .001、.002 等数字后缀的骨骼名，改为 _01、_02 这种下划线+两位数字的格式。
        :param context: Blender上下文对象。
        :return: 操作结果。
        """
        selected_objects = context.selected_objects
        armature_objs = [obj for obj in selected_objects if obj.type == 'ARMATURE']
        if not armature_objs:
            self.report({'WARNING'}, "未选中任何骨架对象（Armature）")
            return {'CANCELLED'}

        for armature in armature_objs:
            # 记录原始模式
            original_mode = armature.mode
            # 若不在编辑模式，切换到编辑模式
            if original_mode != 'EDIT':
                bpy.ops.object.mode_set(mode='EDIT')
            for bone in armature.data.edit_bones:
                name = bone.name
                # 名称转小写
                new_name = name.lower()
                # 替换 .数字 后缀为 _数字，数字补齐两位
                match = re.search(r"\.(\d+)$", new_name)
                if match:
                    num = int(match.group(1))
                    new_name = re.sub(r"\.(\d+)$", f"_{num:02d}", new_name)
                bone.name = new_name
            # 操作完成后切回原模式
            if original_mode != 'EDIT':
                bpy.ops.object.mode_set(mode=original_mode)
        self.report({'INFO'}, "骨骼重命名完成")
        return {"FINISHED"}


class RenameTreeBonesOperator(bpy.types.Operator):
    bl_idname = "hst.rename_tree_bones"
    bl_label = "Rename Tree Bones"
    bl_description = "批量重命名选中有父子关系的骨骼，按树结构编号"

    new_name: bpy.props.StringProperty(
        name="New Bone Name Prefix",
        description="输入新的骨骼基础名称",
        default="bone"
    )

    def invoke(self, context, event):
        """
        弹出对话框，获取用户输入的新骨骼名。
        """
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        """
        在骨骼编辑模式下，选中多个有父子关系的骨骼后，
        将其按父子树结构递归编号并重命名为 new_name_01、new_name_02 等。
        """
        armature = context.active_object
        if not armature or armature.type != 'ARMATURE' or armature.mode != 'EDIT':
            self.report({'WARNING'}, "请在骨骼编辑模式下选中骨骼")
            return {'CANCELLED'}

        selected_bones = list(context.selected_editable_bones)
        if not selected_bones:
            self.report({'WARNING'}, "未选中任何骨骼")
            return {'CANCELLED'}

        # 构建骨骼名到骨骼对象的映射，便于查找
        bone_map = {bone.name: bone for bone in selected_bones}

        # 找到所有选中骨骼中的根骨骼（父骨骼未被选中）
        root_bones = [bone for bone in selected_bones if not bone.parent or bone.parent.name not in bone_map]

        # 递归重命名
        def rename_bone_tree(bone, prefix, index):
            """
            递归重命名骨骼树。
            :param bone: 当前骨骼对象
            :param prefix: 新名字前缀
            :param index: 当前编号（int）
            :return: 当前编号递增值
            """
            new_bone_name = f"{prefix}_{index:02d}"
            bone.name = new_bone_name
            child_index = 1
            for child in bone.children:
                if child in selected_bones:
                    index = rename_bone_tree(child, prefix, index + 1)
                    child_index += 1
            return index

        current_index = 1
        for root in root_bones:
            current_index = rename_bone_tree(root, self.new_name, current_index)

        self.report({'INFO'}, f"已重命名骨骼为 {self.new_name}_XX 格式")
        return {"FINISHED"}



class BoneDisplaySettingsOperator(bpy.types.Operator):
    bl_idname = "hst.bone_display_settings"
    bl_label = "BoneDisplaySettings"

    def execute(self, context):
        for obj in context.selected_objects:
            if obj.type == 'ARMATURE':
                # 设置骨架显示类型为八面体
                obj.data.display_type = 'OCTAHEDRAL'
                # 显示骨骼名称
                obj.data.show_names = True
                # 设置关系线位置为头部
                obj.data.relation_line_position = 'HEAD'
                # 前置显示
                obj.show_in_front = True
                obj.data.show_axes = True
                obj.data.axes_position = 0  # 设置轴位置为0（默认位置）
        # bpy.context.object.data.show_axes = True
        # bpy.context.object.data.axes_position = 0
        # bpy.context.object.data.display_type = 'OCTAHEDRAL'
        # bpy.context.object.data.show_names = True
        # bpy.context.object.data.relation_line_position = 'HEAD'
        # bpy.context.object.show_in_front = True


        return {"FINISHED"}






#TODO: Rename Bones

# class MarkSKMCollectionOperator(bpy.types.Operator):
#     bl_idname = "hst.mark_skm_collection"
#     bl_label = "Mark SKM Collection"
#     bl_description = "Mark selected collection as SKM Collection"

#     def execute(self, context):
#         selected_objs= context.selected_objects
#         selected_colls = Collection.get_selected()
#         if selected_colls is not None:
#             for coll in selected_colls:
#                 Collection.mark_hst_type(coll, "RIG")
#                 coll_objs=coll.all_objects
#                 meshes= filter_type(coll_objs, "MESH")
#                 for mesh in meshes:
#                     Object.mark_hst_type(mesh, "SKM")

#         return {"FINISHED"}


