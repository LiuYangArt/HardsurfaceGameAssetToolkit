# -*- coding: utf-8 -*-
"""Project-local wrapper for HST Blender regression tests."""

from pathlib import Path
import subprocess
import sys


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    command = [sys.executable, str(repo_root / "tools" / "run_blender_tests.py"), *sys.argv[1:]]
    return subprocess.call(command, cwd=repo_root)


if __name__ == "__main__":
    raise SystemExit(main())
