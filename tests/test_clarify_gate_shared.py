import json
import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from clarify_gate_shared import (
    DOMAIN_FRAME_REQUIRED_KEYS,
    clarify_focus_point_closure_errors,
    clarify_state_constraint_signal_scn_focus_errors,
    domain_frame_missing_required_keys,
    generated_scenarios_strict_errors,
    scenario_coverage_strict_errors,
)


class DomainFrameRequiredKeysTests(unittest.TestCase):
    def test_missing_required_keys_one_omission(self) -> None:
        for omit in DOMAIN_FRAME_REQUIRED_KEYS:
            data = {k: [] for k in DOMAIN_FRAME_REQUIRED_KEYS if k != omit}
            self.assertEqual(domain_frame_missing_required_keys(data), [omit], omit)

    def test_missing_required_keys_all_present(self) -> None:
        data = {k: [] for k in DOMAIN_FRAME_REQUIRED_KEYS}
        self.assertEqual(domain_frame_missing_required_keys(data), [])


class ClarifyGateSharedFocusTests(unittest.TestCase):
    def test_focus_points_json_requires_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            fd = Path(tmp_dir)
            (fd / "focus-points.json").write_text(
                '{"version":"1.0","items":[{"id":"FP-1","text":"user asked X"}]}\n',
                encoding="utf-8",
            )
            errs = clarify_focus_point_closure_errors(fd)
            self.assertTrue(any("maps_to" in e or "closure_ref" in e for e in errs))

    def test_focus_section_bullet_without_ref_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            fd = Path(tmp_dir)
            (fd / "clarification-notes.md").write_text(
                "## Domain Frame\n\nx\n\n## Focus Points\n- user wants magic\n",
                encoding="utf-8",
            )
            errs = clarify_focus_point_closure_errors(fd)
            self.assertTrue(any("REQ-" in e or "Focus Points" in e for e in errs))

    def test_focus_section_with_refs_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            fd = Path(tmp_dir)
            (fd / "clarification-notes.md").write_text(
                "## Domain Frame\n\nx\n\n## Focus Points\n"
                "- delete→insert 同键 → REQ-001, SCN-002\n",
                encoding="utf-8",
            )
            self.assertEqual(clarify_focus_point_closure_errors(fd), [])


class CanonicalScenarioContractTests(unittest.TestCase):
    def test_generated_scenarios_rejects_empty_object_rows(self) -> None:
        errors = generated_scenarios_strict_errors({"scenarios": [{}]})
        self.assertTrue(any("empty object" in error for error in errors))

    def test_generated_scenarios_rejects_non_object_rows(self) -> None:
        errors = generated_scenarios_strict_errors({"scenarios": ["placeholder"]})
        self.assertTrue(any("only JSON objects" in error for error in errors))

    def test_generated_scenarios_requires_confidence_when_placeholder_has_content(self) -> None:
        errors = generated_scenarios_strict_errors(
            {
                "scenarios": [
                    {
                        "scenario_id": "SCN-001",
                    }
                ]
            }
        )
        self.assertTrue(any("must declare `confidence`" in error for error in errors))

    def test_generated_scenarios_requires_confidence_when_only_source_signals_exist(self) -> None:
        errors = generated_scenarios_strict_errors(
            {
                "scenarios": [
                    {
                        "source_signals": ["constraint_conflicts[0]"],
                    }
                ]
            }
        )
        self.assertTrue(any("must declare `confidence`" in error for error in errors))

    def test_generated_scenarios_requires_confidence_for_noncanonical_note_placeholder(self) -> None:
        errors = generated_scenarios_strict_errors(
            {
                "scenarios": [
                    {
                        "note": "todo later",
                    }
                ]
            }
        )
        self.assertTrue(any("must declare `confidence`" in error for error in errors))

    def test_generated_scenarios_high_confidence_requires_strict_fields(self) -> None:
        errors = generated_scenarios_strict_errors(
            {
                "scenarios": [
                    {
                        "confidence": "high",
                        "scenario_id": "SCN-001",
                    }
                ]
            }
        )
        self.assertTrue(any("pattern" in error for error in errors))
        self.assertTrue(any("source_signals" in error for error in errors))

    def test_generated_scenarios_rejects_duplicate_scenario_ids(self) -> None:
        errors = generated_scenarios_strict_errors(
            {
                "scenarios": [
                    {
                        "confidence": "high",
                        "scenario_id": "SCN-001",
                        "pattern": "p1",
                        "source_signals": ["state_transition_scenarios[0]"],
                        "scenario": "A",
                        "why_it_matters": "A",
                        "expected_followup": "REQ",
                    },
                    {
                        "confidence": "medium",
                        "scenario_id": "SCN-001",
                        "pattern": "p2",
                        "source_signals": ["constraint_conflicts[0]"],
                        "scenario": "B",
                        "why_it_matters": "B",
                        "expected_followup": "DEC",
                    },
                ]
            }
        )
        self.assertTrue(any("duplicates `scenario_id`" in error for error in errors))

    def test_generated_scenarios_low_confidence_skips_strict_fields(self) -> None:
        self.assertEqual(
            generated_scenarios_strict_errors(
                {
                    "scenarios": [
                        {
                            "confidence": "low",
                            "scenario_id": "",
                        }
                    ]
                }
            ),
            [],
        )

    def test_scenario_coverage_allows_dropped_invalid_without_mapped_to(self) -> None:
        self.assertEqual(
            scenario_coverage_strict_errors(
                {
                    "epic_id": "sh-1-demo",
                    "version": "1.0",
                    "scenarios": [
                        {
                            "scenario_id": "SCN-001",
                            "status": "dropped_invalid",
                        }
                    ],
                }
            ),
            [],
        )

    def test_scenario_coverage_requires_signals_array_when_present(self) -> None:
        errors = scenario_coverage_strict_errors(
            {
                "epic_id": "sh-1-demo",
                "version": "1.0",
                "scenarios": [],
                "signals": {},
            }
        )
        self.assertTrue(any("signals" in error for error in errors))

    def test_scenario_coverage_rejects_duplicate_scenario_ids(self) -> None:
        errors = scenario_coverage_strict_errors(
            {
                "epic_id": "sh-1-demo",
                "version": "1.0",
                "scenarios": [
                    {
                        "scenario_id": "SCN-001",
                        "status": "covered",
                        "mapped_to": ["REQ-001"],
                    },
                    {
                        "scenario_id": "SCN-001",
                        "status": "needs_decision",
                        "mapped_to": ["DEC-001"],
                    },
                ],
            }
        )
        self.assertTrue(any("duplicates `scenario_id`" in error for error in errors))

    def test_focus_section_paragraph_without_ref_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            fd = Path(tmp_dir)
            (fd / "clarification-notes.md").write_text(
                "## Domain Frame\n\nx\n\n## Focus Points\n必须覆盖 delete→insert 同键，但这里没有任何闭环映射。\n",
                encoding="utf-8",
            )
            errs = clarify_focus_point_closure_errors(fd)
            self.assertTrue(any("paragraph text" in e or "Focus Points section" in e for e in errs))

    def test_focus_none_line_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            fd = Path(tmp_dir)
            (fd / "clarification-notes.md").write_text(
                "## Domain Frame\n\nx\n\n## 用户关注点\n- 无（用户未点名）\n",
                encoding="utf-8",
            )
            self.assertEqual(clarify_focus_point_closure_errors(fd), [])


class StateConstraintSignalScnFocusTests(unittest.TestCase):
    def _write_base(self, fd: Path, *, scn_id: str = "SCN-011", confidence: str = "high") -> None:
        (fd / "generated-scenarios.json").write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "scenarios": [
                        {
                            "scenario_id": scn_id,
                            "pattern": "pk_roundtrip",
                            "confidence": confidence,
                            "scenario": "After delete, insert row with same primary key",
                            "why_it_matters": "Order and uniqueness matter",
                            "expected_followup": "REQ",
                        }
                    ],
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        (fd / "scenario-coverage.json").write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "scenarios": [
                        {
                            "scenario_id": scn_id,
                            "status": "covered",
                            "mapped_to": ["REQ-001"],
                            "notes": "",
                        }
                    ],
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

    def test_high_confidence_hits_signal_missing_focus_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            fd = Path(tmp_dir)
            self._write_base(fd)
            errs = clarify_state_constraint_signal_scn_focus_errors(fd)
            self.assertEqual(len(errs), 1)
            self.assertIn("SCN-011", errs[0])
            self.assertIn("focus closure (full)", errs[0])

    def test_source_signals_trigger_focus_gate_without_regex_words(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            fd = Path(tmp_dir)
            (fd / "generated-scenarios.json").write_text(
                json.dumps(
                    {
                        "version": "1.0",
                        "scenarios": [
                            {
                                "scenario_id": "SCN-021",
                                "confidence": "high",
                                "pattern": "custom",
                                "source_signals": ["constraint_conflicts[0]"],
                                "scenario": "Canonical content",
                                "why_it_matters": "Needs explicit focus",
                                "expected_followup": "REQ",
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (fd / "scenario-coverage.json").write_text(
                json.dumps(
                    {
                        "version": "1.0",
                        "scenarios": [
                            {
                                "scenario_id": "SCN-021",
                                "status": "covered",
                                "mapped_to": ["REQ-021"],
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            errs = clarify_state_constraint_signal_scn_focus_errors(fd)
            self.assertEqual(len(errs), 1)
            self.assertIn("SCN-021", errs[0])

    def test_focus_bullet_with_scn_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            fd = Path(tmp_dir)
            self._write_base(fd)
            (fd / "clarification-notes.md").write_text(
                "## Domain Frame\n\nx\n\n## Focus Points\n- SCN-011 → REQ-001\n",
                encoding="utf-8",
            )
            self.assertEqual(clarify_state_constraint_signal_scn_focus_errors(fd), [])

    def test_focus_points_json_trace_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            fd = Path(tmp_dir)
            self._write_base(fd)
            (fd / "focus-points.json").write_text(
                '{"version":"1.0","items":[{"id":"FP-1","maps_to":["SCN-011"]}]}\n',
                encoding="utf-8",
            )
            self.assertEqual(clarify_state_constraint_signal_scn_focus_errors(fd), [])

    def test_low_confidence_not_triggered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            fd = Path(tmp_dir)
            self._write_base(fd, confidence="low")
            self.assertEqual(clarify_state_constraint_signal_scn_focus_errors(fd), [])

    def test_dropped_invalid_not_triggered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            fd = Path(tmp_dir)
            self._write_base(fd)
            data = json.loads((fd / "scenario-coverage.json").read_text(encoding="utf-8"))
            data["scenarios"][0]["status"] = "dropped_invalid"
            (fd / "scenario-coverage.json").write_text(
                json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            self.assertEqual(clarify_state_constraint_signal_scn_focus_errors(fd), [])

    def test_constraints_only_signal_without_state_flow_words(self) -> None:
        """constraints-identity regex must match without state-flow vocabulary."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            fd = Path(tmp_dir)
            (fd / "generated-scenarios.json").write_text(
                json.dumps(
                    {
                        "version": "1.0",
                        "scenarios": [
                            {
                                "scenario_id": "SCN-011",
                                "confidence": "high",
                                "scenario": "Ambiguous locator yields multi-match rows",
                                "why_it_matters": "Constraint resolution",
                                "expected_followup": "REQ",
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (fd / "scenario-coverage.json").write_text(
                json.dumps(
                    {
                        "version": "1.0",
                        "scenarios": [
                            {
                                "scenario_id": "SCN-011",
                                "status": "needs_decision",
                                "mapped_to": [],
                                "notes": "",
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            errs = clarify_state_constraint_signal_scn_focus_errors(fd)
            self.assertEqual(len(errs), 1)


if __name__ == "__main__":
    unittest.main()
