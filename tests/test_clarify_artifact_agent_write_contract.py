"""CLARIFY artifact agents: Edit disabled, Write allowed for a single harness path only."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "agents"

# Agent file -> required substring for its sole Write artifact (in body, after frontmatter).
ARTIFACT_PATH_MARKERS: dict[str, str] = {
    "requirement-analyst.md": ".harness/features/<epic-id>/requirements-draft.md",
    "challenger.md": ".harness/features/<epic-id>/challenge-report.md",
    "project-surface-router.md": ".harness/features/<epic-id>/surface-map.md",
    "deep-dive-specialist.md": ".harness/features/<epic-id>/deep-dive-<slug>.md",
}

# Agents where blanket "no writes" / "cannot Write" prose must not remain (conflicts with Write scope).
NO_ABSOLUTE_WRITE_VETO_AGENTS = frozenset(
    {
        "requirement-analyst.md",
        "challenger.md",
        "project-surface-router.md",
        "deep-dive-specialist.md",
    }
)

CONFLICT_PHRASES = (
    "Do NOT modify any files",
    "this agent cannot Write",
)


def _split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---\n"):
        raise ValueError("expected YAML frontmatter opening ---")
    rest = text[4:]
    sep = rest.find("\n---\n")
    if sep == -1:
        raise ValueError("expected closing --- for frontmatter")
    return rest[:sep], rest[sep + 5 :]


def _parse_disallowed_tools(frontmatter: str) -> list[str]:
    m = re.search(r"^disallowedTools:\s*\[([^\]]*)\]\s*$", frontmatter, re.MULTILINE)
    if not m:
        raise AssertionError("frontmatter missing disallowedTools: [...]")
    inner = m.group(1).strip()
    if not inner:
        return []
    return [part.strip() for part in inner.split(",") if part.strip()]


class ClarifyArtifactAgentWriteContractTests(unittest.TestCase):
    def test_frontmatter_edit_only_disallowed_write_allowed(self) -> None:
        for name in ARTIFACT_PATH_MARKERS:
            with self.subTest(agent=name):
                path = AGENTS / name
                text = path.read_text(encoding="utf-8")
                fm, _ = _split_frontmatter(text)
                tools = _parse_disallowed_tools(fm)
                self.assertIn("Edit", tools, msg=f"{name}: Edit must stay disallowed")
                self.assertNotIn(
                    "Write",
                    tools,
                    msg=f"{name}: Write must not be in disallowedTools",
                )
                self.assertEqual(
                    tools,
                    ["Edit"],
                    msg=f"{name}: disallowedTools should be exactly [Edit]",
                )

    def test_body_includes_artifact_path(self) -> None:
        for name, marker in ARTIFACT_PATH_MARKERS.items():
            with self.subTest(agent=name):
                path = AGENTS / name
                text = path.read_text(encoding="utf-8")
                _, body = _split_frontmatter(text)
                self.assertIn(marker, body, msg=f"{name}: missing artifact path {marker!r}")

    def test_no_absolute_write_conflict_phrases_where_required(self) -> None:
        for name in NO_ABSOLUTE_WRITE_VETO_AGENTS:
            with self.subTest(agent=name):
                path = AGENTS / name
                text = path.read_text(encoding="utf-8")
                _, body = _split_frontmatter(text)
                for phrase in CONFLICT_PHRASES:
                    self.assertNotIn(
                        phrase,
                        body,
                        msg=f"{name}: must not contain conflicting phrase {phrase!r}",
                    )


if __name__ == "__main__":
    unittest.main()
