import bpy
import bmesh
from .Functions.CommonFunctions import (
    create_collection,
    filter_name,
    filter_type,
    make_transfer_proxy_mesh,
    apply_transfrom,
    merge_vertes_by_distance,
    set_visibility,
    Material,
    BMesh,
    Object,
)
import mathutils

from .Const import *

def get_bone_matrix(armature):
    """get bone matrix from armature"""
    bone_matrix = {}
    for bone in armature.pose.bones:
        bone_matrix[bone.name] = bone.matrix
    return bone_matrix

def add_datatransfer_modifier(mesh):
    """add datatransfer modifier to mesh"""
    transfer_source_mesh = bpy.data.objects[TRANSFER_MESH_PREFIX + mesh.name]
    if NORMALTRANSFER_MODIFIER in mesh.modifiers:
        datatransfermod = mesh.modifiers[NORMALTRANSFER_MODIFIER]

    else:
        datatransfermod = mesh.modifiers.new(
            name=NORMALTRANSFER_MODIFIER, type="DATA_TRANSFER"
        )
    datatransfermod.object = transfer_source_mesh
    datatransfermod.use_loop_data = True
    datatransfermod.data_types_loops = {"CUSTOM_NORMAL"}
    datatransfermod.loop_mapping = "TOPOLOGY"


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
    c_name = f"{mesh.name}{Const.SKM_SUFFIX}"
    collection = create_collection(c_name, Const.SKM_COLLECTION_COLOR)
    vertex_groups = mesh.vertex_groups
    split_meshes = []
    for group in vertex_groups:
        # duplicate mesh and rename to group.name
        print(f"group: {group.name}")
        split_mesh = mesh.copy()
        split_mesh.data = mesh.data.copy()
        split_mesh.name = f"{mesh.name}_{group.name}"
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
    if split_mesh:
        remove_mat_faces(split_mesh, non_decal_mats)
        print("remove non_decal_mats")
        remove_mat_faces(mesh, decal_mats)
    return split_mesh


# def seperate_by_vertexgroup(mesh):
#     obj = mesh
#     transform = obj.matrix_world
#     new_objs = []
#     c_name = f"{mesh.name}_SKM"
#     # collection = mesh.users_collection[0]
#     # if collection.name != c_name:
#     collection = create_collection(c_name, "02")
#     # Create a BMesh object and fill it with the mesh data
#     bm = bmesh.new()
#     bm.from_mesh(obj.data)

#     deform_layer = bm.verts.layers.deform.active
#     color_layer = bm.loops.layers.color.active

#     # Loop through the vertex groups
#     for group in obj.vertex_groups:
#         name = f"{mesh.name}_{group.name}"
#         # Create a new mesh and object for this group
#         new_mesh = bpy.data.meshes.new(name)
#         new_obj = bpy.data.objects.new(name, object_data=new_mesh)
#         collection.objects.link(new_obj)

#         # Create a new BMesh for this group
#         new_bm = bmesh.new()
#         new_color_layer = new_bm.loops.layers.color.new(color_layer.name)
#         vert_map = {}

#         # Create a mapping from old material indices to new material indices
#         mat_map = {}

#         # Create a new vertex group in the new object for each vertex group in the original object
#         group_map = new_obj.vertex_groups.new(name=group.name)
#         # group_map = {g: new_obj.vertex_groups.new(name=g.name) for g in obj.vertex_groups}
#         for vert in bm.verts:
#             if group.index in vert[deform_layer]:
#                 new_vert = new_bm.verts.new(vert.co)
#                 vert_map[vert] = new_vert

#         for face in bm.faces:
#             if all(vert in vert_map for vert in face.verts):
#                 new_face = new_bm.faces.new([vert_map[vert] for vert in face.verts])

#                 # Add the face's material to the new object and update the material index mapping
#                 if face.material_index not in mat_map:
#                     mat = obj.data.materials[face.material_index]
#                     new_obj.data.materials.append(mat)
#                     mat_map[face.material_index] = len(new_obj.data.materials) - 1

#                 # Assign the correct material index to the new face
#                 new_face.material_index = mat_map[face.material_index]

#                 for old_loop, new_loop in zip(face.loops, new_face.loops):
#                     new_loop[new_color_layer] = old_loop[color_layer]

#         new_obj.matrix_world = transform

#         new_bm.to_mesh(new_mesh)
#         new_bm.clear()
#         new_bm.free()
#         new_objs.append(new_obj)

#         group = new_obj.vertex_groups[0]
#         group.add(range(len(obj.data.vertices)), 1.0, "REPLACE")

#     # Clean up the original BMesh
#     bm.clear()
#     bm.free()
#     return new_objs


# def separate_by_material(mesh):
#     obj = mesh
#     transform = obj.matrix_world
#     new_objs = []
#     c_name = f"{mesh.name}"

#     collection = mesh.users_collection[0]

#     bm = bmesh.new()
#     bm.from_mesh(obj.data)

#     color_layer = bm.loops.layers.color.active

#     for mat_index, mat in enumerate(obj.data.materials):
#         if "_Decal" in mat.name:
#             name = f"{mesh.name}_{mat.name}"
#             new_mesh = bpy.data.meshes.new(name)
#             new_obj = bpy.data.objects.new(name, object_data=new_mesh)
#             collection.objects.link(new_obj)
#             new_bm = bmesh.new()
#             new_color_layer = new_bm.loops.layers.color.new(color_layer.name)
#             new_obj.data.materials.append(mat)

#             group_map = {
#                 g: new_obj.vertex_groups.new(name=g.name) for g in obj.vertex_groups
#             }

#             # Create a dictionary to map old vertices to new ones
#             vert_map = {}

#             # Loop through the faces in the original BMesh
#             faces_to_remove = []
#             for face in bm.faces:
#                 if face.material_index == mat_index:
#                     # If it does, create new vertices in the new BMesh for each vertex in the face
#                     new_verts = []
#                     for vert in face.verts:
#                         if vert not in vert_map:
#                             new_vert = new_bm.verts.new(vert.co)
#                             vert_map[vert] = new_vert
#                         new_verts.append(vert_map[vert])
#                     # Then, create a new face in the new BMesh using these new vertices
#                     new_face = new_bm.faces.new(new_verts)

#                     # Copy the vertex colors
#                     for old_loop, new_loop in zip(face.loops, new_face.loops):
#                         new_loop[new_color_layer] = old_loop[color_layer]

#                     # Add the face to the list of faces to remove
#                     faces_to_remove.append(face)

#             # Remove the faces from the original mesh

#             for face in faces_to_remove:
#                 edges_to_remove = []
#                 for edge in face.edges:
#                     if len(edge.link_faces) == 1:
#                         edges_to_remove.append(edge)
#                 bm.faces.remove(face)
#                 for edge in edges_to_remove:
#                     bm.edges.remove(edge)

#             obj.data.materials.pop(index=mat_index)
#             # Update the new mesh with the new BMesh data
#             new_bm.to_mesh(new_mesh)
#             new_bm.clear()
#             new_bm.free()
#             new_objs.append(new_obj)
#             group = new_obj.vertex_groups[0]
#             group.add(range(len(new_obj.data.vertices)), 1.0, "REPLACE")
#             new_obj.matrix_world = transform
#             # Update the original mesh with the modified BMesh data
#             bm.to_mesh(obj.data)

#             # Clean up the original BMesh
#             bm.clear()
#             bm.free()
#     return new_objs


def extract_child_mesh(armature) -> list:
    """extract child mesh from armature, apply transform and return list of child meshes"""
    child_meshes = []
    armature.select_set(False)
    for child in armature.children:
        # Check if the child is a mesh
        if child.type == "MESH":
            # Keep the current transform
            child.parent = None
            child.matrix_world = armature.matrix_world
            child.select_set(True)
            with bpy.context.temp_override(active_object=child):
                bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
            child_meshes.append(child)
    armature.select_set(True)
    with bpy.context.temp_override(active_object=armature):
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return child_meshes


def make_triangle_mesh(mesh):
    mesh = bpy.data.meshes.new(name="TriangleMesh")

    # Create a bmesh object and add a triangle to it
    bm = bmesh.new()
    bmesh.ops.create_cone(
        bm,
        cap_ends=True,
        cap_tris=True,
        segments=3,
        diameter1=0.1,
        diameter2=0,
        depth=0.1,
    )

    # Convert the bmesh to a mesh
    bm.to_mesh(mesh)
    bm.free()

    # Create a new object using the mesh
    obj = bpy.data.objects.new("TriangleObject", mesh)

    # Link the object to the current collection
    bpy.context.collection.objects.link(obj)


def make_sk_placeholder_mesh(armature):
    """make sk placeholder mesh from armature"""
    SUFFIX="_SK"
    collection=armature.users_collection[0]
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


class SkeletelSeparatorOperator(bpy.types.Operator):
    bl_idname = "hst.skeletel_separator"
    bl_label = "Skeletel Separator"
    bl_description = "Separate skeletel mesh for nanite"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_armatures = [obj for obj in selected_objects if obj.type == "ARMATURE"]
        target_meshes = []
        bpy.ops.object.select_all(action="DESELECT")
        bpy.ops.object.mode_set(mode="OBJECT")
        for obj in selected_objects:
            if obj.type == "MESH":
                if obj.parent is not None:
                    if obj.parent.type == "ARMATURE":
                        if obj.parent not in selected_armatures:
                            selected_armatures.append(obj.parent)
                else:
                    target_meshes = filter_type(selected_objects, "MESH")
            # obj.select_set(False)
        if len(selected_armatures) > 0:

            for armature in selected_armatures:
                current_collection = armature.users_collection[0]
                rig_collection = create_collection(
                    armature.name + Const.RIG_SUFFIX, Const.SKM_COLLECTION_COLOR
                )
                rig_collection.objects.link(armature)
                current_collection.objects.unlink(armature)
                meshes = extract_child_mesh(armature)
                for mesh in meshes:
                    if mesh not in target_meshes:
                        target_meshes.append(mesh)

                make_sk_placeholder_mesh(armature)
        else:
            target_meshes = filter_type(selected_objects, "MESH")
        target_meshes = filter_name(target_meshes, UCX_PREFIX, "EXCLUDE")

        for mesh in target_meshes:
            split_meshes = split_vertex_groups(mesh)

        bpy.ops.object.select_all(action="DESELECT")
        for mesh in split_meshes:
            for armature in selected_armatures:
                for bone in armature.data.bones:
                    if bone.name in mesh.name:
                        pose_bone = armature.pose.bones[bone.name]
                        bone_matrix = pose_bone.matrix
                        Object.set_pivot_to_matrix(mesh, bone_matrix)


            mesh.select_set(True)

        bpy.context.view_layer.objects.active=split_meshes[0]
        bpy.ops.object.material_slot_remove_unused()

        for mesh in split_meshes:
            split_decal_mat(mesh)

        for mesh in target_meshes:
            bpy.data.meshes.remove(mesh.data)
            # mesh.select_set(False)
            # set_visibility(mesh, False)
        bpy.ops.object.select_all(action="DESELECT")
        self.report({"INFO"}, "Skeletel Separation Complete")

        return {"FINISHED"}


class FillWeightOperator(bpy.types.Operator):
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


class FixSplitMesh(bpy.types.Operator):
    bl_idname = "hst.fix_splitmesh"
    bl_label = "Fix Split Faces Mesh"
    bl_description = "Merge split faces mesh without breaking the custom normal"

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

        transfer_collection = create_collection(
            TRANSFER_COLLECTION, PROXY_COLLECTION_COLOR
        )
        set_visibility(transfer_collection, True)
        transfer_object_list = []
        for mesh in selected_meshes:
            apply_transfrom(mesh)

            transfer_object_list.append(
                make_transfer_proxy_mesh(
                    mesh, TRANSFER_MESH_PREFIX, transfer_collection
                )
            )

            add_datatransfer_modifier(mesh)
            merge_vertes_by_distance(mesh, merge_distance=0.01)

            for modifier in mesh.modifiers:
                if modifier.type == "DATA_TRANSFER":
                    with bpy.context.temp_override(active_object=mesh):
                        bpy.ops.object.modifier_apply(modifier=modifier.name)

            mesh.select_set(True)

        collection_objects = transfer_collection.all_objects
        if len(collection_objects) == 0 or collection_objects is None:
            bpy.data.collections.remove(transfer_collection)

        for obj in transfer_object_list:
            bpy.data.meshes.remove(obj.data)

        set_visibility(transfer_collection, False)
        self.report(
            {"INFO"},
            "Added Bevel and Transfer Normal to "
            + str(len(selected_meshes))
            + " objects",
        )
        return {"FINISHED"}

# def set_obj_transform_to_cursor(obj):
#     context=bpy.context
#     cmx = context.scene.cursor.matrix
#     loc, rot, sca = obj.matrix_world.decompose()
#     omx = obj.matrix_world
#     mx = cmx
#     omx = obj.matrix_world.copy()
#     deltamx = mx.inverted_safe() @ obj.matrix_world
#     obj.matrix_world = mx
#     obj.data.transform(deltamx)
#     if obj.type == 'MESH':
#         obj.data.update()

# def set_obj_transform_to_matrix(obj,matrix):
#     # context=bpy.context
#     # cmx = context.scene.cursor.matrix
#     # loc, rot, sca = obj.matrix_world.decompose()
#     # omx = obj.matrix_world
#     # mx = cmx
#     # omx = obj.matrix_world.copy()
#     deltamx = matrix.inverted_safe() @ obj.matrix_world
#     obj.matrix_world = matrix
#     obj.data.transform(deltamx)
#     # if obj.type == 'MESH':
#     #     obj.data.update()
    

class Get_Bone_PosOperator(bpy.types.Operator):
    bl_idname = "hst.get_bone_pos"
    bl_label = "Get_Bone_Pos"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        cursor = bpy.context.scene.cursor
        
        
        for obj in selected_objects:
            # bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
            # obj.data.transform=cursor.matrix
            # print(f"obj: {obj.name} type: {obj.data.pivot}")
            if obj.type == "ARMATURE":
                pose_bone = obj.pose.bones["robotArmB_2"]  # Replace "Bone" with the name of your bone

                # Get the bone's transformation matrix
                bone_matrix = pose_bone.matrix
                cursor.matrix = bone_matrix

            if obj.type == "MESH":
                print(f"obj: {obj.name} type: {obj.type}")
                obj.location = (0, 0, 0)
                obj.rotation_euler = (0, 0, 0)
                obj.rotation_quaternion = mathutils.Quaternion((1, 0, 0, 0))
                # Object.set_pivot_to_matrix(obj,cursor.matrix)

        return {'FINISHED'}

