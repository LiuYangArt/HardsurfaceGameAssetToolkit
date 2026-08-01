# -*- coding: utf-8 -*-
"""统一运行 Feature Chamfer FeatureGraph Python/native 最终 A/B。"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
from pathlib import Path


# payload: 任意嵌套诊断；移除计时与后端标签后返回语义值。
def _semantic_value(payload):
    if isinstance(payload, dict):
        return {
            key: _semantic_value(value)
            for key, value in payload.items()
            if not key.endswith("_seconds")
            and key not in {
                "backend",
                "backend_actual",
                "backend_requested",
                "feature_graph_backend",
                "feature_graph_native_adapter_seconds",
                "feature_graph_native_solver_seconds",
                "repetition",
            }
        }
    if isinstance(payload, list):
        return [_semantic_value(value) for value in payload]
    return payload


# python_payload/native_payload: 两个后端的原始汇总；返回逐轮等价与性能结论。
def _compare(python_payload, native_payload):
    if len(python_payload["runs"]) != len(native_payload["runs"]):
        raise RuntimeError("Python/native repetition counts differ")
    comparisons = []
    for python_run, native_run in zip(
        python_payload["runs"], native_payload["runs"]
    ):
        checks = {
            "operation_result_equal": (
                python_run["operation_result"] == native_run["operation_result"]
            ),
            "mesh_equal": python_run["mesh"] == native_run["mesh"],
            "feature_groups_equal": (
                python_run["feature_groups"] == native_run["feature_groups"]
                and python_run["feature_groups_fingerprint"]
                == native_run["feature_groups_fingerprint"]
            ),
            "vertex_matching_equal": (
                python_run["vertex_matching"] == native_run["vertex_matching"]
                and python_run["vertex_matching_fingerprint"]
                == native_run["vertex_matching_fingerprint"]
            ),
            "chamfer_plan_equal": (
                python_run["chamfer_plan"] == native_run["chamfer_plan"]
                and python_run["chamfer_plan_fingerprint"]
                == native_run["chamfer_plan_fingerprint"]
            ),
            "feature_graph_semantics_equal": (
                _semantic_value(python_run["feature_graph"])
                == _semantic_value(native_run["feature_graph"])
            ),
        }
        comparisons.append(
            {
                "repetition": python_run["repetition"],
                "checks": checks,
                "pass": all(checks.values()),
                "timings": {
                    "python": python_run["timings"],
                    "native": native_run["timings"],
                },
            }
        )
    timing_keys = (
        "feature_graph_seconds",
        "operator_seconds",
        "operator_wall_seconds",
    )
    performance = {}
    for key in timing_keys:
        python_median = statistics.median(
            run["timings"][key] for run in python_payload["runs"]
        )
        native_median = statistics.median(
            run["timings"][key] for run in native_payload["runs"]
        )
        performance[key] = {
            "python_median": python_median,
            "native_median": native_median,
            "improvement_seconds": python_median - native_median,
            "improvement_ratio": (
                (python_median - native_median) / python_median
                if python_median > 0.0
                else None
            ),
        }
    correctness_pass = (
        python_payload["status"] == "PASS"
        and native_payload["status"] == "PASS"
        and all(item["pass"] for item in comparisons)
    )
    return {
        "status": "PASS" if correctness_pass else "STOP",
        "correctness_pass": correctness_pass,
        "comparisons": comparisons,
        "performance": performance,
        "python_contract_fingerprint": python_payload["contract_fingerprint"],
        "native_contract_fingerprint": native_payload["contract_fingerprint"],
    }


# backend/args/repo_root/artifact_root: 后端与命令行上下文；运行独立 Blender 并返回 JSON。
def _run_backend(backend, args, repo_root, artifact_root):
    output_json = artifact_root / f"{backend}.json"
    log_path = artifact_root / f"{backend}.log"
    environment = os.environ.copy()
    environment.update(
        HST_ADDON_ROOT=str(repo_root),
        HST_FEATURE_GRAPH_AB_BACKEND=backend,
        HST_FEATURE_GRAPH_AB_FIXTURE=str(
            Path(args.fixture).resolve()
        ),
        HST_FEATURE_GRAPH_AB_OBJECT=args.object,
        HST_FEATURE_GRAPH_AB_RADIUS=str(args.radius),
        HST_FEATURE_GRAPH_AB_OUTPUT_JSON=str(output_json),
        HST_FEATURE_GRAPH_AB_REPETITIONS=str(args.repetitions),
    )
    command = [
        str(Path(args.blender).resolve()),
        "--background",
        "--factory-startup",
        "--disable-autoexec",
        "--python-exit-code",
        "1",
        "--python",
        str(repo_root / "tests" / "feature_chamfer_feature_graph_final_ab_driver.py"),
    ]
    completed = subprocess.run(
        command,
        cwd=repo_root,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=args.timeout,
        check=False,
    )
    log_path.write_text(
        "COMMAND: " + subprocess.list2cmdline(command)
        + "\n\nSTDOUT\n" + completed.stdout
        + "\n\nSTDERR\n" + completed.stderr,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"{backend} Blender run failed with exit code {completed.returncode}; "
            f"see {log_path}"
        )
    if not output_json.exists():
        raise RuntimeError(f"{backend} Blender run produced no JSON; see {log_path}")
    return json.loads(output_json.read_text(encoding="utf-8"))


# argv: 可选命令行参数；顺序运行两个正式后端并写出统一比较报告。
def run(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--backend",
        choices=("both", "auto", "python", "native"),
        default="both",
    )
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument(
        "--fixture",
        default="tests/fixtures/feature-chamfer-topology-defect-mixed.blend",
    )
    parser.add_argument("--object", default="Extruded.002")
    parser.add_argument("--radius", type=float, default=0.01)
    parser.add_argument(
        "--blender",
        default=r"C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe",
    )
    parser.add_argument(
        "--artifact-dir",
        default="tests/artifacts/feature_chamfer_feature_graph_final_ab",
    )
    args = parser.parse_args(argv)
    if args.repetitions < 1:
        parser.error("repetitions must be positive")
    repo_root = Path(__file__).resolve().parent.parent
    artifact_root = (repo_root / args.artifact_dir).resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)
    payloads = {
        backend: _run_backend(backend, args, repo_root, artifact_root)
        for backend in (
            ("python", "native")
            if args.backend == "both"
            else (args.backend,)
        )
    }
    if args.backend == "both":
        result = _compare(payloads["python"], payloads["native"])
        result_path = artifact_root / "comparison.json"
    else:
        result = payloads[args.backend]
        result_path = artifact_root / f"{args.backend}.json"
    result.update(
        fixture=str(Path(args.fixture)),
        object=args.object,
        radius=args.radius,
        repetitions=args.repetitions,
    )
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(run())
