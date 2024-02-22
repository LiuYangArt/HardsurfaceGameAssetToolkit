import bpy


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
