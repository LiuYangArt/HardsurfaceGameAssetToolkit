# -*- coding: utf-8 -*-
"""
Collection 管理 Operators
========================

包含 Collection 标记、排序、隔离显示等功能。
"""

import bpy
from ..Const import *
from ..Functions.CommonFunctions import *


class HST_OT_MarkDecalCollection(bpy.types.Operator):
    """标记为 Decal Collection"""
    bl_idname = "hst.markdecalcollection"
    bl_label = "Mark Decal Collection"
    bl_description = "设置所选为Decal Collection，对collection中的Mesh，如果材质名是decal类型，则标记Mesh为decal。"

    def execute(self, context):
        selected_collections = Collection.get_selected()

        if selected_collections is None:
            self.report(
                {"ERROR"},
                "No selected collection, please select collections and retry\n"
                + "没有选中Collection，请选中Collection后重试",
            )
            return {"CANCELLED"}

        for decal_collection in selected_collections:
            static_meshes, ucx_meshes = filter_static_meshes(decal_collection)
            if len(ucx_meshes) > 0:
                self.report(
                    {"ERROR"},
                    decal_collection.name
                    + " has UCX mesh, please check | "
                    + "collection内有UCX Mesh，请检查",
                )

            decal_collection_name = clean_collection_name(decal_collection.name)
            new_name = decal_collection_name + DECAL_SUFFIX
            decal_collection.name = new_name

            decal_collection.hide_render = True
            Collection.mark_hst_type(decal_collection, "DECAL")
            for mesh in static_meshes:
                mats = get_materials(mesh)
                for mat in mats:
                    if mat.name.endswith(MESHDECAL_SUFFIX) or mat.name.endswith(INFODECAL_SUFFIX) or mat.name.endswith(DECAL_SUFFIX) or mat.name.startswith(DECAL_PREFIX):
                        Object.mark_hst_type(mesh, "DECAL")
                        self.report({"INFO"}, mesh.name + " marked as Decal")
                        mesh.visible_shadow = False
                        mesh.display.show_shadows = False

            self.report(
                {"INFO"}, str(len(selected_collections)) + " Decal collection marked"
            )
        return {"FINISHED"}


class HST_OT_MarkPropCollection(bpy.types.Operator):
    """标记为 Prop Collection"""
    bl_idname = "hst.markpropcollection"
    bl_label = "Mark Prop Collection"
    bl_description = "设置所选为Prop Collection"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_collections = Collection.get_selected()

        if selected_collections is None:
            self.report(
                {"ERROR"},
                "No selected collection, please select collections and retry\n"
                + "没有选中Collection，请选中Collection后重试",
            )
            return {"CANCELLED"}

        for prop_collection in selected_collections:
            prop_collection_name = clean_collection_name(prop_collection.name)
            new_name = prop_collection_name

            prop_collection.name = new_name
            Collection.mark_hst_type(prop_collection, "PROP")
            prop_collection.hide_render = True
        rename_prop_meshes(selected_objects)

        self.report({"INFO"}, str(len(selected_collections)) + " Prop collection marked")
        return {"FINISHED"}


class HST_OT_SortCollections(bpy.types.Operator):
    """按字母排序所有 Collection"""
    bl_idname = "hst.sort_collections"
    bl_label = "Sort Collections"
    bl_description = "按首字母对所有Collection进行排序"

    def execute(self, context):
        for scene in bpy.data.scenes:
            Collection.sort_order(scene.collection, case_sensitive=False)
        return {'FINISHED'}


class HST_OT_IsolateCollectionsAlt(bpy.types.Operator):
    """隔离显示选中的 Collection"""
    bl_idname = "hst.isolate_collections_alt"
    bl_label = "Isolate Collections"
    bl_description = "选中collection中的任一物体，单独显示此collection"

    def execute(self, context):
        is_local_view = Viewport.is_local_view()
        selected_collections = Collection.get_selected()
        selected_objects = Object.get_selected()
        
        if selected_collections is None:
            if selected_objects is None:
                if is_local_view:
                    self.report({"INFO"}, "Exit local view")
                    bpy.ops.view3d.localview(frame_selected=False)
                else:
                    self.report({"INFO"}, "nothing selected, please select object and retry")
                    return {"CANCELLED"}
        else:
            store_mode = prep_select_mode()
            if selected_collections:
                for collection in selected_collections:
                    parent_coll = Collection.find_parent(collection)
                    if parent_coll:
                        if parent_coll not in selected_collections:
                            selected_collections.append(parent_coll)

                coll_objs = []
                if selected_collections is not None:
                    for coll in selected_collections:
                        for object in coll.all_objects:
                            if object not in coll_objs:
                                coll_objs.append(object)

                Collection.active(selected_collections[0])

                if is_local_view is True:
                    bpy.ops.view3d.localview()

                for object in bpy.data.objects:
                    object.select_set(False)

                for obj in coll_objs:
                    obj.select_set(True)

                bpy.ops.view3d.localview(frame_selected=True)

                restore_select_mode(store_mode)

            self.report({"INFO"}, "Isolate Collections")

        return {'FINISHED'}


class HST_OT_BreakLinkFromLibrary(bpy.types.Operator):
    """断开与 Asset Library 的链接"""
    bl_idname = "hst.break_link_from_library"
    bl_label = "Break Link From Library"
    bl_description = "Break Link From Library"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        selected_meshes = filter_type(selected_objects, "MESH")
        count = 0
        unlinked_meshes = []
        if selected_meshes is None:
            self.report({"INFO"}, "No meshes selected, please select mesh and retry")
            return {'CANCELLED'}
        else:
            for mesh in selected_meshes:
                unlinked_mesh = Object.break_link_from_assetlib(mesh)
                unlinked_meshes.append(unlinked_mesh)
                count += 1
            for mesh in unlinked_meshes:
                mesh.select_set(True)
            self.report({"INFO"}, f"{count} meshes break link from library")
        return {'FINISHED'}
