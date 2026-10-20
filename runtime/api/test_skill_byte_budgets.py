"""Every Yoke skill file carries a byte budget, and growth past it fails."""

from __future__ import annotations

from pathlib import Path
import subprocess

from yoke_contracts.project_contract.file_byte_budget import parse_byte_budgets
from yoke_core.domain import file_line_check

ROOT = Path(__file__).resolve().parents[2]
SKILL = ".agents/skills/yoke/dash/verify.md"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def _budgets() -> dict[str, int]:
    config = (ROOT / ".yoke" / "project.config").read_text(encoding="utf-8")
    entries = [
        line.split("=", 1)[1]
        for line in config.splitlines()
        if line.startswith("file_byte_budget=")
    ]
    budgets, broken = parse_byte_budgets(entries)
    assert broken == []
    return budgets


def test_every_skill_file_is_budgeted_and_within_budget():
    budgets = _budgets()
    skills = _git(ROOT, "ls-files", ".agents/skills/yoke").split()
    assert skills
    unbudgeted = [path for path in skills if path not in budgets]
    assert unbudgeted == []
    over = [path for path in skills if (ROOT / path).stat().st_size > budgets[path]]
    assert over == []


def test_a_skill_grown_past_its_budget_fails_the_authored_file_check(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / ".yoke").mkdir()
    (tmp_path / ".yoke" / "project.config").write_text(
        f"file_byte_budget={SKILL}:{_budgets()[SKILL]}\n"
    )
    skill = tmp_path / SKILL
    skill.parent.mkdir(parents=True)
    skill.write_text((ROOT / SKILL).read_text(encoding="utf-8"))
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "seed")
    skill.write_text(skill.read_text() + "Rationale an agent does not need.\n" * 20)
    _git(tmp_path, "add", SKILL)

    verdict = file_line_check.changed_files_check(repo_root=tmp_path, staged=True)

    assert verdict.ok is False
    [failure] = verdict.byte_budget_fails
    assert failure.path == SKILL
    assert failure.reason == "file_byte_budget_exceeded"
