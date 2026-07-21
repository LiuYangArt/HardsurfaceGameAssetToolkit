# -*- coding: utf-8 -*-
"""运行 blender_test_driver 中一个指定回归 case。"""

import json
import os
import bpy


driver_path = os.environ["HST_TEST_DRIVER"]
namespace = {
    "__name__": "hst_single_test_driver",
    "__file__": driver_path,
}
exec(compile(open(driver_path, "rb").read(), driver_path, "exec"), namespace)

addon_module = namespace["load_addon_module"]()
addon_module.register()
context = namespace["TestContext"](addon_module)
case_name = os.environ["HST_SINGLE_TEST_NAME"]
callback = namespace[f"test_{case_name}"]
context.run_case(case_name, callback)
record = context.results[0].to_dict()
print("HST_SINGLE_TEST_RESULT=" + json.dumps(record, ensure_ascii=False))
try:
    addon_module.unregister()
except Exception:
    pass
if record["status"] != "passed":
    raise SystemExit(1)
