# -*- coding: utf-8 -*-
"""Headless Blender regression test runner for HardsurfaceGameAssetToolkit."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def find_blender_explicit(cli_value: str | None) -> Path | None:
    if cli_value:
        path = Path(cli_value)
        return path if path.exists() else None

    env_value = os.environ.get("BLENDER_EXE")
    if env_value:
        path = Path(env_value)
        return path if path.exists() else None

    candidates = [
        Path(r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"),
        Path(r"C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe"),
        Path(r"E:\Portable Apps\Art\BlenderBuilds\stable\blender-5.1\blender.exe"),
        Path(r"E:\Portable Apps\Art\BlenderBuilds\stable\blender-4.1.1-stable.e1743a0317bc\blender.exe"),
        Path(r"E:\Portable Apps\Art\BlenderBuilds\stable\blender-4.0.2-stable.9be62e85b727\blender.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def run() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--blender", help="Path to blender.exe")
    parser.add_argument("--artifact-dir", help="Artifact output directory")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    blender_exe = find_blender_explicit(args.blender)
    if blender_exe is None:
        print("ERROR: Blender executable not found. Set BLENDER_EXE or pass --blender.")
        return 2

    artifact_dir = Path(args.artifact_dir) if args.artifact_dir else repo_root / "tests" / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    test_driver = repo_root / "tests" / "blender_test_driver.py"
    results_path = artifact_dir / "results.json"
    env = os.environ.copy()
    env["HST_ADDON_ROOT"] = str(repo_root)
    env["HST_TEST_ARTIFACT_DIR"] = str(artifact_dir)
    env["HST_TEST_RESULTS"] = str(results_path)

    command = [
        str(blender_exe),
        "--background",
        "--factory-startup",
        "--disable-autoexec",
        "--python",
        str(test_driver),
    ]

    print(f"Using Blender: {blender_exe}")
    print("Running headless regression tests...")
    completed = subprocess.run(command, cwd=repo_root, env=env)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(run())
