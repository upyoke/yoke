"""Regression guards for canonical Yoke xdist verification teaching."""

from __future__ import annotations

from runtime.api.skill_doc_regressions_test_helpers import REPO, SKILLS, _read


CANONICAL_WATCH_PYTEST = "yoke watch pytest -- runtime/api/ runtime/harness/ tests/"
IMPACTED_WATCH_PYTEST = "yoke watch pytest --impacted main --bounded"


def test_agents_testing_section_teaches_watcher_not_raw_pytest() -> None:
    text = _read(REPO / "AGENTS.md")
    # Impacted selection is the local default; the three-anchor sweep stays
    # taught as CI's job and the CI-outage fallback.
    assert IMPACTED_WATCH_PYTEST in text
    assert CANONICAL_WATCH_PYTEST in text
    assert "inject xdist `-n auto`" in text
    assert (
        "The canonical verification target for Yoke code is `python3 -m pytest"
        not in text
    )


def test_advance_summary_default_uses_watcher() -> None:
    text = _read(SKILLS / "advance" / "finalize.md")
    assert IMPACTED_WATCH_PYTEST in text
    assert '"python3 -m pytest runtime/api/" (yoke default)' not in text


def test_readiness_repair_verification_defers_to_project_command() -> None:
    """This skill ships verbatim into target projects, so its Verification
    block names the registered readiness commands and then points at the
    project's own verification command instead of pinning test anchors that
    only exist in this repo."""
    text = _read(SKILLS / "refine" / "readiness-repair.md")
    tail = text[text.index("## Verification") :]
    next_heading = tail.find("\n## ", 1)
    verification = tail if next_heading == -1 else tail[:next_heading]

    assert "yoke readiness check PREFIX-N" in verification
    assert "yoke readiness repair-stale-count --item PREFIX-N" in verification
    assert "your project's registered verification command" in verification
    assert "rather than hardcoding a test-file list" in verification

    # Neither a raw-pytest recipe nor this repo's own test anchors may
    # return to the block agents copy from.
    assert "python3 -m pytest" not in text
    assert "runtime/api/domain/test_idea_readiness_repair.py" not in verification
    assert "runtime/api/test_skill_doc_regressions_file_budget.py" not in verification


def test_db_reference_rehearsal_commands_use_watcher() -> None:
    text = _read(
        REPO / ".yoke" / "docs" / "reference" / "db-reference" / "items-and-epics.md"
    )
    assert (
        '"rehearsal_commands": ["yoke watch pytest -- <project-test-path>"]'
    ) in text
    assert '"rehearsal_commands": ["python3 -m pytest <project-test-path>"]' not in text


def test_api_readmes_use_watcher_for_test_recipes() -> None:
    for rel in ("runtime/api/README.md", "runtime/api/board/README.md"):
        text = _read(REPO / rel)
        assert "yoke watch pytest --" in text
        assert "python3 -m pytest runtime/api" not in text


def test_pg_cluster_example_uses_watcher() -> None:
    text = _read(
        REPO
        / "packages"
        / "yoke-core"
        / "src"
        / "yoke_core"
        / "tools"
        / "pg_testcluster.py"
    )
    assert "yoke watch pytest -- runtime/api/" in text
    assert "python3 -m pytest runtime/api/ -q" not in text


def test_watch_pytest_help_teaches_parallel_default() -> None:
    text = _read(
        REPO
        / "packages"
        / "yoke-core"
        / "src"
        / "yoke_core"
        / "tools"
        / "watch_pytest.py"
    )
    help_text = text.split("from __future__", 1)[0]
    assert "Parallel-by-default: ``-n auto``" in help_text
    assert "``-n 0``" in help_text
    assert "``--no-parallel``" not in help_text


def test_live_verification_teaching_uses_supported_sequential_and_lint_forms() -> None:
    for path in (
        REPO / "AGENTS.md",
        REPO / "CONTRIBUTING.md",
        REPO / "runtime" / "harness" / "claude" / "rules" / "session.md",
        REPO
        / "packages"
        / "yoke-core"
        / "src"
        / "yoke_core"
        / "domain"
        / "schema_api_context_commands_watchers.py",
    ):
        text = _read(path)
        assert "--no-parallel" not in text
    assert "yoke dev ruff-changed --base <ref>" in _read(REPO / "AGENTS.md")
    assert '"ruff==0.15.20"' in _read(REPO / "pyproject.toml")
