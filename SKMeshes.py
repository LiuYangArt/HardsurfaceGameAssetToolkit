import bpy
import bmesh
from .Functions.CommonFunctions import *


from .Const import *


def get_bone_matrix(armature):
    """get bone matrix from armature"""
    bone_matrix = {}
    for bone in armature.pose.bones:
        bone_matrix[bone.name] = bone.matrix
    return bone_matrix


def remove_active_vertexgroup_verts(mesh):
    """remove active vertex group verts"""

    bm = bmesh.new()
    bm.from_mesh(mesh.data)

    bm.verts.layers.deform.verify()

    deform = bm.verts.layers.deform.active

    verts_select = set()

    for v in bm.verts:
        for group in v[deform].items():
            group_index, weight = group
            print(f"index: {group_index}, weight: {weight}")
            if group_index == 0:
                verts_select.add(v)

    bmesh.ops.delete(bm, geom=list(verts_select), context="VERTS")

    bm.to_mesh(mesh.data)
    mesh.data.update()
    bm.clear()
    bm.free()


def extract_vertexgroup_verts(mesh, groupindex=0):
    """extract verts from vertex group index"""
    groupindex = int(groupindex)
    bm = bmesh.new()
    bm.from_mesh(mesh.data)

    bm.verts.layers.deform.verify()
    deform = bm.verts.layers.deform.active

    verts_select = []
    verts_delete = []

    for v in bm.verts:
        for group in v[deform].items():
            group_index, weight = group
            if group_index == groupindex and weight > 0:
                verts_select.append(v)

    for v in bm.verts:
        if v not in verts_select:
            verts_delete.append(v)

    bmesh.ops.delete(bm, geom=verts_delete, context="VERTS")

    bm.to_mesh(mesh.data)
    mesh.data.update()
    bm.clear()
    bm.free()


def remove_mat_faces(mesh, materials):
    """remove faces with materials in materials list"""
    mat_indexs = []
    for material in materials:
        mat_index = mesh.data.materials.find(material.name)
        mat_indexs.append(mat_index)
        print(f"material: {material.name} index: {mat_index}")

    bm = bmesh.new()
    bm.from_mesh(mesh.data)

    faces_to_remove = []

    for face in bm.faces:
        for mat_index in mat_indexs:
            if face.material_index == mat_index:
                if face not in faces_to_remove:
                    faces_to_remove.append(face)

    for face in faces_to_remove:
        edges_to_remove = []
        for edge in face.edges:
            if len(edge.link_faces) == 1:
                edges_to_remove.append(edge)
        bm.faces.remove(face)
        for edge in edges_to_remove:
            bm.edges.remove(edge)

    bm.to_mesh(mesh.data)
    mesh.data.update()
    bm.clear()
    bm.free()

    for mat in materials:
        for material in mesh.data.materials:
            if material.name == mat.name:
                mat_index = mesh.data.materials.find(material.name)
                mesh.data.materials.pop(index=mat_index)


def clean_groups(mesh, group_index):
    """remove all vertex groups except group_index"""
    remove_groups = []
    for group in mesh.vertex_groups:
        if group.index != group_index:
            remove_groups.append(group)
    for group in remove_groups:
        mesh.vertex_groups.remove(group)


def split_vertex_groups(mesh) -> list:
    """split mesh by vertex groups, return list of split meshes"""
    name=mesh.name.removeprefix(Const.SKELETAL_MESH_PREFIX)
    name=name.split("_")[0]
    skm_collection_name = f"{name}{Const.SKM_SUFFIX}"
    collection = Collection.create(name=skm_collection_name, type="SKM")
    vertex_groups = mesh.vertex_groups
    split_meshes = []
    for group in vertex_groups:
        # duplicate mesh and rename to group.name
        # print(f"group: {group.name}")
        split_mesh = mesh.copy()
        split_mesh.data = mesh.data.copy()
        split_mesh.name = f"{Const.STATICMESH_PREFIX}{name}_{group.name}"
        collection.objects.link(split_mesh)
        split_meshes.append(split_mesh)
    for group in vertex_groups:
        for mesh in split_meshes:
            if mesh.name.endswith(group.name):
                extract_vertexgroup_verts(mesh, group.index)
                clean_groups(mesh, group.index)
    return split_meshes


def split_decal_mat(mesh) -> bpy.types.Object:
    """split mesh by decal material, remove decal material faces from original mesh, return split mesh object"""

    collection = mesh.users_collection[0]
    materials = mesh.data.materials

    split_mesh = None
    has_decal_mat = False
    decal_mats = []
    non_decal_mats = []
    for material in materials:
        if DECAL_SUFFIX in material.name:
            has_decal_mat = True
            decal_mats.append(material)
        else:
            non_decal_mats.append(material)
    if has_decal_mat:
        split_mesh = mesh.copy()
        split_mesh.data = mesh.data.copy()
        split_mesh.name = mesh.name + DECAL_SUFFIX
        collection.objects.link(split_mesh)
        Object.mark_hst_type(split_mesh, "DECAL")

    if split_mesh:
        remove_mat_faces(split_mesh, non_decal_mats)
        print("remove non_decal_mats")
        remove_mat_faces(mesh, decal_mats)
    return split_mesh


def extract_child_mesh(armature) -> list:
    """extract child mesh from armature, apply transform and return list of child meshes"""
    child_meshes = []
    armature.select_set(False)
    arm_collection=get_collection(armature)
    name=arm_collection.name
    for child in armature.children:
        # Check if the child is a mesh
        if child.type == "MESH":
            # Keep the current transform
            Transform.ops_apply(child)
            child.parent = None
            child.matrix_world = armature.matrix_world
            child.select_set(True)
            child_meshes.append(child)
        rename_meshes(child_meshes, Const.SKELETAL_MESH_PREFIX + name)
    return child_meshes


# def make_triangle_mesh(mesh):
#     mesh = bpy.data.meshes.new(name="TriangleMesh")

#     # Create a bmesh object and add a triangle to it
#     bm = bmesh.new()
#     bmesh.ops.create_cone(
#         bm,
#         cap_ends=True,
#         cap_tris=True,
#         segments=3,
#         diameter1=0.1,
#         diameter2=0,
#         depth=0.1,
#     )

#     # Convert the bmesh to a mesh
#     bm.to_mesh(mesh)
#     bm.free()

#     # Create a new object using the mesh
#     obj = bpy.data.objects.new("TriangleObject", mesh)

#     # Link the object to the current collection
#     bpy.context.collection.objects.link(obj)


def make_sk_placeholder_mesh(armature):
    """make sk placeholder mesh from armature"""
    SUFFIX = "_SK"
    collection = armature.users_collection[0]
    sk_mesh = bpy.data.meshes.new(armature.name + SUFFIX)
    vertices = [
        (0, 0, 0),
        (0.001, 0, 0),
        (0, 0.001, 0),
    ]
    faces = [(0, 1, 2)]
    sk_mesh.from_pydata(vertices, [], faces)

    sk_obj = bpy.data.objects.new(armature.name + SUFFIX, sk_mesh)
    collection.objects.link(sk_obj)
    sk_obj.parent = armature
    sk_obj.matrix_world = armature.matrix_world
    Object.mark_hst_type(sk_obj, "PLACEHOLDER")

    # loop the first bone of the armature, and create a vertex group , fill weight 1.0
    bone = armature.data.bones[0]
    active_group = sk_obj.vertex_groups.new(name=bone.name)
    active_group.add(range(len(sk_obj.data.vertices)), 1.0, "REPLACE")
    # add armature modifier to sk_obj
    armature_mod = sk_obj.modifiers.new(name="Armature", type="ARMATURE")
    armature_mod.object = armature
    armature_mod.use_vertex_groups = True

    # sk_obj.select_set(True)
    # bpy.context.view_layer.objects.active = sk_obj
    # bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    # bpy.ops.object.select_all(action="DESELECT")
    return sk_obj


# def add_placeholder_material():
#     """ add placeholder material"""
#     MAT_NAME = "MI_Placeholder"
#     has_mat=False
#     placeholder_mat = None

#     for mat in bpy.data.materials:
#         if mat.name == MAT_NAME:
#             has_mat=True
#             placeholder_mat = mat
#             break
#     if not has_mat:
#         placeholder_mat_ = bpy.data.materials.new(name=MAT_NAME)
#     return placeholder_mat


class HST_OT_SkeletelSeparator(bpy.types.Operator):
    bl_idname = "hst.skeletel_separator"
    bl_label = "Skeletel Separator"
    bl_description = "Separate skeletel mesh for nanite\
        导入骨骼模型FBX不要勾选Armature下的Automatic Bone Orientation，会破坏骨骼朝向"

    def execute(self, context):
        bpy.ops.object.mode_set(mode="OBJECT")
        selected_objects = bpy.context.selected_objects
        selected_armatures = [obj for obj in selected_objects if obj.type == "ARMATURE"]
        target_meshes = []
        bpy.ops.object.select_all(action="DESELECT")
        
        for obj in selected_objects:

            if obj.type == "EMPTY":
                print(f"obj: {obj.name} type: {obj.type}")
                for child in obj.children:
                    if child.type == "ARMATURE":
                        if child not in selected_armatures:
                            selected_armatures.append(child)
                            break

        for obj in selected_objects:
            if obj.type == "MESH":
                custom_type=Object.read_custom_property(obj, Const.CUSTOM_TYPE)
                if custom_type == Const.TYPE_SKM:
                    self.report(
                        {"ERROR"},
                        "Mesh has been separated, please don't re-split\n"
                        + "Mesh已经分离，请不要重复操作",
                    )
                    return {"CANCELLED"}
                if obj.parent is not None:
                    if obj.parent.type == "ARMATURE":
                        if obj.parent not in selected_armatures:
                            selected_armatures.append(obj.parent)
                else:
                    target_meshes = filter_type(selected_objects, "MESH")
            # obj.select_set(False)
        if len(selected_armatures) == 0:
            self.report(
                {"ERROR"},
                "No selected armature, please select armature and retry\n"
                + "没有选中的Armature，请选中Armature后重试",
            )
            return {"CANCELLED"}

        elif len(selected_armatures) > 0:
            for armature in selected_armatures:
                custom_type=Object.read_custom_property(armature, Const.CUSTOM_TYPE)
                if custom_type == Const.TYPE_SPLITSKEL:
                    self.report(
                        {"ERROR"},
                        "Armature has been separated, please don't re-split\n"
                        + "Armature已经分离，请不要重复操作",
                    )
                    return {"CANCELLED"}
                current_collection = get_collection(armature)
                
                if current_collection is None:
                    self.report(
                        {"ERROR"},
                        "Armature not in collection, please put armature in collection and retry\n"
                        + "Armature不在Collection中，请把Armature放在Collection中后重试",
                    )
                    return {"CANCELLED"}
                if armature.parent is not None:
                    empty_obj = armature.parent
                    Transform.apply(armature.parent)
                    armature.parent = None
                    bpy.data.objects.remove(empty_obj)

                Transform.ops_apply(armature)
                Armature.set_display(armature)
                Object.mark_hst_type(armature, "SPLITSKEL")
                # sk_name=armature.name
                sk_name=current_collection.name
                Collection.create(
                    name=sk_name, type="RIG"
                )
                # rig_collection.objects.link(armature)
                # current_collection.objects.unlink(armature)
                
                meshes = extract_child_mesh(armature)
                for mesh in meshes:
                    if mesh not in target_meshes:
                        target_meshes.append(mesh)

                make_sk_placeholder_mesh(armature)

        target_meshes = Object.filter_hst_type(target_meshes, "UCX", "EXCLUDE")

        for mesh in target_meshes:
            split_meshes = split_vertex_groups(mesh)

        bpy.ops.object.select_all(action="DESELECT")
        if len(split_meshes) == 0:
            self.report(
                {"ERROR"},
                "No vertex group found in mesh, please check vertex group and retry\n"
                + "Mesh没有Vertex Group，请检查Vertex Group后重试",
            )

        for mesh in split_meshes:
            Object.mark_hst_type(mesh, "SKM")
            for armature in selected_armatures:
                for bone in armature.data.bones:
                    if bone.name in mesh.name:
                        pose_bone = armature.pose.bones[bone.name]
                        bone_matrix = pose_bone.matrix
                        Object.set_pivot_to_matrix(mesh, bone_matrix)

            mesh.select_set(True)

        bpy.context.view_layer.objects.active = split_meshes[0]
        bpy.ops.object.material_slot_remove_unused()

        for mesh in split_meshes:
            split_decal_mat(mesh)

        for mesh in target_meshes:
            set_visibility(mesh, False)
            # bpy.data.meshes.remove(mesh.data)

        bpy.ops.object.select_all(action="DESELECT")

        self.report({"INFO"}, "Skeletel Separation Complete")

        return {"FINISHED"}


class HST_OT_FillWeight(bpy.types.Operator):
    bl_idname = "hst.fill_weight"
    bl_label = "Fill Weight"
    bl_description = "Fill active vertex group with 1.0 weight"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        # bpy.ops.paint.weight_paint_toggle()

        for mesh in selected_meshes:
            active_group = mesh.vertex_groups.active
            active_group.add(range(len(mesh.data.vertices)), 1.0, "REPLACE")
            print(f"active_group: {active_group.name} filled")
        self.report({"INFO"}, "Fill Weight Complete")
        return {"FINISHED"}


class HST_OT_FixSplitMesh(bpy.types.Operator):
    bl_idname = "hst.fix_splitmesh"
    bl_label = "Fix Split Faces Mesh"
    bl_description = "Merge split faces mesh without breaking the custom normal"

    def add_datatransfer_modifier(self, mesh,transfer_source_mesh):
        """add datatransfer modifier to mesh"""
        # transfer_source_mesh = bpy.data.objects[TRANSFER_MESH_PREFIX + mesh.name]
        if NORMALTRANSFER_MODIFIER in mesh.modifiers:
            datatransfermod = mesh.modifiers[NORMALTRANSFER_MODIFIER]

        else:
            datatransfermod = mesh.modifiers.new(
                name=NORMALTRANSFER_MODIFIER, type="DATA_TRANSFER"
            )
        datatransfermod.object = transfer_source_mesh
        datatransfermod.use_loop_data = True
        datatransfermod.data_types_loops = {"CUSTOM_NORMAL"}
        datatransfermod.loop_mapping = "NEAREST_POLYNOR"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        if len(selected_objects) == 0:
            self.report(
                {"ERROR"},
                "No selected object, please select objects and retry\n"
                + "没有选中的Object，请选中物体后重试",
            )
            return {"CANCELLED"}

        selected_meshes = filter_type(selected_objects, "MESH")
        selected_meshes = filter_name(selected_meshes, UCX_PREFIX, "EXCLUDE")

        if len(selected_meshes) == 0:
            self.report(
                {"ERROR"},
                "No selected mesh object, please select mesh objects and retry\n"
                + "没有选中Mesh物体，请选中Mesh物体后重试",
            )
            return {"CANCELLED"}
        
        transfer_collection = Collection.create(TRANSFER_COLLECTION, type="PROXY")
        set_visibility(transfer_collection, True)
        transfer_object_list = []
        for mesh in selected_meshes:
            current_matrix = mesh.matrix_world.copy()
            Transform.apply(mesh)
            proxy_mesh=make_transfer_proxy_mesh(
                    mesh, TRANSFER_MESH_PREFIX, transfer_collection
                )

            transfer_object_list.append(proxy_mesh)
            self.add_datatransfer_modifier(mesh,proxy_mesh)
            Mesh.merge_verts_by_distance(mesh, merge_distance=0.0001)
            for modifier in mesh.modifiers:
                if modifier.type == "DATA_TRANSFER":
                    bpy.context.view_layer.objects.active = mesh
                    bpy.ops.object.modifier_apply(modifier=modifier.name)
            mesh.select_set(True)
            Object.set_pivot_to_matrix(mesh, current_matrix)

        for obj in transfer_object_list:
            bpy.data.meshes.remove(obj.data)
        set_visibility(transfer_collection, False)
        collection_objects = transfer_collection.all_objects
        if len(collection_objects) == 0 or collection_objects is None:
            bpy.data.collections.remove(transfer_collection)

        self.report(
            {"INFO"},
            "Added Bevel and Transfer Normal to "
            + str(len(selected_meshes))
            + " objects",
        )
        return {"FINISHED"}


class HST_OT_GetBonePos(bpy.types.Operator):
    bl_idname = "hst.get_bone_pos"
    bl_label = "Get_Bone_Pos"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects

        for obj in selected_objects:

            if obj.type == "ARMATURE":

                print(f"obj: {obj.name} type: {obj.type}")
                type=Object.read_custom_property(obj, Const.CUSTOM_TYPE)
                self.report({"INFO"}, f"obj: {obj.name} type: {type}")

            if obj.type == "MESH":
                type=Object.read_custom_property(obj, Const.CUSTOM_TYPE)
                self.report({"INFO"}, f"obj: {obj.name} type: {type}")
                # print(f"obj: {obj.name} type: {obj.type}")
                # print(obj.matrix_world)
                # Transform.apply(obj, location=True, rotation=True, scale=True)

        return {"FINISHED"}


class HST_OT_DisplayUEBoneDirection(bpy.types.Operator):
    bl_idname = "hst.display_ue_bone_direction"
    bl_label = "DisplayUEBoneDirection"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        custom_shape_mesh = None
        for obj in selected_objects:
            if obj.type == "MESH":
                custom_shape_mesh = obj
                break
        for obj in selected_objects:
            if custom_shape_mesh is not None:
                if obj.type == "ARMATURE":
                    for bone in obj.data.bones:
                        pose_bone = obj.pose.bones[bone.name]
                        pose_bone.custom_shape = custom_shape_mesh

        return {"FINISHED"}



class HST_OT_FixRootBoneForUE(bpy.types.Operator):
    bl_idname = "hst.fix_root_bone_for_ue"
    bl_label = "Fix Root Bone For UE"
    bl_description = "修正root bone的朝向，适配UE规范。使用armature的第一根骨骼作为root bone。"

    def execute(self, context):
        # 块注释：
        # 对于选中的 armature object，进入编辑模式，对其 root bone（第一个 bone）进行如下处理：
        # 1. 与其所有子级 bone 断开（disconnect）。
        # 2. 调整 root bone 的朝向：X轴朝向世界-Y，Y轴朝向世界X，Z轴朝向世界Z（head:0,0,0 tail:x:0.1,0,0）。
        # 3. 恢复原有模式和选择。

        selected_objects = bpy.context.selected_objects
        armatures = [obj for obj in selected_objects if obj.type == "ARMATURE"]
        if not armatures:
            self.report({'ERROR'}, "未选中任何骨骼对象（Armature）")
            return {'CANCELLED'}

        for armature in armatures:
            # 存储当前模式和选择，便于恢复
            store_mode = prep_select_mode()
            bpy.context.view_layer.objects.active = armature
            armature.select_set(True)
            bpy.ops.object.mode_set(mode='EDIT')

            edit_bones = armature.data.edit_bones
            if not edit_bones:
                self.report({'ERROR'}, f"骨架 {armature.name} 没有任何骨骼")
                restore_select_mode(store_mode)
                return {'CANCELLED'}

            # 寻找 root bone（无 parent 的 bone，若无则取第一个）
            root_bone = None
            for bone in edit_bones:
                if bone.parent is None:
                    root_bone = bone
                    break
            if root_bone is None:
                root_bone = edit_bones[0]

            root_bone.name = "root"

            # 断开 root bone 的所有子骨骼连接
            for child in root_bone.children:
                child.use_connect = False

            # 调整 root bone 的 head 和 tail
            root_bone.head = (0.0, 0.0, 0.0)
            root_bone.tail = (0.01, 0.0, 0.0)  # Y轴朝向世界X
            root_bone.roll = 0.0

            bpy.ops.object.mode_set(mode='OBJECT')
            restore_select_mode(store_mode)

        self.report({'INFO'}, "Root Bone 处理完成")
        return {'FINISHED'}

