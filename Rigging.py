import bpy
import re

from .Functions.CommonFunctions import Collection, Object, filter_type
from mathutils import Vector


def setup_ue_rig_scene():
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.length_unit = 'CENTIMETERS'
    scene.unit_settings.scale_length = 1
    # bpy.context.space_data.clip_start = 1
    # bpy.context.space_data.clip_end = 10000
    bpy.context.space_data.shading.color_type = 'OBJECT'
    bpy.context.space_data.shading.light = 'MATCAP'
    bpy.context.space_data.overlay.show_text = True


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
    
def set_blender_armature_display(object,display_type='OCTAHEDRAL'):
    """
    Set the display type of armature objects to WIRE and show axes.
    :param objects: List of objects to modify.
    """
    

    if object.type == 'ARMATURE':
        # 设置骨架显示类型为线框
        object.data.display_type = display_type
        object.data.show_names = True

        # 显示骨架轴线
        object.data.show_axes = True
        # 前置显示
        object.show_in_front = True
        # 关系线位置为头部
        object.data.relation_line_position = 'HEAD'


class HST_OT_SetSceneUnitForUnrealRig(bpy.types.Operator):
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
    

class HST_OT_CleanupUESKM(bpy.types.Operator):
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



class HST_OT_QuickWeight(bpy.types.Operator):
    bl_idname = "hst.quickweight"
    bl_label = "QuickWeight"
    bl_description = "将选中模型的所有顶点权重刷到当前激活的骨骼上，或仅刷Edit模式下选中的顶点"
    bl_options = {'REGISTER', 'UNDO'}

    mode: bpy.props.EnumProperty(
        name="Weight Mode",
        description="选择权重分配方式",
        items=[
            ('ALL_VERTS', "Object", "对选中的整个Mesh填充权重"),
            ('EDIT_SELECTED_VERTS', "Selected Verts", "仅将Edit模式下选中的顶点填充权重")
        ],
        default='ALL_VERTS'
    )

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

            if self.mode == 'ALL_VERTS':
                # 所有顶点赋权重
                all_vertex_indices = [v.index for v in mesh_obj.data.vertices]
                vertex_group.add(all_vertex_indices, 1.0, 'REPLACE')
            elif self.mode == 'EDIT_SELECTED_VERTS':
                # 仅Edit模式下选中的顶点赋权重，未选中顶点移除
                selected_indices = [v.index for v in mesh_obj.data.vertices if v.select]
                unselected_indices = [v.index for v in mesh_obj.data.vertices if not v.select]
                if selected_indices:
                    vertex_group.add(selected_indices, 1.0, 'REPLACE')
                if unselected_indices:
                    vertex_group.remove(unselected_indices)

        self.report({'INFO'}, f"权重已成功赋予到骨骼: {bone_name}")
            
        return {"FINISHED"}



class HST_OT_RenameBones(bpy.types.Operator):
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


class HST_OT_RenameTreeBones(bpy.types.Operator):
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



class HST_OT_BoneDisplaySettings(bpy.types.Operator):
    bl_idname = "hst.bone_display_settings"
    bl_label = "Bone Display Settings"
    bl_options = {"REGISTER", "UNDO"}

    # 添加属性用于invoke弹窗
    display_type: bpy.props.EnumProperty(
        name="Bone Display Type",
        description="选择骨骼显示类型",
        items=[
            ('OCTAHEDRAL', "Octahedral", "八面体显示"),
            ('ENVELOPE', "Envelope", "包络显示"),
            ('WIRE', "Wire", "线框显示"),
            ('STICK', "Stick", "棒状显示"),
            ('BBONE', "B-Bone", "B样条骨骼显示")

        ],
        default="OCTAHEDRAL",)
    def execute(self, context):
            selected_objects = context.selected_objects
            for obj in selected_objects:
                set_blender_armature_display(obj,display_type=self.display_type)
            self.report({'INFO'}, "已设置选中骨架的显示设置")
            return {"FINISHED"}




class HST_OT_SetSocketBoneForUE(bpy.types.Operator):
    bl_idname = "hst.set_socket_bone_for_ue"
    bl_label = "Set Socket Bone For UE"
    bl_options = {"REGISTER", "UNDO"}


    socket_type: bpy.props.EnumProperty(
        name="Socket Type",
        description="Socket 类型",
        items=[
            ('ATTACH', "Attach", "Attach Component"),
            ('SPAWN', "SPAWN", "Spawn Actor")

        ],
        default="ATTACH",)
    
    def execute(self, context):
        armature = context.active_object
        if not armature or armature.type != 'ARMATURE':
            self.report({'WARNING'}, "Active object is not an Armature.")
            return {'CANCELLED'}

        if armature.mode != 'EDIT':
            self.report({'WARNING'}, "Please run this operator in Edit Mode.")
            return {'CANCELLED'}

        selected_bones = context.selected_editable_bones
        if not selected_bones:
            self.report({'WARNING'}, "No bones selected in Edit Mode.")
            return {'CANCELLED'}

        # Define target axes in world space
        # UE's X-forward, Z-up corresponds to Blender's Y-forward, Z-up
        world_y = Vector((0.0, 1.0, 0.0))
        world_z = Vector((0.0, 0.0, 1.0))

        for bone in selected_bones:
            # 1. Rename bone if necessary
            if not bone.name.lower().startswith("socket_"):
                bone.name = f"SOCKET_{bone.name}"

            # 2. Re-orient the bone
            # Keep the bone's head position, but change its orientation and length
            bone_length = bone.length
            head_pos = bone.head.copy()
            bone.display_type = 'STICK'


            if self.socket_type == 'ATTACH':
                # ATTACH: Bone Y-axis (primary) aligns with World Y (UE Forward)
                # Bone Z-axis aligns with World Z (UE Up)
                bone.tail = head_pos + world_y * bone_length
                bone.roll = 0.0
            elif self.socket_type == 'SPAWN':
                # SPAWN: Bone X-axis aligns with World Y (UE Forward)
                # Bone Z-axis aligns with World Z (UE Up)
                # This means the bone's primary axis (Y) must align with World -X
                bone_direction = Vector((-1.0, 0.0, 0.0))
                bone.tail = head_pos + bone_direction * bone_length
                bone.roll = 0.0
            
            # Recalculate bone matrix after changes
            armature.data.update_tag()
            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.object.mode_set(mode='EDIT')


        # 3. Set armature display for socket visibility
        # Switch to object mode to apply display settings
        # bpy.ops.object.mode_set(mode='OBJECT')
        # set_blender_armature_display(armature, display_type='STICK')
        # armature.data.show_names = True
        
        self.report({'INFO'}, f"Processed {len(selected_bones)} bones as {self.socket_type} sockets.")
        return {"FINISHED"}



class HST_OT_SelectBoneInOutliner(bpy.types.Operator):
    bl_idname = "hst.select_bone_in_outliner"
    bl_label = "Select Bone In Outliner"
    bl_description = "For the selected bone, show it as selected in the Outliner, expand its parents, and collapse other unrelated parts."

    @classmethod
    def poll(cls, context):
        # Check if there is an active armature in Pose or Edit mode
        active_obj = context.active_object
        if not active_obj or active_obj.type != 'ARMATURE':
            return False
        if active_obj.mode not in {'POSE', 'EDIT'}:
            return False
        # Check if there is an active bone
        if active_obj.mode == 'POSE' and not context.active_pose_bone:
            return False
        if active_obj.mode == 'EDIT' and not context.active_bone:
            return False
        return True

    def execute(self, context):
        armature_obj = context.active_object
        active_bone_name = None

        # Get the active bone name from the current mode
        if armature_obj.mode == 'POSE':
            active_bone_name = context.active_pose_bone.name
        elif armature_obj.mode == 'EDIT':
            active_bone_name = context.active_bone.name

        if not active_bone_name:
            self.report({'WARNING'}, "No active bone found.")
            return {'CANCELLED'}

        # Get the Bone object from its name
        active_bone = armature_obj.data.bones.get(active_bone_name)

        if not active_bone:
            self.report({'WARNING'}, f"Bone '{active_bone_name}' not found in armature data.")
            return {'CANCELLED'}

        # Find the Outliner area
        outliner_area = None
        for area in context.screen.areas:
            if area.type == 'OUTLINER':
                outliner_area = area
                break
        
        if not outliner_area:
            self.report({'WARNING'}, "Outliner area not found.")
            return {'CANCELLED'}

        # Override context for outliner operators
        override = context.copy()
        override['area'] = outliner_area
        override['region'] = outliner_area.regions[-1] # Use the main region

        # Switch Outliner to View Layer mode to ensure bones are visible
        outliner_area.spaces.active.display_mode = 'VIEW_LAYER'

        with context.temp_override(**override):
            # Deselect all in the outliner to start fresh
            bpy.ops.outliner.select_all(action='DESELECT')

            # Select the armature object in the outliner
            armature_obj.select_set(True)
            context.view_layer.objects.active = armature_obj

            # Collapse all hierarchies in the outliner
            bpy.ops.outliner.show_hierarchy()

            # Select the active bone in the armature's data
            armature_obj.data.bones.active = active_bone
            active_bone.select = True

            # Expand the hierarchy to show the active bone
            bpy.ops.outliner.show_active()

        self.report({'INFO'}, f"Selected '{active_bone.name}' in Outliner.")
        return {"FINISHED"}



