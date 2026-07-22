# -*- coding: utf-8 -*-
"""运行 Feature Chamfer 目标 Operator 的产品矩阵。"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path


# 定位 Blender 可执行文件，支持 CLI、环境变量、PATH 与 macOS/Windows 常见位置。
# cli_value: --blender 显式路径；为 None 时自动发现。
def find_blender(cli_value):
    if cli_value:
        explicit_path = Path(cli_value).expanduser()
        return explicit_path if explicit_path.exists() else None

    environment_value = os.environ.get("BLENDER_EXE")
    if environment_value:
        environment_path = Path(environment_value).expanduser()
        return environment_path if environment_path.exists() else None

    path_value = shutil.which("blender")
    if path_value:
        return Path(path_value)

    candidates = (
        Path("/Applications/Blender.app/Contents/MacOS/Blender"),
        Path.home() / "Applications" / "Blender.app" / "Contents" / "MacOS" / "Blender",
        Path(r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"),
        Path(r"C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe"),
    )
    return next((candidate for candidate in candidates if candidate.exists()), None)


# 解析参数并在独立 Blender background 进程中运行产品矩阵。
# argv: 可选命令行参数；为 None 时读取当前进程的 sys.argv。
def run(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--blender", help="Path to the Blender executable")
    parser.add_argument("--artifact-dir", help="Product matrix artifact directory")
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args(argv)

    if args.repetitions < 3:
        parser.error("Phase 2 requires at least three repetitions per matrix cell")

    repo_root = Path(__file__).resolve().parent.parent
    blender_executable = find_blender(args.blender)
    if blender_executable is None:
        print("ERROR: Blender executable not found. Set BLENDER_EXE or pass --blender.")
        return 2

    artifact_directory = (
        Path(args.artifact_dir).expanduser().resolve()
        if args.artifact_dir
        else repo_root / "tests" / "artifacts" / "feature_chamfer_matrix"
    )
    artifact_directory.mkdir(parents=True, exist_ok=True)

    environment = os.environ.copy()
    environment["HST_ADDON_ROOT"] = str(repo_root)
    environment["HST_FEATURE_CHAMFER_MATRIX_ARTIFACT_DIR"] = str(artifact_directory)
    environment["HST_FEATURE_CHAMFER_MATRIX_REPETITIONS"] = str(args.repetitions)
    driver_path = repo_root / "tests" / "feature_chamfer_matrix_driver.py"
    command = [
        str(blender_executable),
        "--background",
        "--factory-startup",
        "--disable-autoexec",
        "--python-exit-code",
        "1",
        "--python",
        str(driver_path),
    ]

    print(f"Using Blender: {blender_executable}")
    print(
        "Running Feature Chamfer product matrix: "
        f"14 cells x {args.repetitions} repetitions"
    )
    completed = subprocess.run(command, cwd=repo_root, env=environment)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(run())
