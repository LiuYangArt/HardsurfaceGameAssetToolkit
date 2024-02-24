import bpy
from ..Const import *
from .CommonFunctions import set_active_color_attribute

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
    result = False
    bake_collection = object.users_collection[0]
    print("checking " + object.name + " in " + bake_collection.name + " for export")

    

    if object.type == "MESH":
        if len(object.data.uv_layers) == 0:
            uv_check = False
            print("NO UV!")
        elif len(object.data.uv_layers) > 1:
            uv_check = False
            print("has MORE THAN 1 UV!")
        else:
            uv_check = True
        
        if (LOW_SUFFIX) in object.name:
            if len(object.material_slots) == 0:
                print(
                    object.name
                    + " in Collection: "
                    + bake_collection.name
                    + " has NO MATERIAL!"
                )
            else:
                for material in object.material_slots:
                    if not material.name.startswith(MATERIAL_PREFIX):
                        print("MAT PREFIX is wrong")
                    elif "Bake." in material.name:
                        print("has DUPLICATED BAKE MATERIAL!")
                    else:
                        print("material GOOD")
                        material_check = True
    else:
        print("NOT MESH")
                        
    if uv_check and material_check:
        result = True
    return result


def check_decal_object(object):
    uv_check = False
    material_check = False
    result = False
    decal_collection = object.users_collection[0]
    print("checking " + object.name + " in " + decal_collection.name + "as decal for export")

    if object.type == "MESH":
        if len(object.data.uv_layers) == 0:
            uv_check = False
            print("NO UV!")
        elif len(object.data.uv_layers) > 1:
            uv_check = False
            print("has MORE THAN 1 UV!")
        else:
            uv_check = True

        if len(object.material_slots) == 0:
            print(
                object.name
                + " in Collection: "
                + decal_collection.name
                + " has NO MATERIAL!"
            )
        else:
            for material in object.material_slots:
                if not material.name.startswith(MATERIAL_PREFIX):
                    print("MAT PREFIX is wrong")
                elif "Decal" not in material.name:
                    print("has NON-DECAL MATERIAL!")
                # elif not material.name.endswith(MESHDECAL_SUFFIX):
                #     if not material.name.endswith(INFODECAL_SUFFIX):
                #         print("has NON-DECAL MATERIAL!")
                elif "Decal." in material.name:
                    print("has DUPLICATED DECAL MATERIAL!")
                else:
                    print("material GOOD")
                    material_check = True
    else:
        print("NOT MESH")
    if uv_check and material_check:
        result = True
    return result


def check_prop_object(object):

    result = False
    prop_collection = object.users_collection[0]
    print("checking " + object.name + " in " + prop_collection.name + " for export")

    if object.type == "MESH":
        vertex_color_check = False
        material_check = False
        uv0_check = False
        uv1_check = False
        vertex_color = set_active_color_attribute(object, WEARMASK_ATTR)
        if vertex_color is None:
            print("NO WEARMASK!")
        else:
            vertex_color_check = True
            print("HAS WEARMASK!")
        if len(object.material_slots) > 0:
            for material in object.material_slots:
                if "Decal" in material.name:
                    print("HAS decal material")
                elif not material.name.startswith(MATERIAL_PREFIX):
                    print("Mat prefix is wrong")
                elif "." in material.name:
                    print("HAS duplicated material!")
                else:
                    print("material good")
                    material_check = True
        else:
            print("NO MATERIAL!")
        if object.data.uv_layers.get(UV_BASE) is None:
            print("NO UV0!")
        else:
            uv0_check = True
        if object.data.uv_layers.get(UV_SWATCH) is None:
            print("NO UV1!")
        else:
            uv1_check = True

        if vertex_color_check and material_check and uv0_check and uv1_check:
            result = True

    elif object.type == "EMPTY":
        if object.name.startswith(SOCKET_PREFIX):
            print("is snap socket")
            result = True
    else:
        print("BAD TYPE")

    return result
