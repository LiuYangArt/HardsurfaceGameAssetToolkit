import bpy
from ..Const import *
from .CommonFunctions import set_active_color_attribute, name_remove_digits


def scene_unit_check():
    scene_settings = bpy.context.scene.unit_settings
    if scene_settings.length_unit != "CENTIMETERS" or scene_settings.system != "METRIC":
        return False
    else:
        return True


def show_reusult(result_input):
    match result_input:
        case False:
            result_show = "ERROR"
        case True:
            result_show = "CHECKMARK"
    return result_show


def check_bake_object(object):
    uv_check = False
    material_check = False
    mesh_check = False
    result = False
    bake_collection = object.users_collection[0]
    print("checking " + object.name + " in " + bake_collection.name + " for export")

    if object.type == "MESH":
        mesh_check = CHECK_OK
        if len(object.data.uv_layers) == 0:
            uv_check = "No UV"
        elif len(object.data.uv_layers) > 1:
            uv_check = "More Than 1 UV"
        else:
            uv_check = CHECK_OK

        if (LOW_SUFFIX) in object.name:
            if len(object.material_slots) == 0:
                material_check = "No Material"
                print(
                    object.name
                    + " in Collection: "
                    + bake_collection.name
                    + " has NO MATERIAL!"
                )
            else:
                for material in object.material_slots:
                    # if not material.name.startswith(MATERIAL_PREFIX):
                    #     material_check = "No Prefix"
                    if "Bake." in material.name:
                        material_check = "Duplicated"
                    else:
                        material_check = CHECK_OK
        elif (HIGH_SUFFIX) in object.name: # high poly not need to check
            uv_check = CHECK_OK
            material_check = CHECK_OK
    
    else:
        mesh_check = "No Mesh"


    if uv_check is CHECK_OK and material_check is CHECK_OK and mesh_check is CHECK_OK:
        result = CHECK_OK
    elif mesh_check is not CHECK_OK:
        result = "Mesh = " + mesh_check
    else:
        result = "UV = " + uv_check + " , Material = " + material_check
    return result


def check_decal_object(object):
    uv_check = False
    material_check = False
    result = False
    decal_collection = object.users_collection[0]
    print(
        "checking "
        + object.name
        + " in "
        + decal_collection.name
        + "as decal for export"
    )

    if object.type == "MESH":
        if object.name.startswith(UCX_PREFIX):
            mesh_check = "is UCX"
        else:
            mesh_check = CHECK_OK
            if len(object.data.uv_layers) == 0:
                uv_check = "No UV"
            elif len(object.data.uv_layers) > 1:
                uv_check = "Has More Than 1 UV"
            else:
                uv_check = CHECK_OK

            if len(object.material_slots) == 0:
                material_check = "No Mat"
            else:
                for material in object.material_slots:
                    if not material.name.startswith(MATERIAL_PREFIX):
                        material_check = "No Prefix"
                    elif "Decal" not in material.name:
                        material_check = "BAD"
                    elif "Decal." in material.name:
                        material_check = "Duplicated"
                    else:
                        material_check = CHECK_OK

    if mesh_check is CHECK_OK and uv_check is CHECK_OK and material_check is CHECK_OK:
        result = CHECK_OK
    elif mesh_check is not CHECK_OK:
        result = "Mesh = " + mesh_check
    else:
        result = "UV = " + uv_check + " , Material = " + material_check
    print(result)
    return result


def check_prop_object(object):

    result = "BAD TYPE"
    prop_collection = object.users_collection[0]
    print("checking " + object.name + " in " + prop_collection.name + " for export")

    if object.type == "MESH":
        if not object.name.startswith(UCX_PREFIX):
            result = check_prop_staticmesh(object)
        else:
            result = check_UCX(object)
            # result = True
    elif object.type == "EMPTY":
        result = check_snap_socket(object)
    else:
        print("BAD TYPE")

    return result


def check_prop_staticmesh(object):
    if object.type == "MESH":
        if not object.name.startswith(UCX_PREFIX):
            vertex_color_check = False
            material_check = False
            uv0_check = False
            uv1_check = False
            
            vertex_color = set_active_color_attribute(object, WEARMASK_ATTR)
            if vertex_color is not None:
                vertex_color_check = True

            mat_result = "No Mat"
            if len(object.material_slots) > 0:
                for material in object.material_slots:
                    if "Decal" in material.name:
                        mat_result = "Decal Mat"
                    elif not material.name.startswith(MATERIAL_PREFIX):
                        mat_result = "No MI Prefix"
                    elif "." in material.name:
                        mat_result = "Duplicated"
                    else:
                        mat_result = CHECK_OK
                        material_check = True
            else:
                print("NO MATERIAL!")
            if object.data.uv_layers.get(UV_BASE) is not None:
                uv0_check = True
            if object.data.uv_layers.get(UV_SWATCH) is not None:
                uv1_check = True

            # check result
            if vertex_color_check == False:
                vertex_color_result = "Missing"
            else:
                vertex_color_result = CHECK_OK
            if material_check == False:
                mat_result = mat_result
            else:
                mat_result = CHECK_OK
            if uv0_check == False:
                uv0_result = "No UV"
            else:
                uv0_result = CHECK_OK
            if uv1_check == False:
                uv1_result = "No UV"
            else:
                uv1_result = CHECK_OK

            if vertex_color_check and material_check and uv0_check and uv1_check:
                result = CHECK_OK
            else:
                result = (
                    "UV0 = "
                    + uv0_result
                    + " , UV1 = "
                    + uv1_result
                    + " , WearMask = "
                    + vertex_color_result
                    + " , Material = "
                    + mat_result
                )

    return result


def check_UCX(object):
    result = "No UCX"
    if object.name.startswith(UCX_PREFIX):
        # extract name
        name = object.name.split(UCX_PREFIX)[1]
        name = name_remove_digits(name,parts=2)

        collection = object.users_collection[0]
        has_match_name = False
        for obj in collection.all_objects:
            if obj.name == name:
                has_match_name = True
                break
        print(has_match_name)
        if has_match_name:
            result = CHECK_OK
        else:
            result = "No Match Mesh Naming"
    return result


def check_snap_socket(object):
    result = "BAD TYPE"
    if object.type == "EMPTY":
        if object.name.startswith(SOCKET_PREFIX):
            print("is Snap Socket")
            result = CHECK_OK
    return result

def check_collections(self,bake_collections,prop_collections,decal_collections):
    for collection in bake_collections:
        for object in collection.all_objects:
            bake_check_result = check_bake_object(object)
            if bake_check_result != CHECK_OK:
                self.report(
                    {"ERROR"},
                    "Collection: "
                    + collection.name
                    + " has non-standard prop object, please check: | "
                    + "有不符合Prop规范的物体，请检查确认",
                )
                break
        for object in collection.all_objects:
            set_active_color_attribute(object, BAKECOLOR_ATTR)
            check_bake_object(object)
            bake_check_result = check_bake_object(object)
            if bake_check_result != CHECK_OK:
                self.report(
                    {"ERROR"},
                    "  Object: " + object.name + " : " + bake_check_result,
                )

    # Check Prop
    for collection in prop_collections:
        for object in collection.all_objects:
            prop_check_result = check_prop_object(object)
            if prop_check_result != CHECK_OK:
                self.report(
                    {"ERROR"},
                    "Collection: "
                    + collection.name
                    + " has non-standard prop object, please check: | "
                    + "有不符合Prop规范的物体，请检查确认",
                )
                break
        for object in collection.all_objects:
            prop_check_result = check_prop_object(object)
            if prop_check_result != CHECK_OK:
                self.report(
                    {"ERROR"},
                    "  Object: " + object.name + " | " + prop_check_result,
                )

    # Check Decal
    for collection in decal_collections:
        for object in collection.all_objects:
            decal_check_result = check_decal_object(object)
            if decal_check_result != CHECK_OK:
                self.report(
                    {"ERROR"},
                    "Collection: "
                    + collection.name
                    + " has non-standard decal object, please check: | "
                    + "有不符合Decal规范的物体，请检查确认",
                )
                break
        for object in collection.all_objects:
            decal_check_result = check_decal_object(object)
            if decal_check_result != CHECK_OK:
                self.report(
                    {"ERROR"},
                    "  Object: " + object.name + " : " + decal_check_result,
                )