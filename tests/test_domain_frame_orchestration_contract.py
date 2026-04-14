"""Orchestration docs + harnessctl stay aligned with domain-frame CLARIFY gate contract."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
ORCH_DOCS = [
    ROOT / "agents" / "lead-orchestrator.md",
    ROOT / "commands" / "harness-clarify.md",
    ROOT / "skills" / "clarify" / "SKILL.md",
]


class HarnessctlDomainFrameGateTests(unittest.TestCase):
    def test_harnessctl_uses_shared_missing_key_helper(self) -> None:
        src = (ROOT / "scripts" / "harnessctl.py").read_text(encoding="utf-8")
        self.assertIn("domain_frame_missing_required_keys", src)
        # harnessctl may use parenthesized multi-line imports; allow newlines after `import`.
        self.assertRegex(
            src,
            r"(?s)from clarify_gate_shared import.*?domain_frame_missing_required_keys",
        )


class OrchestrationDocsDomainFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        from clarify_gate_shared import DOMAIN_FRAME_REQUIRED_KEYS

        cls.domain_frame_required_keys = DOMAIN_FRAME_REQUIRED_KEYS

    def test_each_doc_mentions_gate_keys_schema_pointer_and_legacy_veto(self) -> None:
        # At least two explicit legacy key tokens so we do not match on accidental "domain" prose alone.
        legacy_markers = ("`domain`", "subdomain", "domain_signals")
        for path in ORCH_DOCS:
            text = path.read_text(encoding="utf-8")
            self.assertIn("agents/domain-scout.md", text.replace("\\", "/"), msg=path.name)
            self.assertIn("DOMAIN_FRAME_REQUIRED_KEYS", text, msg=path.name)
            self.assertIn("clarify_gate_shared.py", text, msg=path.name)
            for key in self.domain_frame_required_keys:
                self.assertIn(key, text, msg=f"{path.name} missing {key!r}")
            hits = sum(1 for m in legacy_markers if m in text)
            self.assertGreaterEqual(
                hits,
                2,
                msg=f"{path.name} should forbid at least two legacy key names explicitly",
            )


if __name__ == "__main__":
    unittest.main()
