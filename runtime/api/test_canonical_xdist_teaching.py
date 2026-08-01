"""Regression guards for canonical Yoke xdist verification teaching."""

from __future__ import annotations

from runtime.api.skill_doc_regressions_test_helpers import REPO, SKILLS, _read


CANONICAL_WATCH_PYTEST = (
    "uv run --frozen python3 -m yoke_core.tools.watch_pytest -- "
    "runtime/api/ runtime/harness/ tests/"
)
IMPACTED_WATCH_PYTEST = (
    "uv run --frozen python3 -m yoke_core.tools.watch_pytest --impacted main"
)


def test_agents_testing_section_teaches_watcher_not_raw_pytest() -> None:
    text = _read(REPO / "AGENTS.md")
    # Impacted selection is the local default; the three-anchor sweep stays
    # taught as CI's job and the CI-outage fallback.
    assert IMPACTED_WATCH_PYTEST in text
    assert CANONICAL_WATCH_PYTEST in text
    assert "inject xdist `-n auto`" in text
    assert "The canonical verification target for Yoke code is `python3 -m pytest" not in text


def test_advance_summary_default_uses_watcher() -> None:
    text = _read(SKILLS / "advance" / "finalize.md")
    assert IMPACTED_WATCH_PYTEST in text
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
    text = _read(REPO / ".yoke" / "docs" / "db-reference" / "items-and-epics.md")
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
    help_text = text.split("from __future__", 1)[0]
    assert "Parallel-by-default: ``-n auto``" in help_text
    assert "``-n 0``" in help_text
    assert "``--no-parallel``" not in help_text


def test_shipped_surfaces_carry_no_repo_local_test_anchors() -> None:
    """Install-bundle surfaces must not teach this repo's own test paths.

    ``.agents/skills/yoke``, the harness rules, and the rendered agent
    adapters are copied verbatim into every project Yoke installs into.
    A hardcoded ``runtime/api/ runtime/harness/ tests/`` there tells a
    target project's agents to run paths that do not exist in their repo.
    The anchors belong to AGENTS.md, which stays repo-local below the
    managed-block marker.
    """
    shipped_roots = (
        REPO / ".agents" / "skills" / "yoke",
        REPO / "runtime" / "harness" / "claude" / "rules",
        REPO / "runtime" / "harness" / "claude" / "agents",
        REPO / "runtime" / "harness" / "codex" / "agents",
    )
    offenders = []
    for root in shipped_roots:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".md", ".toml"}:
                continue
            if "runtime/api/ runtime/harness/ tests/" in _read(path):
                offenders.append(str(path.relative_to(REPO)))
    assert offenders == [], (
        "repo-local test anchors found in install-bundle surfaces: "
        f"{offenders}. Teach the anchors in AGENTS.md (below the managed "
        "block) and keep shipped copy project-neutral."
    )


def test_live_verification_teaching_uses_supported_sequential_and_lint_forms() -> None:
    for path in (
        REPO / "AGENTS.md",
        REPO / "CONTRIBUTING.md",
        REPO / "runtime" / "harness" / "claude" / "rules" / "session.md",
        REPO / "packages" / "yoke-core" / "src" / "yoke_core" / "domain"
        / "schema_api_context_commands_watchers.py",
    ):
        text = _read(path)
        assert "--no-parallel" not in text
    assert "uv run --frozen ruff check <changed Python paths>" in _read(
        REPO / "AGENTS.md"
    )
    assert '"ruff==0.15.20"' in _read(REPO / "pyproject.toml")
