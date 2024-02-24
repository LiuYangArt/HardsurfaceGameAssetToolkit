import bpy
from ..Const import *

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

def check_decal_materials(object):
    result = False
    decal_collection=object.users_collection[0]

    if len(object.material_slots) == 0:
        print(
            object.name
            + " in Collection: "
            + decal_collection.name
            + " has NO MATERIAL!"
        )

    for material in object.material_slots:
        if material.name.endswith(DECAL_SUFFIX):
            print("is decal material")
            result = True
        elif DECAL_SUFFIX + "." in material.name:
            print("HAS duplicated decal material!")
        else:
            print(
                object.name
                + " in Collection: "
                + decal_collection.name
                + " has NON-DECAL-MATERIAL!"
            )
    return result