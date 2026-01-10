# -*- coding: utf-8 -*-
"""
文件/路径操作工具函数
===================

包含路径处理、文件读写、剪贴板等功能。
"""

import os
import platform
import subprocess
import json


def make_dir(path: str) -> str:
    """
    创建文件夹

    Args:
        path: 目录路径

    Returns:
        创建的路径
    """
    if not os.path.exists(path):
        os.makedirs(path)
    return path


def normalize_path(path: str) -> str:
    """
    规范化路径

    Args:
        path: 原始路径

    Returns:
        规范化后的路径
    """
    # 规范化路径分隔符
    path = os.path.normpath(path)
    # 转换为绝对路径
    path = os.path.abspath(path)
    return path


def fix_ue_game_path(path: str) -> str:
    """
    修复 UE 路径格式

    Args:
        path: 原始路径

    Returns:
        UE 格式路径
    """
    # 确保路径以 /Game/ 开头
    if not path.startswith("/Game/"):
        path = "/Game/" + path.lstrip("/")
    # 规范化斜杠
    path = path.replace("\\", "/")
    return path


def fix_ip_input(ip_address: str) -> str:
    """
    修复 IP 地址格式

    Args:
        ip_address: 原始 IP 地址

    Returns:
        规范化的 IP 地址
    """
    # 移除多余空格
    ip_address = ip_address.strip()
    # 移除端口号（如果有）
    if ":" in ip_address:
        ip_address = ip_address.split(":")[0]
    return ip_address


def make_ue_python_script_command(file_name: str, command: str) -> str:
    """
    生成 UE Python 脚本命令

    Args:
        file_name: 脚本文件名
        command: Python 命令

    Returns:
        完整的命令字符串
    """
    script_content = f'''
import unreal
{command}
'''
    return script_content


def write_json(file_path: str, data) -> None:
    """
    写入 json 文件

    Args:
        file_path: 文件路径
        data: 要写入的数据
    """
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def read_json_from_file(file_path: str):
    """
    从文件读取 json

    Args:
        file_path: 文件路径

    Returns:
        读取的 JSON 数据
    """
    if not os.path.exists(file_path):
        return None
    
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def copy_to_clip(txt: str) -> None:
    """
    copy text string to clipboard

    Args:
        txt: 要复制的文本
    """
    import bpy
    bpy.context.window_manager.clipboard = txt


class FilePath:
    """文件路径操作工具类"""

    @staticmethod
    def open_os_path(path: str):
        """
        在系统文件管理器中打开路径

        Args:
            path: 目录路径
        """
        if platform.system() == "Windows":
            os.startfile(path)
        elif platform.system() == "Darwin":  # macOS
            subprocess.call(["open", path])
        else:  # Linux
            subprocess.call(["xdg-open", path])

    @staticmethod
    def is_path_exists(path: str) -> bool:
        """
        检查路径是否存在

        Args:
            path: 路径

        Returns:
            是否存在
        """
        return os.path.exists(path)
