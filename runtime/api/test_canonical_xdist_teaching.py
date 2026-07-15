"""Regression guards for canonical Yoke xdist verification teaching."""

from __future__ import annotations

from runtime.api.skill_doc_regressions_test_helpers import REPO, SKILLS, _read


CANONICAL_WATCH_PYTEST = (
    "uv run --frozen python3 -m yoke_core.tools.watch_pytest -- "
    "runtime/api/ runtime/harness/ tests/"
)


def test_agents_testing_section_teaches_watcher_not_raw_pytest() -> None:
    text = _read(REPO / "AGENTS.md")
    assert CANONICAL_WATCH_PYTEST in text
    assert "it injects xdist `-n auto`" in text
    assert "The canonical verification target for Yoke code is `python3 -m pytest" not in text


def test_advance_summary_default_uses_watcher() -> None:
    text = _read(SKILLS / "advance" / "finalize.md")
    assert CANONICAL_WATCH_PYTEST in text
    assert '"python3 -m pytest runtime/api/" (yoke default)' not in text


def test_readiness_repair_verification_uses_watcher() -> None:
    text = _read(SKILLS / "refine" / "readiness-repair.md")
    assert (
        "python3 -m yoke_core.tools.watch_pytest -- "
        "runtime/api/domain/test_idea_readiness_repair.py "
        "runtime/api/test_skill_doc_regressions_file_budget.py"
    ) in text
    assert "python3 -m pytest runtime/api/domain/test_idea_readiness_repair.py" not in text


def test_db_reference_rehearsal_commands_use_watcher() -> None:
    text = _read(REPO / "docs" / "db-reference" / "items-and-epics.md")
    assert (
        '"rehearsal_commands": '
        '["python3 -m yoke_core.tools.watch_pytest -- runtime/api/"]'
    ) in text
    assert '"rehearsal_commands": ["python3 -m pytest runtime/api/"]' not in text


def test_api_readmes_use_watcher_for_test_recipes() -> None:
    for rel in ("runtime/api/README.md", "runtime/api/board/README.md"):
        text = _read(REPO / rel)
        assert "python3 -m yoke_core.tools.watch_pytest --" in text
        assert "python3 -m pytest runtime/api" not in text


def test_ac_verification_policy_uses_watcher_target() -> None:
    text = _read(
        REPO / "packages" / "yoke-core" / "src"
        / "yoke_core" / "domain" / "qa_requirements_auto.py"
    )
    assert (
        'PYTEST_TARGET = "python3 -m yoke_core.tools.watch_pytest -- runtime/api/"'
        in text
    )
    assert 'PYTEST_TARGET = "python3 -m pytest runtime/api/"' not in text


def test_pg_cluster_example_uses_watcher() -> None:
    text = _read(
        REPO / "packages" / "yoke-core" / "src"
        / "yoke_core" / "tools" / "pg_testcluster.py"
    )
    assert "python3 -m yoke_core.tools.watch_pytest -- runtime/api/" in text
    assert "python3 -m pytest runtime/api/ -q" not in text


def test_watch_pytest_help_teaches_parallel_default() -> None:
    text = _read(
        REPO / "packages" / "yoke-core" / "src"
        / "yoke_core" / "tools" / "watch_pytest.py"
    )
    assert "Parallel-by-default: ``-n auto``" in text
    assert "``--no-parallel``" in text
