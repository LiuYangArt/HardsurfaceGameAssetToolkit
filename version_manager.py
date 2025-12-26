"""
版本管理器 - 用于管理 blender_manifest.toml 中的版本号

用法:
    python version_manager.py info     - 显示当前版本和下一版本信息
    python version_manager.py update <type> - 更新版本号 (patch/minor/major)
    python version_manager.py get      - 获取当前版本 (用于批处理脚本)
"""

import re
import sys
from pathlib import Path

MANIFEST_FILE = Path(__file__).parent / "blender_manifest.toml"


def get_version() -> str:
    """从 blender_manifest.toml 读取版本号"""
    content = MANIFEST_FILE.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if match:
        return match.group(1)
    raise ValueError("未找到版本号")


def set_version(new_version: str) -> None:
    """更新 blender_manifest.toml 中的版本号"""
    content = MANIFEST_FILE.read_text(encoding="utf-8")
    new_content = re.sub(
        r'^(version\s*=\s*)"[^"]+"',
        f'\\1"{new_version}"',
        content,
        count=1,
        flags=re.MULTILINE,
    )
    MANIFEST_FILE.write_text(new_content, encoding="utf-8")


def parse_version(v_str: str) -> tuple[int, int, int]:
    """解析版本号字符串为元组"""
    parts = v_str.split(".")
    return int(parts[0]), int(parts[1]), int(parts[2])


def bump_version(v_str: str, v_type: str) -> str:
    """根据类型增加版本号"""
    major, minor, patch = parse_version(v_str)
    if v_type == "patch":
        patch += 1
    elif v_type == "minor":
        minor += 1
        patch = 0
    elif v_type == "major":
        major += 1
        minor = 0
        patch = 0
    return f"{major}.{minor}.{patch}"


def main():
    if len(sys.argv) < 2:
        print("用法: python version_manager.py [info|update <type>|get]")
        sys.exit(1)

    command = sys.argv[1]

    if command == "info":
        current = get_version()
        ma, mi, pa = parse_version(current)
        next_patch = f"{ma}.{mi}.{pa + 1}"
        next_minor = f"{ma}.{mi + 1}.0"
        next_major = f"{ma + 1}.0.0"

        # 输出批处理可用的变量
        with open("versions.bat", "w", encoding="utf-8") as f:
            f.write(f"set CURRENT_VERSION={current}\n")
            f.write(f"set NEXT_PATCH={next_patch}\n")
            f.write(f"set NEXT_MINOR={next_minor}\n")
            f.write(f"set NEXT_MAJOR={next_major}\n")

    elif command == "update":
        if len(sys.argv) < 3:
            print("用法: python version_manager.py update [patch|minor|major]")
            sys.exit(1)

        v_type = sys.argv[2]
        current = get_version()
        new_v = bump_version(current, v_type)
        set_version(new_v)
        print(f"版本已更新: {current} -> {new_v}")

    elif command == "get":
        current = get_version()
        with open("new_version.bat", "w", encoding="utf-8") as f:
            f.write(f"set NEW_VERSION={current}\n")


if __name__ == "__main__":
    main()
