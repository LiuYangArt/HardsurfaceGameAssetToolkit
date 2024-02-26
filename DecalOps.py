import bpy
#TBD: 贴花工具组

class MakeDecalOperator(bpy.types.Operator):
    bl_idname = "object.makedecal"
    bl_label = "MakeDecal"
    bl_description = "Make Decal Asset"

    def execute(self, context):
        #TBD: 对所选物体进行处理
        # pivot 剧中到mesh
        # 增加 displace modifier， 上移.002
        # 修改命名 Decal_XXX
        # 保存到AssetLibrary
            # 拍Decal的缩略图
            # 导入环境
            # 导入摄像机
            # 渲染
            # 保存缩略图


        # Get the selected objects
        return {'FINISHED'}


class OpenAssetLibraryOperator(bpy.types.Operator):
    bl_idname = "object.open_assetlib"
    bl_label = "Open AssetLibrary"
    bl_description = "Open AssetLibrary"

    def execute(self, context):
        #在下方打开AssetLibrary窗口
        return {'FINISHED'}
