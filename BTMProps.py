import bpy
from bpy.props import (BoolProperty, EnumProperty, FloatProperty, IntProperty,
                       StringProperty)
from bpy.types import PropertyGroup
from bpy.utils import register_class, unregister_class

class BTMPropGroup(PropertyGroup):

    grouplist: EnumProperty(
        name="Group list",
        description="Apply Data to attribute.",
        items=[ ('_01', "Group 1", ""),
                ('_02', "Group 2", ""),
                ('_03', "Group 3", ""),
                ('_04', "Group 4", ""),
                ('_05', "Group 5", ""),
                ('_06', "Group 6", ""),
                ('_07', "Group 7", ""),
                ('_08', "Group 8", ""),
                ('_09', "Group 9", ""),
                ('_10', "Group 10", ""),
               ]
        )

    sel_bevel_width: FloatProperty(
        description="Batch edit HST bevel width", 
        default=0.01,
        min=0.0, max=1.0
        )

    sel_bevel_segments: IntProperty(
        description="Batch edit HST bevel segments", 
        default=1,
        min=0, max=12
        )

    add_triangulate: BoolProperty(
        description="Whether to add triangulation modifiers.", 
        default=True
        )

    clean_all_mod: BoolProperty(
        description="Clear all modifiers.", 
        default=True
        )

class BTMCollection (PropertyGroup):
    baker_id: IntProperty()

classes = (BTMPropGroup,
           BTMCollection)