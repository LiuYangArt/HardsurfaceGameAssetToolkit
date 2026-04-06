# -*- coding: utf-8 -*-
"""
图像分析工具函数
===============

包含材质贴图提取、alpha 读取和连通域分析功能。
"""

from array import array
from collections import OrderedDict
import os

import bpy

RunSpan = tuple[int, int, int]
RegionBounds = dict[str, int]
ImageCacheStamp = tuple[object, ...]

_ALPHA_IMAGE_CACHE_MAX = 2
_ALPHA_THRESHOLD_CACHE_MAX = 8
_ALPHA_IMAGE_CACHE: OrderedDict[ImageCacheStamp, dict] = OrderedDict()
_ALPHA_THRESHOLD_CACHE: OrderedDict[tuple[ImageCacheStamp, float], dict] = OrderedDict()


def _collect_upstream_image_nodes(node, visited, image_nodes) -> None:
    """递归收集连接到当前节点上游的图片节点。"""
    if node is None:
        return

    node_key = node.as_pointer()
    if node_key in visited:
        return

    visited.add(node_key)

    if node.type == "TEX_IMAGE" and node.image is not None:
        image_nodes.append(node)

    for input_socket in node.inputs:
        for link in input_socket.links:
            _collect_upstream_image_nodes(link.from_node, visited, image_nodes)


def get_linked_image_texture_node(material: bpy.types.Material):
    """
    获取连接到材质输出链路上的 Image Texture 节点。

    这里不做“取第一个图片节点”式的宽松 fallback，只接受真实连到 shader 输出的图片。
    """
    if material is None:
        raise ValueError("Active object has no active material")
    if not material.use_nodes or material.node_tree is None:
        raise ValueError("Active material must use nodes")

    output_nodes = [
        node
        for node in material.node_tree.nodes
        if node.type == "OUTPUT_MATERIAL"
    ]
    active_outputs = [
        node for node in output_nodes if getattr(node, "is_active_output", False)
    ]
    if active_outputs:
        output_nodes = active_outputs

    image_nodes = []
    visited = set()
    for output_node in output_nodes:
        surface_input = output_node.inputs.get("Surface")
        if surface_input is None:
            continue
        for link in surface_input.links:
            _collect_upstream_image_nodes(link.from_node, visited, image_nodes)

    if not image_nodes:
        raise ValueError("Active material has no image texture linked into the shader output")

    return image_nodes[0]


def _touch_cache_entry(cache: OrderedDict, key):
    """读取缓存项并刷新 LRU 顺序。"""
    entry = cache.get(key)
    if entry is None:
        return None

    cache.move_to_end(key)
    return entry


def _store_cache_entry(cache: OrderedDict, key, value, max_size: int) -> None:
    """写入缓存并按 LRU 限制容量。"""
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > max_size:
        cache.popitem(last=False)


def _get_image_size_and_channels(image: bpy.types.Image) -> tuple[int, int, int]:
    """校验图像尺寸和通道数。"""
    if image is None:
        raise ValueError("Image texture node has no image datablock")

    width, height = image.size
    channels = int(image.channels)
    if width <= 0 or height <= 0:
        raise ValueError("Image has invalid size")
    if channels < 4:
        raise ValueError("Image must contain an alpha channel")
    return width, height, channels


def _resolve_image_cache_path(image: bpy.types.Image) -> str:
    """尽量解析出稳定的图像绝对路径。"""
    image_path = getattr(image, "filepath_raw", "") or getattr(image, "filepath", "")
    if not image_path:
        return ""

    bpy_path = getattr(bpy, "path", None)
    if bpy_path is not None and hasattr(bpy_path, "abspath"):
        try:
            image_path = bpy_path.abspath(image_path)
        except Exception:
            pass

    return os.path.normcase(os.path.normpath(image_path))


def _build_image_cache_stamp(
    image: bpy.types.Image,
    width: int,
    height: int,
    channels: int,
) -> ImageCacheStamp | None:
    """构造图像内容缓存键。dirty 图像不走缓存，避免内存编辑时失效不准。"""
    if bool(getattr(image, "is_dirty", False)):
        return None

    image_pointer = image.as_pointer() if hasattr(image, "as_pointer") else id(image)
    image_path = _resolve_image_cache_path(image)
    packed_file = bool(getattr(image, "packed_file", None))

    if image_path and not packed_file:
        try:
            stat = os.stat(image_path)
            source_stamp = (image_path, stat.st_mtime_ns, stat.st_size)
        except OSError:
            source_stamp = (image_path, None, None)
    else:
        source_stamp = (
            image_path,
            packed_file,
            getattr(image, "source", ""),
            getattr(image, "name_full", getattr(image, "name", "")),
        )

    return (image_pointer, width, height, channels, source_stamp)


def _get_image_cache_context(
    image: bpy.types.Image,
) -> tuple[int, int, int, ImageCacheStamp | None]:
    """返回图像尺寸、通道和缓存戳。"""
    width, height, channels = _get_image_size_and_channels(image)
    cache_stamp = _build_image_cache_stamp(image, width, height, channels)
    return width, height, channels, cache_stamp


def read_image_alpha(
    image: bpy.types.Image,
) -> tuple[int, int, array, int, ImageCacheStamp | None]:
    """读取并提取 alpha 通道。"""
    width, height, channels, cache_stamp = _get_image_cache_context(image)

    pixel_count = width * height
    pixels = array("f", [0.0]) * (pixel_count * channels)
    image.pixels.foreach_get(pixels)
    alpha_values = pixels[3::channels]
    transparent_pixel_count = sum(1 for alpha in alpha_values if alpha < 0.999)
    return width, height, alpha_values, transparent_pixel_count, cache_stamp


def _get_alpha_data(image: bpy.types.Image) -> dict:
    """读取或复用图像 alpha 数据。"""
    width, height, channels, cache_stamp = _get_image_cache_context(image)

    if cache_stamp is not None:
        cached = _touch_cache_entry(_ALPHA_IMAGE_CACHE, cache_stamp)
        if cached is not None:
            return cached

    width, height, alpha_values, transparent_pixel_count, cache_stamp = read_image_alpha(image)
    alpha_data = {
        "width": width,
        "height": height,
        "alpha_values": alpha_values,
        "transparent_pixel_count": transparent_pixel_count,
        "cache_stamp": cache_stamp,
    }
    if cache_stamp is not None:
        _store_cache_entry(
            _ALPHA_IMAGE_CACHE,
            cache_stamp,
            alpha_data,
            _ALPHA_IMAGE_CACHE_MAX,
        )

    return alpha_data


def _find_root(parents: list[int], index: int) -> int:
    """并查集 root 查找，带路径压缩。"""
    while parents[index] != index:
        parents[index] = parents[parents[index]]
        index = parents[index]
    return index


def _merge_region_stats(target: RegionBounds, source: RegionBounds) -> None:
    """把 source 的包围盒和像素数合并到 target。"""
    target["min_x"] = min(target["min_x"], source["min_x"])
    target["min_y"] = min(target["min_y"], source["min_y"])
    target["max_x"] = max(target["max_x"], source["max_x"])
    target["max_y"] = max(target["max_y"], source["max_y"])
    target["pixel_count"] += source["pixel_count"]


def _union_regions(
    parents: list[int],
    region_stats: list[RegionBounds],
    left: int,
    right: int,
) -> int:
    """合并两个连通域，并返回新的 root。"""
    left_root = _find_root(parents, left)
    right_root = _find_root(parents, right)
    if left_root == right_root:
        return left_root

    if region_stats[left_root]["pixel_count"] < region_stats[right_root]["pixel_count"]:
        left_root, right_root = right_root, left_root

    parents[right_root] = left_root
    _merge_region_stats(region_stats[left_root], region_stats[right_root])
    return left_root


def _create_region(
    region_stats: list[RegionBounds],
    parents: list[int],
    start_x: int,
    end_x: int,
    y: int,
    pixel_count: int,
) -> int:
    """创建新的连通域节点。"""
    region_index = len(region_stats)
    parents.append(region_index)
    region_stats.append(
        {
            "min_x": start_x,
            "min_y": y,
            "max_x": end_x,
            "max_y": y,
            "pixel_count": pixel_count,
        }
    )
    return region_index


def _extend_region(
    region: RegionBounds,
    start_x: int,
    end_x: int,
    y: int,
    pixel_count: int,
) -> None:
    """把当前行的 run 扩展到已有连通域。"""
    region["min_x"] = min(region["min_x"], start_x)
    region["max_x"] = max(region["max_x"], end_x)
    region["max_y"] = max(region["max_y"], y)
    region["pixel_count"] += pixel_count


def _build_row_runs(
    alpha_values: array,
    width: int,
    height: int,
    alpha_threshold: float,
) -> tuple[list[list[RunSpan]], bool]:
    """按行提取实体像素 run，避免逐像素 BFS。"""
    row_runs: list[list[RunSpan]] = []
    found_solid = False

    for y in range(height):
        runs: list[RunSpan] = []
        row_base = y * width
        x = 0

        while x < width:
            alpha = alpha_values[row_base + x]
            if alpha <= alpha_threshold:
                x += 1
                continue

            found_solid = True
            run_start = x
            run_pixel_count = 1
            x += 1

            while x < width:
                alpha = alpha_values[row_base + x]
                if alpha <= alpha_threshold:
                    break

                run_pixel_count += 1
                x += 1

            runs.append((run_start, x - 1, run_pixel_count))

            if x < width:
                x += 1

        row_runs.append(runs)

    return row_runs, found_solid


def _extract_region_bounds_from_row_runs(row_runs: list[list[RunSpan]]) -> list[RegionBounds]:
    """基于每行 run 计算 8 连通域原始包围盒。"""
    parents: list[int] = []
    region_stats: list[RegionBounds] = []
    previous_runs: list[RunSpan] = []

    for y, runs in enumerate(row_runs):
        current_runs: list[RunSpan] = []
        previous_index = 0

        for run_start, run_end, run_pixel_count in runs:
            while (
                previous_index < len(previous_runs)
                and previous_runs[previous_index][1] + 1 < run_start
            ):
                previous_index += 1

            overlap_index = previous_index
            region_index = None

            while (
                overlap_index < len(previous_runs)
                and previous_runs[overlap_index][0] - 1 <= run_end
            ):
                candidate_index = _find_root(parents, previous_runs[overlap_index][2])
                if region_index is None:
                    region_index = candidate_index
                else:
                    region_index = _union_regions(
                        parents,
                        region_stats,
                        region_index,
                        candidate_index,
                    )
                overlap_index += 1

            if region_index is None:
                region_index = _create_region(
                    region_stats,
                    parents,
                    run_start,
                    run_end,
                    y,
                    run_pixel_count,
                )
            else:
                region_index = _find_root(parents, region_index)
                _extend_region(
                    region_stats[region_index],
                    run_start,
                    run_end,
                    y,
                    run_pixel_count,
                )

            current_runs.append((run_start, run_end, region_index))

        previous_runs = current_runs

    region_bounds = []
    for region_index, region in enumerate(region_stats):
        if _find_root(parents, region_index) != region_index:
            continue

        region_bounds.append(dict(region))

    return region_bounds


def _get_threshold_cache_key(cache_stamp: ImageCacheStamp | None, alpha_threshold: float):
    """把阈值归一化后作为缓存键的一部分。"""
    if cache_stamp is None:
        return None
    return cache_stamp, round(float(alpha_threshold), 6)


def _get_prepared_alpha_regions(image: bpy.types.Image, alpha_threshold: float) -> dict:
    """准备阈值相关的基础连通域，供多次参数调整复用。"""
    alpha_data = _get_alpha_data(image)
    transparent_pixel_count = alpha_data["transparent_pixel_count"]
    if transparent_pixel_count == 0:
        raise ValueError("Image alpha is fully opaque")

    threshold_cache_key = _get_threshold_cache_key(
        alpha_data["cache_stamp"],
        alpha_threshold,
    )
    if threshold_cache_key is not None:
        cached = _touch_cache_entry(_ALPHA_THRESHOLD_CACHE, threshold_cache_key)
        if cached is not None:
            return cached

    row_runs, found_solid = _build_row_runs(
        alpha_values=alpha_data["alpha_values"],
        width=alpha_data["width"],
        height=alpha_data["height"],
        alpha_threshold=alpha_threshold,
    )
    if not found_solid:
        raise ValueError("No alpha region is above the current threshold")

    prepared = {
        "width": alpha_data["width"],
        "height": alpha_data["height"],
        "transparent_pixel_count": transparent_pixel_count,
        "region_bounds": _extract_region_bounds_from_row_runs(row_runs),
    }
    if threshold_cache_key is not None:
        _store_cache_entry(
            _ALPHA_THRESHOLD_CACHE,
            threshold_cache_key,
            prepared,
            _ALPHA_THRESHOLD_CACHE_MAX,
        )

    return prepared


def _finalize_regions(
    region_bounds: list[RegionBounds],
    min_region_pixels: int,
    padding_pixels: int,
    merge_gap_pixels: int,
    width: int,
    height: int,
) -> tuple[list[RegionBounds], int]:
    """把基础连通域转换为当前参数下的输出矩形。"""
    ignored_small_regions = 0
    regions = []

    for region in region_bounds:
        if region["pixel_count"] < min_region_pixels:
            ignored_small_regions += 1
            continue

        regions.append(
            {
                "min_x": max(0, region["min_x"] - padding_pixels),
                "min_y": max(0, region["min_y"] - padding_pixels),
                "max_x": min(width - 1, region["max_x"] + padding_pixels),
                "max_y": min(height - 1, region["max_y"] + padding_pixels),
                "pixel_count": region["pixel_count"],
            }
        )

    regions = merge_nearby_regions(regions, merge_gap_pixels=merge_gap_pixels)
    regions.sort(key=lambda region: (-region["max_y"], region["min_x"]))
    return regions, ignored_small_regions


def find_alpha_regions(
    image: bpy.types.Image,
    alpha_threshold: float = 0.1,
    min_region_pixels: int = 16,
    padding_pixels: int = 1,
    merge_gap_pixels: int = 0,
):
    """
    从图片 alpha 通道中查找连通域并输出矩形包围盒。

    返回值中的 min/max 坐标均为像素索引，且 max 为包含边界。
    """
    prepared = _get_prepared_alpha_regions(image, alpha_threshold)
    padding_pixels = max(0, int(padding_pixels))
    min_region_pixels = max(1, int(min_region_pixels))
    merge_gap_pixels = max(0, int(merge_gap_pixels))

    regions, ignored_small_regions = _finalize_regions(
        region_bounds=prepared["region_bounds"],
        min_region_pixels=min_region_pixels,
        padding_pixels=padding_pixels,
        merge_gap_pixels=merge_gap_pixels,
        width=prepared["width"],
        height=prepared["height"],
    )

    return {
        "image": image,
        "width": prepared["width"],
        "height": prepared["height"],
        "regions": regions,
        "ignored_small_regions": ignored_small_regions,
        "transparent_pixel_count": prepared["transparent_pixel_count"],
    }


def merge_nearby_regions(regions: list[dict], merge_gap_pixels: int = 0) -> list[dict]:
    """按矩形包围盒距离合并过碎的小块。"""
    if merge_gap_pixels <= 0 or len(regions) <= 1:
        return [dict(region) for region in regions]

    merged_regions = [dict(region) for region in regions]

    changed = True
    while changed:
        changed = False
        next_regions = []
        consumed = [False] * len(merged_regions)

        for index, region in enumerate(merged_regions):
            if consumed[index]:
                continue

            current = dict(region)
            consumed[index] = True

            merged_in_pass = True
            while merged_in_pass:
                merged_in_pass = False
                for other_index, other in enumerate(merged_regions):
                    if consumed[other_index]:
                        continue
                    if not _regions_within_gap(current, other, merge_gap_pixels):
                        continue

                    current = {
                        "min_x": min(current["min_x"], other["min_x"]),
                        "min_y": min(current["min_y"], other["min_y"]),
                        "max_x": max(current["max_x"], other["max_x"]),
                        "max_y": max(current["max_y"], other["max_y"]),
                        "pixel_count": current["pixel_count"] + other["pixel_count"],
                    }
                    consumed[other_index] = True
                    merged_in_pass = True
                    changed = True

            next_regions.append(current)

        merged_regions = next_regions

    return merged_regions


def _regions_within_gap(region_a: dict, region_b: dict, merge_gap_pixels: int) -> bool:
    """判断两个矩形在给定像素距离内是否应被合并。"""
    if region_a["max_x"] + merge_gap_pixels < region_b["min_x"]:
        return False
    if region_b["max_x"] + merge_gap_pixels < region_a["min_x"]:
        return False
    if region_a["max_y"] + merge_gap_pixels < region_b["min_y"]:
        return False
    if region_b["max_y"] + merge_gap_pixels < region_a["min_y"]:
        return False
    return True
