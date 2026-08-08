"""Tests for the shipped-doctrine path portability check."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_contracts.project_contract.managed_block import render_block
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_project_checks import check_shipped_doctrine_path_portability as mod


def _seed(root: Path, *, doctrine_body: str, rules_body: str = "") -> None:
    """Build a miniature tree with one shipped source of each kind."""
    (root / "AGENTS.md").write_text(
        f"# Rules\n\n{render_block(doctrine_body)}\n\n# Repo Internals\n",
        encoding="utf-8",
    )
    skill = root / ".agents/skills/yoke/idea/path-claim-blocking.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("shipped skill\n", encoding="utf-8")
    doc = root / "docs/public/reference/lifecycle.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("shipped doc\n", encoding="utf-8")
    decision = root / "docs/archive/decisions/some-topic.md"
    decision.parent.mkdir(parents=True)
    decision.write_text("repo-only decision record\n", encoding="utf-8")
    rules = root / "runtime/harness/claude/rules/session.md"
    rules.parent.mkdir(parents=True)
    rules.write_text(f"# Session rules\n\n{rules_body}\n", encoding="utf-8")
    board = root / ".yoke/BOARD.md"
    board.parent.mkdir(parents=True)
    board.write_text("generated view\n", encoding="utf-8")
    for args in (
        ["init", "-q"],
        ["add", "-A", "--", "AGENTS.md", ".agents", "docs", "runtime"],
    ):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _run(root: Path, monkeypatch) -> tuple[str, str]:
    monkeypatch.setattr(mod, "_resolve_repo_root", lambda: str(root))
    records = RecordCollector()
    mod.hc_shipped_doctrine_path_portability(None, DoctorArgs(), records)
    assert len(records.results) == 1
    result = records.results[0]
    return result.result, result.detail


def test_declares_the_check() -> None:
    assert [check.slug for check in mod.PROJECT_HEALTH_CHECKS] == [
        "shipped-doctrine-path-portability"
    ]


def test_passes_when_every_cited_path_ships(tmp_path: Path, monkeypatch) -> None:
    _seed(
        tmp_path,
        doctrine_body=(
            "- Overlap protocol: "
            "`.agents/skills/yoke/idea/path-claim-blocking.md`.\n"
            "- Lifecycle guide: "
            "[`.yoke/docs/reference/lifecycle.md`]"
            "(.yoke/docs/reference/lifecycle.md).\n"
            "- Guard config: `.yoke/lint-config`; hooks: `.claude/settings.json`.\n"
        ),
        rules_body="- Full stance lives in `AGENTS.md`.",
    )
    result, detail = _run(tmp_path, monkeypatch)
    assert result == "PASS", detail


def test_fails_on_a_repo_only_path(tmp_path: Path, monkeypatch) -> None:
    _seed(
        tmp_path,
        doctrine_body="- Why: `docs/archive/decisions/some-topic.md`.",
    )
    result, detail = _run(tmp_path, monkeypatch)
    assert result == "FAIL"
    assert "docs/archive/decisions/some-topic.md" in detail
    assert "ships nothing at that path" in detail


def test_fails_on_a_repo_only_path_in_the_session_rules(
    tmp_path: Path, monkeypatch
) -> None:
    _seed(
        tmp_path,
        doctrine_body="- Nothing cited here.",
        rules_body="- Recipe: `docs/archive/decisions/some-topic.md`.",
    )
    result, detail = _run(tmp_path, monkeypatch)
    assert result == "FAIL"
    assert ".claude/rules/session.md" in detail


def test_fails_when_a_shipped_destination_has_no_source(
    tmp_path: Path, monkeypatch
) -> None:
    _seed(
        tmp_path,
        doctrine_body="- Reference: `.yoke/docs/reference/never-authored.md`.",
    )
    result, detail = _run(tmp_path, monkeypatch)
    assert result == "FAIL"
    assert "docs/public/reference/never-authored.md" in detail


def test_ignores_placeholders_conventions_and_generated_views(
    tmp_path: Path, monkeypatch
) -> None:
    _seed(
        tmp_path,
        doctrine_body=(
            "- Records live under `docs/archive/decisions/` as "
            "`docs/archive/decisions/<helper-name>.md`.\n"
            "- Packs are `packs/<slug>/` bundles; machine config is "
            "`~/.yoke/config.json`.\n"
            "- The board view is `.yoke/BOARD.md`, rebuilt per project.\n"
        ),
    )
    result, detail = _run(tmp_path, monkeypatch)
    assert result == "PASS", detail


def test_skips_cleanly_without_a_repo_root(monkeypatch) -> None:
    monkeypatch.setattr(mod, "_resolve_repo_root", lambda: None)
    records = RecordCollector()
    mod.hc_shipped_doctrine_path_portability(None, DoctorArgs(), records)
    assert records.results[0].result == "PASS"
    assert "repo root not resolvable" in records.results[0].detail


@pytest.mark.parametrize(
    "text, expected",
    [
        ("see `runtime/api/tools/thing.py` now", ["runtime/api/tools/thing.py"]),
        ("[label](docs/public/a.md) and more", ["docs/public/a.md"]),
        ("run `yoke strategy render --target-root <checkout>`", []),
        ("dirs like `docs/archive/decisions/` stay", []),
        ("`NNNN_slug.py` has no directory", []),
        ("`~/.yoke/config.json` is machine-local", []),
        ("`https://upyoke.com/docs/x` is a URL", []),
        ("`a/b.md`, `a/b.md`", ["a/b.md"]),
    ],
)
def test_cited_paths_extraction(text: str, expected: list[str]) -> None:
    assert mod.cited_paths(text) == expected
