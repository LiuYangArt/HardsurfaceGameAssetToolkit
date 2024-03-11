import bpy
from .Const import *
from .Functions.CommonFunctions import *
from .Functions.AssetCheckFunctions import *


class StaticMeshExportOperator(bpy.types.Operator):
    bl_idname = "hst.staticmeshexport"
    bl_label = "HST StaticMesh Export UE"
    bl_description = "根据Collection分组导出Unreal Engine使用的静态模型fbx\
        只导出已被标记且可见的Collection，不导出隐藏的Collection,不导出隐藏的物体\
        在outliner中显示器符号作为是否导出的标记，与眼睛符号无关"

    def execute(self, context):

        parameters = context.scene.hst_params
        export_path = parameters.export_path.replace("\\", "/")
        if export_path == "":
            self.report(
                {"ERROR"},
                "No export path set, please set export path and retry | "
                + "没有设置导出路径，请设置导出路径后重试",
            )
            return {"CANCELLED"}
        if export_path.endswith("/") is False:
            export_path = export_path + "/"
        visible_collections = filter_collection_by_visibility(type="VISIBLE")
        # selected_objects = bpy.context.selected_objects
        store_mode = prep_select_mode()
        bpy.ops.hst.setsceneunits()  # 设置场景单位为厘米
        bpy.ops.object.select_all(action="DESELECT")
        
        (
            bake_collections,
            decal_collections,
            prop_collections,
            sm_collections,
            skm_collections,
            rig_collections,
        ) = filter_collection_types(visible_collections)
        export_collections = (
            bake_collections + decal_collections + prop_collections + sm_collections
        )

        if len(skm_collections) == 0:
            if len(export_collections) == 0:
                self.report(
                    {"ERROR"},
                    "No available collection for export. Please check visibility "
                    + "and ensure objects are placed in collections，"
                    + "set collection in correct type\n"
                    + "没有可导出的collection，请检查collection可见性，把要导出的资产放在collection中，并设置正确的类型后重试",
                )
                return {"CANCELLED"}

        # Check Bake
        check_collections(self, bake_collections, prop_collections, decal_collections)
        if len(export_collections) > 0:
            for collection in export_collections:
                new_name = collection.name.removeprefix("SM_")
                new_name = "SM_" + new_name
                file_path = export_path + new_name + ".fbx"
                FBXExport.staticmesh(collection, file_path)
        
        skm_count=0
        if len(skm_collections) > 0:
            for collection in skm_collections:
                # new_name = collection.name.removeprefix("SKM_")
                # new_name = "SKM_" + new_name
                for mesh in collection.objects:
                    new_name = mesh.name.removeprefix("SM_")
                    new_name = "SM_" + new_name
                    file_path = export_path + new_name + ".fbx"
                    skm_count += 1
                    FBXExport.staticmesh(mesh, file_path,reset_transform=True)
                    # mesh.select_set(True)
        if len(rig_collections) > 0:
            print(f"rig_collections: {rig_collections}")
            for collection in rig_collections:
                print(f"collection: {collection.name} type: {collection.type}")
                # for armature in collection.objects:
                new_name = collection.name.removeprefix("SK_")
                new_name = "SK_" + new_name
                file_path = export_path + new_name + ".fbx"
                FBXExport.skeletal(collection, file_path)

        restore_select_mode(store_mode)

        export_count = (
            len(export_collections) + skm_count + len(rig_collections)
        )
        self.report(
            {"INFO"},
            f"{export_count} Meshes exported to {export_path}",
        )
        return {"FINISHED"}

from mathutils import Matrix, Vector
class TestFuncOperator(bpy.types.Operator):
    bl_idname = "hst.testfunc"
    bl_label = "TestFunc"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        for obj in selected_objects:
            print(f"obj: {obj.name} type: {obj.type}")
            print(f"dir obj: {dir(obj)}")
        for collection in bpy.data.collections:
            print(f"collection: {collection.name} type: {collection.type}")

            
            c_type = Object.read_custom_property(collection, "HST_CollectionType")
            if c_type:
                print(f"Collection Type: {c_type}")
            # collection["custom_prop"]="Hello!?"

            # collection_type=collection.get['HST_CollectionType']
            # if collection_type:
            # print(f"Collection Type: {collection.get('HST_CollectionType')}")


        #     print(f"obj: {obj.name} type: {obj.type}")
        #     export_staticmesh_fbx(
        #         obj, f"D:\OneDrive\Desktop\Export_Test\{obj.name}.fbx"
        #     )
        # for collection in bpy.data.collections:
        #     print(f"collection: {collection.name} type: {collection.type}")
        #     export_staticmesh_fbx(
        #         collection, f"D:\OneDrive\Desktop\Export_Test\{collection.name}.fbx"
        #     )
        #     # print(f"dir collection: {dir(collection)}")

        return {"FINISHED"}
