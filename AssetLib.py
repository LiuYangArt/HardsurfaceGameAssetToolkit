import bpy
import os
from .Functions.CommonFunctions import *
from .Const import *


class AssetLibrary:
    @staticmethod

    def get_asset_library_area():
        screen_area = None
        screen = bpy.context.window.screen
        for area in screen.areas:

            if area.type == "FILE_BROWSER" and area.ui_type == "ASSETS":
                print("has asset lib area")
                screen_area = area
                for space in area.spaces:
                    if space.type == "FILE_BROWSER" and space.browse_mode == "ASSETS":
                        print("asset lib space")
                        break
                break
        return screen_area

    def asset_library_selection():
        selected_assets = None
        screen_area = None
        screen = bpy.context.window.screen
        for area in screen.areas:

            if area.type == "FILE_BROWSER" and area.ui_type == "ASSETS":
                print("has asset lib area")
                screen_area = area
                for space in area.spaces:
                    if space.type == "FILE_BROWSER" and space.browse_mode == "ASSETS":
                        print("asset lib space")
                        break
                break

        if screen_area is not None:
            with bpy.context.temp_override(
                area=screen_area,
                space=screen_area.spaces[0],
                region=screen_area.regions[0],
            ):

                selected_assets = bpy.context.selected_assets

        return selected_assets

    def add_camera_to_view():
        print("add camera")
        CAM_NAME = "AssetPreviewCamera"
        context= bpy.context
        # Add a camera without using ops
        camera_data = bpy.data.cameras.new("Camera")
        camera_object = bpy.data.objects.new("Camera", camera_data)
        camera_object.name = CAM_NAME
        bpy.context.collection.objects.link(camera_object)

        screen_area=check_screen_area("VIEW_3D")
        if screen_area is not None:
            with  bpy.context.temp_override(area=screen_area, space=screen_area.spaces[0], region=screen_area.regions[0]):
                context.scene.camera=camera_object
                bpy.ops.view3d.camera_to_view()
        else:
            print("no 3d view, remove camera and camera data")
            bpy.data.objects.remove(camera_object, do_unlink=True)
            bpy.data.cameras.remove(camera_data, do_unlink=True)
            return None
        
        return camera_object

    def render_from_camera():
        print("render from camera")
        PREVIEW_IMAGE_NAME = "TempAssetPreview.png"
        filepath=AddonPath.TEMP_PATH + PREVIEW_IMAGE_NAME 
        # Store current render engine
        current_render_engine = bpy.context.scene.render.engine
        current_render_resolution_x = bpy.context.scene.render.resolution_x
        current_render_resolution_y = bpy.context.scene.render.resolution_y
        current_render_filepath = bpy.context.scene.render.filepath

        # Set render engine to eevee
        bpy.context.scene.render.engine = 'BLENDER_EEVEE'
        # Set render resolution to 128x128
        bpy.context.scene.render.resolution_x = 128
        bpy.context.scene.render.resolution_y = 128

        bpy.context.scene.eevee.taa_render_samples = 16
        bpy.context.scene.eevee.use_gtao = True
        bpy.context.scene.eevee.use_ssr = True
        bpy.context.scene.eevee.use_ssr_refraction = False

        bpy.context.scene.render.image_settings.color_mode = 'RGBA'
        bpy.context.scene.render.film_transparent = True

        
        
        bpy.context.scene.render.filepath = filepath
        # Render pic from camera
        bpy.ops.render.render(write_still=True, use_viewport=True)

        bpy.context.scene.render.engine = current_render_engine
        bpy.context.scene.render.resolution_x = current_render_resolution_x
        bpy.context.scene.render.resolution_y = current_render_resolution_y
        return filepath



    def set_preview_to_asset(filepath, obj):
        asset_lib_area = AssetLibrary.get_asset_library_area()
        print(f"Make preview for asset: {obj.name}")
        # print(f"dir obj: {dir(obj)}")
        # print(f"local id: {obj.local_id}" )
        # print(f"file path: {file_path}")
        with bpy.context.temp_override(id=obj.local_id, area=asset_lib_area, space=asset_lib_area.spaces[0], region=asset_lib_area.regions[0]):
            bpy.ops.ed.lib_id_load_custom_preview(filepath=filepath)


        print("set preview")

    def remove_camera(camera_object):
        cam_data = camera_object.data
        camera_object.data.user_clear()
        bpy.data.objects.remove(camera_object, do_unlink=True)
        bpy.data.cameras.remove(cam_data, do_unlink=True)
        print("remove camera")

    def remove_render(file_path):
        os.remove(file_path)

        print("remove temp render")


class MakeAssetPreviewOperator(bpy.types.Operator):
    bl_idname = "hst.makeassetpreview"
    bl_label = "MakeAssetPreview"
    bl_description = "Make asset preview from current 3d view. select asset in asset library and run this operator to set preview to selected asset\
        为选中的Asset Library中的Asset生成预览图，可用于Shader Nodes等非模型类Asset。预览图为当前3D视图的渲染结果。"


    def execute(self, context):
        asset_lib_area = AssetLibrary.get_asset_library_area()
        if asset_lib_area is None:
            self.report({"ERROR"}, "No Asset Library Panel at Current Screen")
            return {"CANCELLED"}
        assets = AssetLibrary.asset_library_selection()
        print(f"assets: {assets}")
        if assets is None or len(assets) == 0:
            self.report({"ERROR"}, "No Asset in Asset Library Selected")
            return {"CANCELLED"}
        camera_object=AssetLibrary.add_camera_to_view()
        if camera_object is None:
            self.report({"ERROR"}, "No 3D View at Current Screen")
            return {"CANCELLED"}
        preview_image=AssetLibrary.render_from_camera()
        for asset in assets:
            AssetLibrary.set_preview_to_asset(preview_image, asset)
            AssetLibrary.remove_camera(camera_object)
            AssetLibrary.remove_render(preview_image)


        self.report({"INFO"}, "Asset Preview Created")
        return {"FINISHED"}
