#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from pathlib import Path


DEFAULT_BLENDER = Path("/Applications/Blender.app/Contents/MacOS/Blender")


# 执行单个外部命令并保留完整输出，失败时携带上下文终止。
# command: 已拆分的命令参数列表；返回标准输出文本。
def run_command(command):
    completed = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Command failed ({completed.returncode}): {' '.join(command)}\n"
            f"{completed.stdout}"
        )
    return completed.stdout


# 确认交付 artifact 存在且非空。
# path: 待检查路径；校验失败时抛出异常。
def require_nonempty(path):
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError(f"Expected non-empty artifact: {path}")


# 编排版本检查、正式 runtime 捕获、可视化与 manifest 一致性验证。
# 命令行参数: Blender、fixture、source Mesh、Radius 与输出目录。
def main():
    parser = argparse.ArgumentParser(
        description="Capture and visualize actual Feature Chamfer Bridge pairs."
    )
    parser.add_argument("--blender", type=Path, default=DEFAULT_BLENDER)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--object", dest="object_name", required=True)
    parser.add_argument("--radius", type=float, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()

    blender = arguments.blender.resolve()
    fixture = arguments.fixture.resolve()
    output_directory = arguments.output_dir.resolve()
    if not blender.is_file():
        raise RuntimeError(f"Blender executable not found: {blender}")
    if not fixture.is_file():
        raise RuntimeError(f"Fixture not found: {fixture}")
    output_directory.mkdir(parents=True, exist_ok=True)

    scripts_directory = Path(__file__).resolve().parent
    capture_script = scripts_directory / "capture_runtime_bridge_pairs.py"
    render_script = scripts_directory / "render_runtime_bridge_pairs.py"
    capture_path = output_directory / "runtime-pairs.json"
    manifest_path = output_directory / "pair-manifest.json"
    blend_path = output_directory / "bridge-pairs.blend"
    summary_path = output_directory / "run-summary.json"

    version_output = run_command([str(blender), "--version"])
    capture_log = run_command(
        [
            str(blender),
            "--background",
            "--factory-startup",
            "--python",
            str(capture_script),
            "--",
            str(fixture),
            arguments.object_name,
            str(arguments.radius),
            str(capture_path),
        ]
    )
    render_log = run_command(
        [
            str(blender),
            "--background",
            "--factory-startup",
            "--python",
            str(render_script),
            "--",
            str(fixture),
            str(capture_path),
            str(blend_path),
            str(manifest_path),
        ]
    )

    for path in (capture_path, manifest_path, blend_path):
        require_nonempty(path)
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pair_count = int(capture.get("pair_count", 0))
    if capture.get("preview_result") != ["FINISHED"]:
        raise RuntimeError(f"Preview did not finish: {capture.get('preview_result')}")
    if capture.get("finalize_result") != ["FINISHED"]:
        raise RuntimeError(
            f"Finalize did not finish: {capture.get('finalize_result')}"
        )
    if pair_count <= 0 or manifest.get("pair_count") != pair_count:
        raise RuntimeError("Pair count is empty or inconsistent")
    groups = manifest.get("groups", [])
    if [group.get("runtime_index") for group in groups] != list(
        range(1, pair_count + 1)
    ):
        raise RuntimeError("Runtime pair indices are not continuous")
    for group_index, group in enumerate(groups, start=1):
        sides = group.get("sides", [])
        expected_names = [f"{group_index}a", f"{group_index}b"]
        if len(sides) != 2 or [side.get("name") for side in sides] != expected_names:
            raise RuntimeError(f"Pair {group_index} does not contain {expected_names}")

    summary = {
        "status": "passed",
        "blender_version": version_output.splitlines()[0],
        "fixture": str(fixture),
        "object_name": arguments.object_name,
        "radius": arguments.radius,
        "pair_count": pair_count,
        "artifacts": {
            "blend": str(blend_path),
            "manifest": str(manifest_path),
            "capture": str(capture_path),
        },
        "logs": {
            "capture_saved": "Feature Chamfer finished" in capture_log,
            "artifact_saved": "Saved" in render_log,
        },
    }
    if not all(summary["logs"].values()):
        raise RuntimeError(f"Blender logs lack completion markers: {summary['logs']}")
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
