import bpy
import os
from .Functions.CommonFunctions import *
from .Const import Names, Paths


class AssetPreview:
    """functions for asset preview rendering and setting"""

    CAM_NAME = "AssetPreviewCamera"
    PREVIEW_IMAGE_NAME = "TempAssetPreview.png"

    @staticmethod
        


    def list_current_areas():
        """list current areas and spaces"""
        print("list current areas")
        for area in bpy.context.window.screen.areas:
            print(f"area type: {area.type} ui type:  {area.ui_type}")
            for space in area.spaces:
                print(f"space type: {space.type}")

    def check_screen_area(area_type, ui_type):
        screen_area = None
        screen = bpy.context.window.screen
        for area in screen.areas:
            if area.type == area_type and area.ui_type == ui_type:
                screen_area = area
                break
        return screen_area

    # def get_asset_library_area():
    #     screen_area = None
    #     screen = bpy.context.window.screen
    #     for area in screen.areas:

    #         if area.type == "FILE_BROWSER" and area.ui_type == "ASSETS":
    #             print("has asset lib area")
    #             screen_area = area
    #             for space in area.spaces:
    #                 if space.type == "FILE_BROWSER" and space.browse_mode == "ASSETS":
    #                     print("asset lib space")
    #                     break
    #             break
    #     return screen_area

    def asset_library_selection():
        selected_assets = None
        screen_area = AssetPreview.check_screen_area("FILE_BROWSER", "ASSETS")
        if screen_area is not None:
            with bpy.context.temp_override(
                area=screen_area,
                space=screen_area.spaces[0],
                region=screen_area.regions[0],
            ):

                selected_assets = bpy.context.selected_assets

        return selected_assets

    def add_camera_to_view():

        context = bpy.context
        # Add a camera without using ops
        camera_data = bpy.data.cameras.new("Camera")
        camera_object = bpy.data.objects.new("Camera", camera_data)
        camera_object.name = Names.PREVIEW_CAM
        bpy.context.collection.objects.link(camera_object)

        screen_area = AssetPreview.check_screen_area("VIEW_3D", "VIEW_3D")

        if screen_area is not None:
            with bpy.context.temp_override(
                area=screen_area,
                space=screen_area.spaces[0],
                region=screen_area.regions[0],
            ):
                context.scene.camera = camera_object
                bpy.ops.view3d.camera_to_view()
        else:
            bpy.data.objects.remove(camera_object, do_unlink=True)
            bpy.data.cameras.remove(camera_data, do_unlink=True)
            return None

        return camera_object

    def set_render_settings():
        # Set render engine to eevee
        bpy.context.scene.render.engine = "BLENDER_EEVEE"
        # Set render resolution to 128x128
        bpy.context.scene.render.resolution_x = 128
        bpy.context.scene.render.resolution_y = 128

        bpy.context.scene.eevee.taa_render_samples = 16
        bpy.context.scene.eevee.use_gtao = True
        bpy.context.scene.eevee.use_ssr = True
        bpy.context.scene.eevee.use_ssr_refraction = False

        bpy.context.scene.render.image_settings.color_mode = "RGBA"
        bpy.context.scene.render.film_transparent = True

    def render_from_camera():

        filepath = Paths.TEMP_DIR + Names.PREVIEW_IMAGE
        # Store current render engine
        current_render_engine = bpy.context.scene.render.engine
        current_render_resolution_x = bpy.context.scene.render.resolution_x
        current_render_resolution_y = bpy.context.scene.render.resolution_y
        current_render_filepath = bpy.context.scene.render.filepath

        AssetPreview.set_render_settings()

        bpy.context.scene.render.filepath = filepath
        bpy.ops.render.render(write_still=True, use_viewport=True)

        # restore render settings after render
        bpy.context.scene.render.filepath = current_render_filepath
        bpy.context.scene.render.engine = current_render_engine
        bpy.context.scene.render.resolution_x = current_render_resolution_x
        bpy.context.scene.render.resolution_y = current_render_resolution_y
        return filepath

    def set_preview_to_asset(filepath, obj):
        asset_lib_area = AssetPreview.check_screen_area("FILE_BROWSER", "ASSETS")
        print(f"Make preview for asset: {obj.name}")

        with bpy.context.temp_override(
            id=obj.local_id,
            area=asset_lib_area,
            space=asset_lib_area.spaces[0],
            region=asset_lib_area.regions[0],
        ):
            bpy.ops.ed.lib_id_load_custom_preview(filepath=filepath)

        # print("set preview")

    def remove_camera(camera_object):
        cam_data = camera_object.data
        camera_object.data.user_clear()
        bpy.data.objects.remove(camera_object, do_unlink=True)
        bpy.data.cameras.remove(cam_data, do_unlink=True)
        # print("remove camera")

    # def remove_render(file_path):
    #     os.remove(file_path)

    # print("remove temp render")


class MakeAssetPreviewOperator(bpy.types.Operator):
    bl_idname = "hst.makeassetpreview"
    bl_label = "MakeAssetPreview"
    bl_description = "Make asset preview from current 3d view. select asset in asset library and run this operator to set preview to selected asset\
        为选中的Asset Library中的Asset生成预览图，可用于Shader Nodes等非模型类Asset。预览图为当前3D视图的渲染结果。"

    def execute(self, context):
        selected_objects=Object.get_selected()
        # is_local_view=Viewport.is_local_view()
        visible_objects=[]
        all_objects=bpy.context.scene.objects
        view3d_space=Viewport.get_3dview_space()
        is_local_view=view3d_space.local_view
        view_area=check_screen_area("VIEW_3D")
        visible_lights=[]

        if is_local_view:
            with bpy.context.temp_override(
                window=bpy.context.window,
                area=view_area,
                region=next(region for region in view_area.regions if region.type == "WINDOW"),
                screen=bpy.context.window.screen,
                space=view3d_space
        ):
                bpy.ops.view3d.localview(frame_selected=False)
        
        print(f"is local view: {is_local_view}")
        for obj in all_objects:
            visiblity= obj.hide_render
            if visiblity is False:
                visible_objects.append(obj)
        if selected_objects:
            for obj in visible_objects:
                if obj.type == "LIGHT":
                    visible_lights.append(obj)
                if obj not in selected_objects and obj.type != "LIGHT":
                    obj.hide_render=True


        asset_lib_area = AssetPreview.check_screen_area(
            "FILE_BROWSER", "ASSETS"
        )  # 检查是否有Asset Library面板
        if asset_lib_area is None:
            self.report({"ERROR"}, "No Asset Library Panel at Current Screen")
            return {"CANCELLED"}
        assets = AssetPreview.asset_library_selection()  # 检查是否有选中的Asset
        if assets is None or len(assets) == 0:
            self.report({"ERROR"}, "No Asset in Asset Library Selected")
            return {"CANCELLED"}
        camera_object = AssetPreview.add_camera_to_view()  # 添加摄像机
        if camera_object is None:
            self.report({"ERROR"}, "No 3D View at Current Screen")
            return {"CANCELLED"}
        

        if selected_objects:
            5
            with bpy.context.temp_override(
            window=bpy.context.window,
            area=view_area,
            region=next(region for region in view_area.regions if region.type == "WINDOW"),
            screen=bpy.context.window.screen,
            space=view3d_space):
                bpy.ops.view3d.view_selected()
                # bpy.ops.view3d.localview(frame_selected=False)
            # for obj in visible_lights:
            #     obj.select_set(True)

        preview_image = AssetPreview.render_from_camera()  # 渲染预览图
        for asset in assets:
            AssetPreview.set_preview_to_asset(preview_image, asset)  # 设置预览图
            AssetPreview.remove_camera(camera_object)
            os.remove(preview_image)

        for obj in visible_objects:
            obj.hide_render=False
        


        self.report({"INFO"}, "Asset Preview Created")
        return {"FINISHED"}
