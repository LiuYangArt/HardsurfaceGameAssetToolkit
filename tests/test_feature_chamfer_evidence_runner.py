# -*- coding: utf-8 -*-
"""Feature Chamfer evidence runner 的 host-side fail-closed contracts。"""

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
RUNNER_PATH = REPO_ROOT / "tools" / "run_feature_chamfer_batched_matrix.py"
SPEC = importlib.util.spec_from_file_location("hst_batched_matrix_runner", RUNNER_PATH)
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


# 构造严格 14×3 的最小 gate summary；无参数，返回可供负向 mutation 的字典。
def make_valid_summary():
    cases = []
    for case_id in sorted(RUNNER.EXPECTED_CASE_IDS):
        repetitions = [
            {
                "repetition": repetition_index,
                "status": "PASS",
                "phase_a_pass": True,
                "phase_b_pass": True,
                "phase_c_pass": True,
                "preview_result": ["FINISHED"],
                "adapter_result": ["FINISHED"],
                "preview_contract_matches_owned_curve": True,
                "source_unchanged": True,
                "debug_object_names": [],
                "debug_datablock_names": [],
            }
            for repetition_index in (1, 2, 3)
        ]
        cases.append(
            {
                "case_id": case_id,
                "status": "PASS",
                "stable": True,
                "phase_c_artifacts_present": True,
                "repetitions": repetitions,
            }
        )
    return {
        "status": "finished",
        "run_scope": "PHASE_GATE_FULL",
        "gate_eligible": True,
        "case_count": 14,
        "requested_repetitions": 3,
        "executed_case_count": 14,
        "executed_repetition_count": 42,
        "passed_case_count": 14,
        "failed_case_count": 0,
        "phase_a_go": True,
        "phase_b_go": True,
        "phase_c_go": True,
        "cases": cases,
    }


class FeatureChamferEvidenceRunnerTests(unittest.TestCase):
    def test_valid_phase_c_gate_summary(self):
        valid, errors = RUNNER.validate_phase_c_gate_summary(make_valid_summary())
        self.assertTrue(valid, errors)

    def test_fake_green_mutations_fail_closed(self):
        mutations = (
            lambda summary: summary.update(status="running"),
            lambda summary: summary.update(run_scope="DIAGNOSTIC_PARTIAL"),
            lambda summary: summary.update(case_count=13),
            lambda summary: summary.update(executed_repetition_count=41),
            lambda summary: summary.update(phase_a_go=False),
            lambda summary: summary.update(phase_b_go=False),
            lambda summary: summary["cases"][0].update(status="FAIL"),
            lambda summary: summary["cases"][0]["repetitions"][0].update(
                adapter_result=["CANCELLED"]
            ),
            lambda summary: summary["cases"][0]["repetitions"][0].update(
                source_unchanged=False
            ),
            lambda summary: summary["cases"][0]["repetitions"][0].update(
                debug_datablock_names=["HST_PhaseC_Debug"]
            ),
            lambda summary: summary["cases"][1].update(
                case_id=summary["cases"][0]["case_id"]
            ),
            lambda summary: summary["cases"][0].update(case_id="unknown:case"),
            lambda summary: summary["cases"][0]["repetitions"].pop(),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                summary = copy.deepcopy(make_valid_summary())
                mutate(summary)
                self.assertFalse(
                    RUNNER.validate_phase_c_gate_summary(summary)[0],
                    summary,
                )

    def test_existing_artifact_directory_is_rejected_before_blender(self):
        with tempfile.TemporaryDirectory() as directory:
            exit_code = RUNNER.run(
                [
                    "--artifact-dir",
                    directory,
                    "--blender",
                    "/Applications/Blender.app/Contents/MacOS/Blender",
                    "--stage",
                    "PHASE_C_REGULAR_CORE",
                ]
            )
        self.assertEqual(exit_code, 2)

    def test_failed_run_manifest_binds_command_and_code(self):
        with tempfile.TemporaryDirectory() as parent_directory:
            artifact_directory = Path(parent_directory) / "failed-run"
            run_metadata = {
                "contract": "HST_PHASE_C_EVIDENCE_MANIFEST_V1",
                "run_id": "failed-run",
                "git": {"head": "abc", "dirty_fingerprint": "def"},
                "argv": ["runner", "--stage", "PHASE_C_REGULAR_CORE"],
                "stage": "PHASE_C_REGULAR_CORE",
                "code_hashes": {"runner.py": "123"},
            }
            artifact_directory.mkdir()
            RUNNER.write_evidence_manifest(
                artifact_directory,
                run_metadata,
                "FAILED",
                error="Blender exited before fixture load",
            )
            manifest = json.loads(
                (artifact_directory / "manifest.json").read_text(encoding="utf-8")
            )
        self.assertEqual(manifest["status"], "FAILED")
        self.assertEqual(manifest["run_id"], "failed-run")
        self.assertEqual(manifest["code_hashes"], {"runner.py": "123"})
        self.assertIn("before fixture load", manifest["error"])


if __name__ == "__main__":
    unittest.main()
