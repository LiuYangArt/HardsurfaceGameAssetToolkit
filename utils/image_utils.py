# -*- coding: utf-8 -*-
"""
图像分析工具函数
===============

包含材质贴图提取、alpha 读取和连通域分析功能。
"""

from collections import deque

import bpy


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


def read_image_alpha(image: bpy.types.Image) -> tuple[int, int, list[float]]:
    """读取图片 alpha 通道。"""
    if image is None:
        raise ValueError("Image texture node has no image datablock")

    width, height = image.size
    channels = int(image.channels)
    if width <= 0 or height <= 0:
        raise ValueError("Image has invalid size")
    if channels < 4:
        raise ValueError("Image must contain an alpha channel")

    pixel_count = width * height
    pixels = [0.0] * (pixel_count * channels)
    image.pixels.foreach_get(pixels)
    alpha_values = [pixels[index + 3] for index in range(0, len(pixels), channels)]
    return width, height, alpha_values


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
    width, height, alpha_values = read_image_alpha(image)
    pixel_count = width * height

    transparent_pixel_count = sum(1 for alpha in alpha_values if alpha < 0.999)
    if transparent_pixel_count == 0:
        raise ValueError("Image alpha is fully opaque")

    solid_mask = [alpha > alpha_threshold for alpha in alpha_values]
    if not any(solid_mask):
        raise ValueError("No alpha region is above the current threshold")

    visited = bytearray(pixel_count)
    regions = []
    ignored_small_regions = 0
    padding_pixels = max(0, int(padding_pixels))
    min_region_pixels = max(1, int(min_region_pixels))
    neighbors = (
        (-1, -1), (0, -1), (1, -1),
        (-1, 0),            (1, 0),
        (-1, 1),  (0, 1),   (1, 1),
    )

    for start_index in range(pixel_count):
        if visited[start_index] or not solid_mask[start_index]:
            continue

        visited[start_index] = 1
        queue = deque([start_index])
        min_x = width
        min_y = height
        max_x = -1
        max_y = -1
        region_pixel_count = 0

        while queue:
            current_index = queue.popleft()
            x = current_index % width
            y = current_index // width

            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)
            region_pixel_count += 1

            for dx, dy in neighbors:
                nx = x + dx
                ny = y + dy
                if nx < 0 or nx >= width or ny < 0 or ny >= height:
                    continue

                neighbor_index = ny * width + nx
                if visited[neighbor_index] or not solid_mask[neighbor_index]:
                    continue

                visited[neighbor_index] = 1
                queue.append(neighbor_index)

        if region_pixel_count < min_region_pixels:
            ignored_small_regions += 1
            continue

        regions.append(
            {
                "min_x": max(0, min_x - padding_pixels),
                "min_y": max(0, min_y - padding_pixels),
                "max_x": min(width - 1, max_x + padding_pixels),
                "max_y": min(height - 1, max_y + padding_pixels),
                "pixel_count": region_pixel_count,
            }
        )

    regions = merge_nearby_regions(regions, merge_gap_pixels=max(0, int(merge_gap_pixels)))
    regions.sort(key=lambda region: (-region["max_y"], region["min_x"]))

    return {
        "image": image,
        "width": width,
        "height": height,
        "regions": regions,
        "ignored_small_regions": ignored_small_regions,
        "transparent_pixel_count": transparent_pixel_count,
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
