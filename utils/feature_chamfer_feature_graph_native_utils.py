import bpy
import importlib
import platform
import sys
from pathlib import Path

_NATIVE_MODULE_NAME = "_hst_feature_graph_native"
_NATIVE_MODULE = None
_NATIVE_IMPORT_ERROR = None
_BACKEND_OVERRIDE = None
_NATIVE_FORMAL_INTEGRATION_ENABLED = True


# 加载当前平台可用的 FeatureGraph native module。
# force_reload: 是否清除 import cache 后重试；返回已加载 module，不可用时抛出 ImportError。
def load_feature_graph_native(force_reload=False):
    global _NATIVE_MODULE, _NATIVE_IMPORT_ERROR
    if force_reload:
        _NATIVE_MODULE = None
        _NATIVE_IMPORT_ERROR = None
        sys.modules.pop(_NATIVE_MODULE_NAME, None)
    if _NATIVE_MODULE is not None:
        return _NATIVE_MODULE
    if _NATIVE_IMPORT_ERROR is not None:
        raise ImportError("FeatureGraph native backend is unavailable") from _NATIVE_IMPORT_ERROR
    module_directory = Path(__file__).resolve().parent.parent / "native" / "feature_chamfer_feature_graph"
    module_directory_text = str(module_directory)
    if module_directory_text not in sys.path:
        sys.path.insert(0, module_directory_text)
    try:
        _NATIVE_MODULE = importlib.import_module(_NATIVE_MODULE_NAME)
    except ImportError as error:
        _NATIVE_IMPORT_ERROR = error
        raise ImportError("FeatureGraph native backend is unavailable") from error
    return _NATIVE_MODULE


# 查询 native backend 是否可加载，供 Python fallback 路由使用。
# 返回 Boolean；只把平台或二进制缺失视为不可用。
def feature_graph_native_available():
    try:
        load_feature_graph_native()
    except ImportError:
        return False
    return True


# 设置测试专用 backend override。
# backend: auto/python/native 或 None；生产入口不应设置此值。
def set_backend_override_for_tests(backend):
    global _BACKEND_OVERRIDE
    if backend not in {None, "auto", "python", "native"}:
        raise ValueError(f"Unsupported FeatureGraph backend: {backend}")
    _BACKEND_OVERRIDE = backend


# 清除测试专用 backend override。
def clear_backend_override_for_tests():
    global _BACKEND_OVERRIDE
    _BACKEND_OVERRIDE = None


# 解析当前 FeatureGraph backend。
# requested: 可选显式 backend；auto 在 Windows 优先 native，其余平台稳定回退 Python。
def resolve_feature_graph_backend(requested=None):
    backend = requested or _BACKEND_OVERRIDE or "auto"
    if backend == "python":
        return "python"
    if backend == "native":
        load_feature_graph_native()
        return "native"
    if backend != "auto":
        raise ValueError(f"Unsupported FeatureGraph backend: {backend}")
    if (
        _NATIVE_FORMAL_INTEGRATION_ENABLED
        and platform.system() == "Windows"
        and feature_graph_native_available()
    ):
        return "native"
    return "python"


# 调用完整 native FeatureGraph solver。
# primitive: source Mesh primitive；miter_scale_limit: profile 膨胀上限；返回 groups 与 stats 纯数据。
def solve_feature_graph_native(primitive, miter_scale_limit=1.5):
    native_module = load_feature_graph_native()
    return native_module.solve_feature_graph(primitive, miter_scale_limit)
