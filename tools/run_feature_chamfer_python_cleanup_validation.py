# -*- coding: utf-8 -*-
"""运行 Feature Chamfer Python Bridge 清理的隔离验证。"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
from pathlib import Path


# values: 数值序列；返回中位数，空序列返回 None。
def _median(values):
    return statistics.median(values) if values else None


# runs/mode: 单阶段原始运行与阶段名；返回机器可读的阶段汇总。
def _summarize(runs, mode):
    timing_keys = (
        "operator_seconds",
        "bridge_fill_seconds",
        "bridge_cleanup_seconds",
        "deviation_kernel_seconds",
    )
    medians = {
        key: _median([run["timings"][key] for run in runs])
        for key in timing_keys
    }
    return {
        "mode": mode,
        "run_count": len(runs),
        "medians": medians,
        "chain_counts": [run["counts"] for run in runs],
        "result_contracts": [run["result_contract"] for run in runs],
        "decision_fingerprints": [
            run["decision_fingerprint"] for run in runs
        ],
        "runs": runs,
    }


# value: 正式 Operator stats；移除计时与本任务唯一允许变化的偏差展示字段。
def _semantic_value(value):
    if isinstance(value, dict):
        return {
            key: _semantic_value(item)
            for key, item in value.items()
            if not key.endswith("_seconds")
            and key not in {
                "maximum_geometric_deviation",
                "deviation_fast_path",
                "cyclic_job_side_edge_identity_tokens",
                "cyclic_source_side_edge_identity_tokens",
            }
        }
    if isinstance(value, list):
        return [_semantic_value(item) for item in value]
    return value


# oracle_summary/optimized_summary: 三次冻结与优化结果；返回逐轮完整等价审计。
def _compare_summaries(oracle_summary, optimized_summary):
    comparisons = []
    for oracle_run, optimized_run in zip(
        oracle_summary["runs"], optimized_summary["runs"]
    ):
        oracle_cleanup = oracle_run["cleanup_records"]
        optimized_cleanup = optimized_run["cleanup_records"]
        oracle_replay = oracle_run["deviation_replay"]
        optimized_replay = optimized_run["deviation_replay"]
        unmodified_indices = [
            index
            for index, record in enumerate(oracle_cleanup)
            if record.get("merged_vertex_count", 0) == 0
            and record.get("dissolved_vertex_count", 0) == 0
        ]
        modified_indices = [
            index for index in range(len(oracle_cleanup))
            if index not in set(unmodified_indices)
        ]
        oracle_modified_deviations = [
            oracle_replay[index]["maximum_deviation"]
            for index in modified_indices
        ]
        optimized_modified_deviations = [
            record["maximum_deviation"] for record in optimized_replay
        ]
        semantic_operator_stats_equal = (
            _semantic_value(oracle_run["formal_operator_stats"])
            == _semantic_value(optimized_run["formal_operator_stats"])
        )
        comparison = {
            "result_contract_equal": (
                oracle_run["result_contract"] == optimized_run["result_contract"]
            ),
            "chain_partition_equal": all(
                oracle_run["counts"][key] == optimized_run["counts"][key]
                for key in (
                    "total_chain_count",
                    "no_modification_chain_count",
                    "modified_chain_count",
                )
            ),
            "fast_path_hits_equal_unmodified_count": (
                optimized_run["counts"]["fast_path_hit_count"]
                == optimized_run["counts"]["no_modification_chain_count"]
            ),
            "remaining_calls_equal_modified_count": (
                optimized_run["counts"]["deviation_kernel_call_count"]
                == optimized_run["counts"]["modified_chain_count"]
            ),
            "oracle_unmodified_coordinates_identical": all(
                oracle_replay[index]["source_coordinates"]
                == oracle_replay[index]["cleaned_coordinates"]
                for index in unmodified_indices
            ),
            "modified_deviations_equal": (
                oracle_modified_deviations == optimized_modified_deviations
            ),
            "semantic_operator_stats_equal": semantic_operator_stats_equal,
            "health_equal": all(
                oracle_run["result_contract"][key]
                == optimized_run["result_contract"][key]
                for key in (
                    "boundary_edge_count",
                    "non_manifold_edge_count",
                    "zero_area_face_count",
                )
            ),
            "first_difference": (
                None
                if semantic_operator_stats_equal
                else "formal_operator_stats_after_allowed_field_filter"
            ),
        }
        comparison["pass"] = all(
            value is True
            for key, value in comparison.items()
            if key not in {"first_difference", "pass"}
        )
        comparisons.append(comparison)
    oracle_cleanup_median = oracle_summary["medians"]["bridge_cleanup_seconds"]
    optimized_cleanup_median = optimized_summary["medians"][
        "bridge_cleanup_seconds"
    ]
    improvement_seconds = oracle_cleanup_median - optimized_cleanup_median
    improvement_ratio = improvement_seconds / oracle_cleanup_median
    return {
        "status": "PASS" if all(item["pass"] for item in comparisons) else "STOP",
        "run_count": len(comparisons),
        "runs": comparisons,
        "performance": {
            "oracle_medians": oracle_summary["medians"],
            "optimized_medians": optimized_summary["medians"],
            "bridge_cleanup_improvement_seconds": improvement_seconds,
            "bridge_cleanup_improvement_ratio": improvement_ratio,
            "per_run_improvement_ratios": {
                key: [
                    (
                        oracle_run["timings"][key]
                        - optimized_run["timings"][key]
                    )
                    / oracle_run["timings"][key]
                    for oracle_run, optimized_run in zip(
                        oracle_summary["runs"], optimized_summary["runs"]
                    )
                ]
                for key in (
                    "operator_seconds",
                    "bridge_fill_seconds",
                    "bridge_cleanup_seconds",
                    "deviation_kernel_seconds",
                )
            },
            "bridge_cleanup_all_runs_faster": all(
                optimized_run["timings"]["bridge_cleanup_seconds"]
                < oracle_run["timings"]["bridge_cleanup_seconds"]
                for oracle_run, optimized_run in zip(
                    oracle_summary["runs"], optimized_summary["runs"]
                )
            ),
        },
        "rust_start_gate": {
            "bridge_cleanup_at_least_0_15_seconds": (
                optimized_cleanup_median >= 0.15
            ),
            "remaining_kernel_at_least_0_10_seconds": (
                optimized_summary["medians"]["deviation_kernel_seconds"] >= 0.10
            ),
            "triggered": (
                optimized_cleanup_median >= 0.15
                or optimized_summary["medians"]["deviation_kernel_seconds"] >= 0.10
            ),
            "phase_2_status": "NOT RUN / OUT OF SCOPE",
        },
    }
# argv: 可选命令行参数；逐次启动独立 Blender 并保存阶段产物。
def run(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("oracle", "optimized"), required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument(
        "--blender",
        default=r"C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe",
    )
    parser.add_argument(
        "--artifact-dir",
        default="tests/artifacts/feature_chamfer_python_bridge_cleanup",
    )
    args = parser.parse_args(argv)
    if args.repetitions < 3:
        parser.error("at least three repetitions are required")

    repo_root = Path(__file__).resolve().parent.parent
    blender_path = Path(args.blender).resolve()
    artifact_root = (repo_root / args.artifact_dir).resolve()
    stage_directory = artifact_root / args.mode
    stage_directory.mkdir(parents=True, exist_ok=True)
    driver_path = repo_root / "tests" / "feature_chamfer_python_cleanup_driver.py"
    fixture_path = (
        repo_root
        / "tests"
        / "fixtures"
        / "feature-chamfer-topology-defect-mixed.blend"
    )
    runs = []
    for repetition in range(1, args.repetitions + 1):
        run_directory = stage_directory / f"run-{repetition:02d}"
        run_directory.mkdir(parents=True, exist_ok=True)
        output_json = run_directory / "result.json"
        output_blend = run_directory / "result.blend"
        log_path = run_directory / "blender.log"
        environment = os.environ.copy()
        environment.update(
            HST_ADDON_ROOT=str(repo_root),
            HST_CLEANUP_VALIDATION_MODE=args.mode,
            HST_CLEANUP_VALIDATION_FIXTURE=str(fixture_path),
            HST_CLEANUP_VALIDATION_OUTPUT_JSON=str(output_json),
            HST_CLEANUP_VALIDATION_OUTPUT_BLEND=str(output_blend),
        )
        command = [
            str(blender_path),
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "--python-exit-code",
            "1",
            "--python",
            str(driver_path),
        ]
        completed = subprocess.run(
            command,
            cwd=repo_root,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        log_path.write_text(
            completed.stdout + "\n--- STDERR ---\n" + completed.stderr,
            encoding="utf-8",
        )
        if completed.returncode != 0 or not output_json.exists():
            raise RuntimeError(
                f"Blender validation run {repetition} failed; see {log_path}"
            )
        runs.append(json.loads(output_json.read_text(encoding="utf-8")))

    stage_summary = _summarize(runs, args.mode)
    (stage_directory / "summary.json").write_text(
        json.dumps(stage_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    environment_summary = {
        "platform": platform.platform(),
        "processor": platform.processor(),
        "python": platform.python_version(),
        "blender": str(blender_path),
        "fixture": str(fixture_path),
        "object": "Extruded.002",
        "radius": 0.01,
        "formal_ui_entry": "Feature Chamfer",
        "formal_operator": "hst.feature_chamfer_gn",
    }
    (artifact_root / "environment.json").write_text(
        json.dumps(environment_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    oracle_summary_path = artifact_root / "oracle" / "summary.json"
    optimized_summary_path = artifact_root / "optimized" / "summary.json"
    if oracle_summary_path.exists() and optimized_summary_path.exists():
        comparison = _compare_summaries(
            json.loads(oracle_summary_path.read_text(encoding="utf-8")),
            json.loads(optimized_summary_path.read_text(encoding="utf-8")),
        )
        (artifact_root / "comparison.json").write_text(
            json.dumps(comparison, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (artifact_root / "summary.json").write_text(
            json.dumps(
                {
                    "phase_0": "PASS",
                    "phase_1": comparison["status"],
                    "phase_2": "NOT RUN / OUT OF SCOPE",
                    "comparison": comparison,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    print(json.dumps(stage_summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
