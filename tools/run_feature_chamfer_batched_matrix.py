# -*- coding: utf-8 -*-
"""运行 Feature Chamfer batched Phase A/B 产品矩阵。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path


EXPECTED_CASE_IDS = {
    f"{fixture_label}__{object_name.lower().replace(' ', '_').replace('.', '_')}__r"
    f"{radius:.3f}".replace(".", "p")
    for fixture_label, object_name in (
        ("simple", "Extruded.002"),
        ("simple", "Solid 44"),
        ("tricky", "Solid.004"),
        ("tricky", "Solid.016"),
        ("tricky_b", "Extruded.003"),
        ("tricky_b", "Extruded.002"),
        ("mixed", "Extruded.002"),
    )
    for radius in (0.01, 0.03)
}


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


# 返回文件 SHA-256；path: 待绑定到证据的文件路径。
def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source_file:
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# 返回 Git HEAD、dirty paths 与稳定 fingerprint；repo_root: 仓库根目录。
def git_provenance(repo_root):
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    working_diff = subprocess.run(
        ["git", "diff", "--binary", "HEAD", "--", "."],
        cwd=repo_root,
        check=True,
        capture_output=True,
    ).stdout
    untracked_hashes = {}
    for status_line in status:
        if not status_line.startswith("?? "):
            continue
        relative_path = status_line[3:]
        path = repo_root / relative_path
        if path.is_file():
            untracked_hashes[relative_path] = file_sha256(path)
    dirty_payload = {
        "status": status,
        "working_diff_sha256": hashlib.sha256(working_diff).hexdigest(),
        "untracked_hashes": untracked_hashes,
    }
    return {
        "head": head,
        "dirty_paths": status,
        "dirty_fingerprint": hashlib.sha256(
            json.dumps(dirty_payload, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "working_diff_sha256": dirty_payload["working_diff_sha256"],
        "untracked_hashes": untracked_hashes,
    }


# 严格验证完整 Phase C summary；只验证结构化结果与可手工检查的 Blend，不生成或判断图片。
# summary: Blender driver 生成的完整结果；返回 (valid, errors)。
def validate_phase_c_gate_summary(summary, run_metadata=None):
    errors = []
    cases = summary.get("cases", [])
    repetitions = [item for case in cases for item in case.get("repetitions", [])]
    case_ids = [case.get("case_id") for case in cases]
    if summary.get("status") != "finished":
        errors.append("summary is not finished")
    if summary.get("run_scope") != "PHASE_GATE_FULL":
        errors.append("run scope is partial")
    if summary.get("gate_eligible") is not True:
        errors.append("summary is not gate eligible")
    if summary.get("case_count") != 14 or len(cases) != 14:
        errors.append("expected exactly 14 cases")
    if summary.get("requested_repetitions") != 3 or len(repetitions) != 42:
        errors.append("expected exactly 42 repetitions")
    if summary.get("executed_case_count") != 14:
        errors.append("executed case count mismatch")
    if summary.get("executed_repetition_count") != 42:
        errors.append("executed repetition count mismatch")
    if summary.get("passed_case_count") != 14 or summary.get("failed_case_count") != 0:
        errors.append("passed/failed case totals mismatch")
    if set(case_ids) != EXPECTED_CASE_IDS or len(case_ids) != len(set(case_ids)):
        errors.append("case IDs do not match the fixed 14-cell universe")
    if summary.get("phase_a_go") is not True:
        errors.append("Phase A is not GO")
    if summary.get("phase_b_go") is not True:
        errors.append("Phase B is not GO")
    if summary.get("phase_c_go") is not True:
        errors.append("Phase C is not GO")
    if run_metadata is not None:
        expected_git = run_metadata.get("git", {})
        if summary.get("run_id") != run_metadata.get("run_id"):
            errors.append("run ID does not match the host evidence envelope")
        if summary.get("stage") != run_metadata.get("stage"):
            errors.append("stage does not match the host evidence envelope")
        if summary.get("git_head") != expected_git.get("head"):
            errors.append("Git HEAD does not match the host evidence envelope")
        if summary.get("dirty_fingerprint") != expected_git.get(
            "dirty_fingerprint"
        ):
            errors.append(
                "dirty fingerprint does not match the host evidence envelope"
            )
        if summary.get("argv") != run_metadata.get("argv"):
            errors.append("argv does not match the host evidence envelope")
        if not summary.get("blender_version"):
            errors.append("Blender version is missing")
        fixture_hashes = summary.get("fixture_hashes")
        if not isinstance(fixture_hashes, dict) or len(fixture_hashes) != 4:
            errors.append("fixture hashes do not bind the fixed fixture universe")
        elif any(
            not isinstance(digest, str) or len(digest) != 64
            for digest in fixture_hashes.values()
        ):
            errors.append("fixture hash is not a SHA-256 digest")
    for case in cases:
        repetition_ids = [
            repetition.get("repetition")
            for repetition in case.get("repetitions", [])
        ]
        if repetition_ids != [1, 2, 3]:
            errors.append(f"case repetitions mismatch: {case.get('case_id')}")
        if case.get("status") != "PASS" or not case.get("stable"):
            errors.append(f"case failed or unstable: {case.get('case_id')}")
        if case.get("phase_c_inspection_artifacts_present") is not True:
            errors.append(f"case artifacts missing: {case.get('case_id')}")
        for repetition in case.get("repetitions", []):
            valid_repetition = (
                repetition.get("status") == "PASS"
                and repetition.get("phase_a_pass") is True
                and repetition.get("phase_b_pass") is True
                and repetition.get("phase_c_pass") is True
                and repetition.get("preview_result") == ["FINISHED"]
                and repetition.get("adapter_result") == ["FINISHED"]
                and repetition.get("preview_contract_matches_owned_curve") is True
                and repetition.get("source_unchanged") is True
                and repetition.get("producer_global_preflight") is True
                and repetition.get("regular_backend_valid") is True
                and repetition.get("unexpected_handoff_reasons") == []
                and repetition.get("macro_setback_count") == 0
                and repetition.get("derived_ports_valid") is True
                and repetition.get("fill_job_count") == 0
                and repetition.get("final_output_object_name") is None
                and not repetition.get("debug_object_names")
                and not repetition.get("debug_datablock_names")
            )
            if not valid_repetition:
                errors.append(
                    "invalid repetition: "
                    f"{case.get('case_id')}#{repetition.get('repetition')}"
                )
    return not errors, errors


# 对 artifact directory 中全部证据文件生成稳定 manifest；目录在写 manifest 前扫描。
# artifact_directory: 本次唯一 run 目录；返回相对路径、大小和 SHA-256 列表。
def artifact_manifest(artifact_directory):
    return [
        {
            "path": str(path.relative_to(artifact_directory)),
            "size": path.stat().st_size,
            "sha256": file_sha256(path),
        }
        for path in sorted(artifact_directory.rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    ]


# 写入成功或失败证据 envelope；artifact_directory/run_metadata/status/error: 本次 run 绑定信息与结果。
def write_evidence_manifest(
    artifact_directory,
    run_metadata,
    status,
    error=None,
    summary=None,
):
    manifest = {
        **run_metadata,
        "status": status,
        "error": error,
        "blender_version": (summary or {}).get("blender_version"),
        "fixture_hashes": (summary or {}).get("fixture_hashes"),
        "artifacts": artifact_manifest(artifact_directory),
    }
    (artifact_directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# 解析参数并在独立 Blender background 进程中运行 Phase A/B matrix。
# argv: 可选命令行参数；为 None 时读取当前进程 sys.argv。
def run(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--blender", help="Path to the Blender executable")
    parser.add_argument("--artifact-dir", help="Batched matrix artifact directory")
    parser.add_argument("--run-id", help="Unique evidence run identifier")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument(
        "--stage",
        choices=("PHASE_B_BATCH_PROBE", "PHASE_C_REGULAR_CORE"),
        default="PHASE_B_BATCH_PROBE",
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="cases",
        help="Run only the named matrix case; repeat for multiple cases",
    )
    args = parser.parse_args(argv)
    if args.repetitions < 1:
        parser.error("Batched matrix requires at least one repetition")
    if not args.cases and args.repetitions < 3:
        parser.error("Full batched matrix requires at least three repetitions")
    if not args.cases and args.repetitions != 3:
        parser.error("Full batched matrix requires exactly three repetitions")
    repo_root = Path(__file__).resolve().parent.parent
    blender_executable = find_blender(args.blender)
    if blender_executable is None:
        print("ERROR: Blender executable not found. Set BLENDER_EXE or pass --blender.")
        return 2
    artifact_directory = (
        Path(args.artifact_dir).expanduser().resolve()
        if args.artifact_dir
        else repo_root / "tests" / "artifacts" / "runs" / (
            args.run_id or uuid.uuid4().hex
        ) / args.stage.lower()
    )
    if artifact_directory.exists():
        print(f"ERROR: Artifact directory must not already exist: {artifact_directory}")
        return 2
    artifact_directory.mkdir(parents=True)
    run_id = args.run_id or artifact_directory.parent.name
    git_state = git_provenance(repo_root)
    environment = os.environ.copy()
    environment["HST_ADDON_ROOT"] = str(repo_root)
    environment["HST_FEATURE_CHAMFER_BATCHED_MATRIX_ARTIFACT_DIR"] = str(
        artifact_directory
    )
    environment["HST_FEATURE_CHAMFER_BATCHED_MATRIX_REPETITIONS"] = str(
        args.repetitions
    )
    environment["HST_FEATURE_CHAMFER_BATCHED_MATRIX_STAGE"] = args.stage
    environment["HST_FEATURE_CHAMFER_BATCHED_MATRIX_RUN_ID"] = run_id
    environment["HST_FEATURE_CHAMFER_BATCHED_MATRIX_GIT_HEAD"] = git_state["head"]
    environment["HST_FEATURE_CHAMFER_BATCHED_MATRIX_DIRTY_FINGERPRINT"] = (
        git_state["dirty_fingerprint"]
    )
    environment["HST_FEATURE_CHAMFER_BATCHED_MATRIX_ARGV"] = json.dumps(
        sys.argv if argv is None else [str(Path(__file__)), *argv]
    )
    if args.cases:
        environment["HST_FEATURE_CHAMFER_BATCHED_MATRIX_CASES"] = ",".join(args.cases)
    driver_path = repo_root / "tests" / "feature_chamfer_batched_matrix_driver.py"
    run_metadata = {
        "contract": (
            "HST_PHASE_C_EVIDENCE_MANIFEST_V1"
            if args.stage == "PHASE_C_REGULAR_CORE"
            else "HST_PHASE_B_EVIDENCE_MANIFEST_V1"
        ),
        "run_id": run_id,
        "git": git_state,
        "argv": sys.argv if argv is None else [str(Path(__file__)), *argv],
        "stage": args.stage,
        "blender_executable": str(blender_executable),
        "blender_executable_sha256": file_sha256(blender_executable),
        "code_hashes": {
            str(path.relative_to(repo_root)): file_sha256(path)
            for path in (
                Path(__file__),
                driver_path,
                repo_root / "utils" / "feature_chamfer_batched_finalize_utils.py",
                repo_root / "operators" / "experimental_feature_chamfer_batched_ops.py",
                repo_root / "operators" / "feature_chamfer_gn_ops.py",
                repo_root / "utils" / "feature_chamfer_gn_utils.py",
            )
        },
    }
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
        f"Running Feature Chamfer batched {args.stage} matrix: "
        f"{len(args.cases) if args.cases else 14} cells x {args.repetitions} repetitions"
    )
    completed = subprocess.run(command, cwd=repo_root, env=environment)
    results_path = artifact_directory / "results.json"
    if completed.returncode != 0:
        if args.cases and results_path.is_file():
            try:
                summary = json.loads(results_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                summary = None
            write_evidence_manifest(
                artifact_directory,
                run_metadata,
                "DIAGNOSTIC_PARTIAL",
                error=(
                    "Partial matrix runs cannot return gate success; "
                    f"Blender exited with code {completed.returncode}"
                ),
                summary=summary,
            )
            return 1
        write_evidence_manifest(
            artifact_directory,
            run_metadata,
            "FAILED",
            error=f"Blender exited with code {completed.returncode}",
        )
        return completed.returncode
    if not results_path.is_file():
        print(f"ERROR: Matrix results were not created: {results_path}")
        write_evidence_manifest(
            artifact_directory,
            run_metadata,
            "FAILED",
            error="Matrix results were not created",
        )
        return 1
    try:
        summary = json.loads(results_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"ERROR: Matrix results are invalid: {error}")
        write_evidence_manifest(
            artifact_directory,
            run_metadata,
            "FAILED",
            error=f"Matrix results are invalid: {error}",
        )
        return 1
    if args.cases:
        print("ERROR: Partial matrix runs are diagnostics and cannot return gate success")
        write_evidence_manifest(
            artifact_directory,
            run_metadata,
            "DIAGNOSTIC_PARTIAL",
            error="Partial matrix runs cannot return gate success",
            summary=summary,
        )
        return 1
    gate_valid, gate_errors = validate_phase_c_gate_summary(summary, run_metadata)
    if args.stage == "PHASE_C_REGULAR_CORE" and not gate_valid:
        print(f"ERROR: Phase C gate validation failed: {gate_errors}")
        write_evidence_manifest(
            artifact_directory,
            run_metadata,
            "FAILED",
            error=f"Phase C gate validation failed: {gate_errors}",
            summary=summary,
        )
        return 1
    write_evidence_manifest(
        artifact_directory,
        run_metadata,
        "PASSED",
        summary=summary,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
