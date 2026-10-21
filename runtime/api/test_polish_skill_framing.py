"""Polish skill files stay under the authored-file line limit."""

from __future__ import annotations

from pathlib import Path

from runtime.api.skill_doc_regressions_test_helpers import SKILLS

POLISH_DIR = SKILLS / "polish"


def test_polish_files_under_file_budget_limits() -> None:
    """Each touched polish file stays under the 350-line hard limit
    (300-line design target is advisory).
    """
    limit = 350
    for name in ("parse-and-claim.md", "advance.md", "fixes.md"):
        path: Path = POLISH_DIR / name
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        assert line_count <= limit, (
            f"{name}: {line_count} lines exceeds the {limit}-line hard limit."
        )
