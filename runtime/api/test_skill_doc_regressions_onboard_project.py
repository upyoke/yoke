"""Doc regressions for the harness-side /yoke onboard-project skill."""

from __future__ import annotations

import re
from pathlib import Path

from runtime.api.skill_doc_regressions_test_helpers import REPO, SKILLS, _read


ONBOARD_PROJECT = SKILLS / "onboard-project" / "SKILL.md"
# The retired surface is the `/yoke init` per-repo setup SKILL (slash
# command). The `yoke init --local` CLI command is a different, live
# surface: it births the machine-local universe (embedded Postgres +
# control-plane bootstrap), not repo-local settings/labels setup.
_RETIRED_SETUP_PATTERN = re.compile(r"(?<![\w-])/yoke init(?![\w-])")
_ACTIVE_SETUP_DOCS = (
    REPO / "README.md",
    REPO / "docs" / "local-setup.md",
    REPO / "docs" / "onboard-external-project.md",
    REPO / "docs" / "commands.md",
    REPO / "docs" / "atlas.md",
)
_SETUP_SKILL_REFS = (
    SKILLS / "SKILL.md",
    SKILLS / "help" / "SKILL.md",
    ONBOARD_PROJECT,
)


def _live_setup_doc_and_skill_files() -> list[Path]:
    docs_root = REPO / "docs"
    docs = [
        path
        for path in docs_root.rglob("*.md")
        if "archive" not in path.parts
        and "legacy-plan-artifacts" not in path.parts
    ]
    return sorted([REPO / "README.md", *docs, *SKILLS.rglob("*.md")])


def test_live_setup_docs_and_skill_refs_do_not_teach_retired_init():
    offenders: list[tuple[str, int, str]] = []
    for path in _live_setup_doc_and_skill_files():
        rel = path.relative_to(REPO).as_posix()
        for lineno, line in enumerate(_read(path).splitlines(), start=1):
            if _RETIRED_SETUP_PATTERN.search(line):
                offenders.append((rel, lineno, line.strip()))

    assert not offenders, (
        "Live user-facing docs and Yoke skill references must not teach "
        "the retired `/yoke init` per-repo setup skill (the `yoke init "
        "--local` CLI universe-birth command is a different, live surface). "
        "Intentional retirement discussion belongs in "
        ".yoke/strategy/OPERATIONS-NOTES.md or archived/generated audits.\n"
        + "\n".join(f"  {rel}:{lineno}: {line}" for rel, lineno, line in offenders)
    )


def test_active_setup_docs_teach_replacement_terminal_surfaces():
    text = "\n\n".join(_read(path) for path in _ACTIVE_SETUP_DOCS)
    for surface in (
        "yoke onboard",
        "yoke project install",
        "yoke project create",
        "yoke project import",
        "yoke onboard project",
        "yoke status",
        "yoke dev setup",
        "yoke init --local",
    ):
        assert surface in text, f"{surface!r} missing from active setup docs"


def test_yoke_skill_refs_teach_setup_replacements_and_agentic_handoff():
    text = "\n\n".join(_read(path) for path in _SETUP_SKILL_REFS)
    for surface in (
        "yoke onboard",
        "yoke project install",
        "yoke project create",
        "yoke project import",
        "yoke onboard project",
        "yoke status",
        "yoke dev setup",
        "/yoke onboard-project",
    ):
        assert surface in text, f"{surface!r} missing from Yoke skill refs"


def test_onboard_project_skill_exists_with_expected_frontmatter():
    text = _read(ONBOARD_PROJECT)
    assert "name: onboard-project" in text
    assert "agentic project adoption after deterministic install" in text


def test_router_lists_onboard_project():
    router = _read(SKILLS / "SKILL.md")
    assert "/yoke onboard-project" in router
    assert "agentic project adoption after deterministic install" in router


def test_onboard_project_consumes_durable_checklist_and_install_report():
    text = _read(ONBOARD_PROJECT)
    assert "yoke onboard checklist --run-id {run_id} --json" in text
    assert "Do not treat project-local checklist Markdown as authority." in text
    assert "existing `yoke project install` report" in text
    assert "do not rerun deterministic setup" in text


def test_onboard_project_teaches_required_sanctioned_surfaces():
    text = _read(ONBOARD_PROJECT)
    for surface in (
        "yoke project-structure patch apply",
        "yoke strategy doc list",
        "yoke strategy doc get",
        "yoke strategy doc create",
        "yoke strategy doc replace",
        "yoke strategy render",
        "yoke strategy ingest",
        "yoke projects capability has",
        "yoke projects capability-secret set",
        "yoke templates list",
        "yoke templates fetch",
        "yoke qa requirement list",
        "yoke qa requirement add",
        "yoke events emit",
        "yoke onboard checklist --run-id {run_id}",
        "--row-status",
        "--evidence",
    ):
        assert surface in text


def test_onboard_project_teaches_product_safe_webapp_template_fetch():
    text = _read(ONBOARD_PROJECT)

    assert "yoke templates fetch webapp" in text
    assert "yoke templates fetch --source-dev-admin" in text


def test_onboard_project_names_required_rows_and_phases():
    text = _read(ONBOARD_PROJECT)
    for row in (
        "repo-survey",
        "human-interview",
        "documentation-context-setup",
        "strategy-setup",
        "project-structure-setup",
        "capability-setup",
        "delivery-setup",
        "verification",
        "lifecycle-readiness",
    ):
        assert row in text
    for phase in (
        "Intake",
        "Repo Survey",
        "Human Interview And Blockers",
        "Apply Sanctioned Setup",
        "Verification",
        "Handoff",
    ):
        assert phase in text


def test_onboard_project_teaches_explicit_github_adoption_preview():
    text = _read(ONBOARD_PROJECT)
    for choice in (
        "temporary-only",
        "store-token",
        "different-token",
        "skip",
    ):
        assert choice in text
    for preview_target in (
        "GitHub labels",
        "issue/PR templates",
        "Actions variables/secrets",
        "branch protection",
        "environment protection",
    ):
        assert preview_target in text
    assert "--github-adoption {choice}" in text
    assert "--dry-run --json" in text
    assert (
        "Machine credentials used to reach Yoke are not project runtime authority"
        in text
    )
    assert "Direct, file, and stdin token inputs are import methods only" in text
    assert "stored as Yoke-owned literal values" in text


def test_onboard_project_skill_avoids_forbidden_raw_surfaces():
    text = _read(ONBOARD_PROJECT)
    forbidden = (
        "db_router",
        "service_client.py",
        "python3 -m yoke_core",
        "curl localhost",
        "localhost:8765",
        "YOKE_API",
        "from runtime",
    )
    for phrase in forbidden:
        assert phrase not in text
    assert "Do not edit `.yoke/BOARD.md`." in text
