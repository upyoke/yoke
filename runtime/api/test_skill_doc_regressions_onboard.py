"""Doc regressions for the harness-side /yoke onboard execution-readiness skill."""

from __future__ import annotations

import re
from pathlib import Path

from runtime.api.skill_doc_regressions_test_helpers import REPO, SKILLS, _read


ONBOARD_DIR = SKILLS / "onboard"
ONBOARD = ONBOARD_DIR / "SKILL.md"
# The retired surface is the `/yoke init` per-repo setup SKILL (slash
# command). The `yoke init --local` CLI command is a different, live
# surface: it births the machine-local universe (embedded Postgres +
# control-plane bootstrap), not repo-local settings/labels setup.
_RETIRED_SETUP_PATTERN = re.compile(r"(?<![\w-])/yoke init(?![\w-])")
_ACTIVE_SETUP_DOCS = (
    REPO / "README.md",
    REPO / "docs" / "local-setup.md",
    REPO / "docs" / "onboard-external-project.md",
    REPO / ".yoke" / "docs" / "reference" / "commands.md",
    REPO / "docs" / "atlas.md",
)
_SETUP_SKILL_REFS = (
    SKILLS / "SKILL.md",
    SKILLS / "help" / "SKILL.md",
    ONBOARD,
)

# One durable checklist row per onboarding concern. The six execution-readiness
# rows pair with the shared checklist contract
# (yoke_contracts.onboard_checklist.ROW_SPECS); the adapter itself rejects
# unknown row ids at write time, so prose and contract cannot drift silently.
_EXECUTION_READINESS_ROWS = (
    "scaffold-install",
    "hosting-setup",
    "environment-registration",
    "domain-setup",
    "infra-apply-first-deploy",
    "work-seeding",
)
_ADOPTION_ROWS = (
    "repo-survey",
    "human-interview",
    "documentation-context-setup",
    "strategy-setup",
    "project-structure-setup",
    "capability-setup",
    "delivery-setup",
    "verification",
    "lifecycle-readiness",
)


def _onboard_bundle() -> str:
    files = sorted(ONBOARD_DIR.glob("*.md"))
    assert files, f"expected onboard skill files under {ONBOARD_DIR}"
    return "\n\n".join(_read(path) for path in files)


def _live_setup_doc_and_skill_files() -> list[Path]:
    docs_root = REPO / "docs"
    docs = [
        path
        for path in docs_root.rglob("*.md")
        if "archive" not in path.parts and "legacy-plan-artifacts" not in path.parts
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


def test_no_retired_skill_names_anywhere_in_skills():
    offenders: list[str] = []
    for path in sorted(SKILLS.rglob("*.md")):
        if "onboard-project" in _read(path):
            offenders.append(path.relative_to(REPO).as_posix())
    assert not offenders, (
        "the project-adoption skill surface is /yoke onboard; no skill file "
        f"may reference the retired name: {offenders}"
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
        "/yoke onboard",
    ):
        assert surface in text, f"{surface!r} missing from Yoke skill refs"


def test_onboard_skill_exists_with_expected_frontmatter():
    text = _read(ONBOARD)
    assert "name: onboard" in text
    assert "execution-ready" in text
    assert '"[--project P] [--run-id RUN]"' in text


def test_router_lists_onboard():
    router = _read(SKILLS / "SKILL.md")
    assert "/yoke onboard" in router
    assert "execution-ready" in router


def test_onboard_initializes_and_resumes_the_durable_checklist():
    text = _onboard_bundle()
    assert "yoke onboard checklist --run-id {run_id} --json" in text
    assert (
        "yoke onboard checklist init --project {project} "
        "--checkout {checkout} --json" in text
    )
    assert "never treat it as authority" in text
    # Re-runs are idempotent-skip with explicit reconfigure, never blind
    # re-apply.
    assert "never blindly re-applies" in text
    assert "reconfigure" in text.lower()


def test_onboard_names_every_checklist_row():
    text = _onboard_bundle()
    for row in _EXECUTION_READINESS_ROWS + _ADOPTION_ROWS:
        assert row in text, f"checklist row {row!r} missing from onboard skill"
    assert "--row-status" in text
    assert "--evidence" in text
    assert "--blocker" in text


def test_onboard_has_the_eight_step_structure():
    text = _onboard_bundle()
    for heading in (
        "Strategy Conversation",
        "Derive The Execution Profile",
        "Install The Scaffold Pack",
        "Hosting Capability",
        "Deploy Flow",
        "Domain",
        "Gated Infra Apply + First Deploy",
        "Seed The First Work",
    ):
        assert heading in text, f"step heading {heading!r} missing"
    # Every step carries entry and skip conditions in the router map.
    router = _read(ONBOARD)
    assert "| Entry | Skip |" in router


def test_onboard_binds_two_stop_pacing_and_the_apply_gate():
    text = _onboard_bundle()
    assert "Exactly two stops" in text
    assert "[y/N]" in text
    assert "defaults No" in text
    assert "unattended" in text
    # Gated-apply failure posture: re-approve + retry; smoke failures stay up.
    assert "re-presents the same gate" in text
    assert "stays up for diagnosis" in text
    # The confirmed profile is never persisted; resume re-derives it.
    assert "not persisted" in text
    assert "re-derives" in text


def test_onboard_teaches_receipt_first_preview_first_packs():
    text = _onboard_bundle()
    assert "yoke packs get webapp-scaffold {checkout} --project {project}" in text
    assert "--apply" in text
    assert ".yoke/packs.json" in text
    assert "preview" in text.lower()
    assert "ordinary project-owned source" in text
    # Version moves are Pack updates, not onboarding.
    assert "yoke packs update" in text


def test_onboard_teaches_strategy_seed_topup_and_all_five_docs():
    text = _read(ONBOARD_DIR / "strategy-conversation.md")
    assert "yoke strategy seed-defaults" in text
    for slug in ("MISSION", "VISION", "MASTER-PLAN", "LANDSCAPE", "CURRENT-PLAN"):
        assert slug in text, f"strategy slug {slug!r} missing"
    assert "yoke strategy doc replace" in text
    assert "--base-updated-at" in text
    assert "yoke claims work acquire --process STRATEGIZE" in text


def test_onboard_teaches_hosting_probe_and_stdin_secrets():
    text = _read(ONBOARD_DIR / "hosting-and-environments.md")
    assert (
        "yoke projects capability has --project {project} --cap-type aws-admin" in text
    )
    assert "yoke aws exec --project {project} -- sts get-caller-identity" in text
    assert "yoke projects capability secret set" in text
    assert "--value-stdin" in text
    assert "app-binding" in text
    assert "disabled" in text
    bundle = _onboard_bundle()
    assert "never printed" in bundle or "never print" in bundle.lower()


def test_onboard_teaches_environment_and_flow_registration():
    text = _read(ONBOARD_DIR / "hosting-and-environments.md")
    assert (
        "yoke projects site create --project {project} --site-slug {site_slug}" in text
    )
    assert "yoke projects environment create" in text
    assert "--environment-id stage" in text
    assert "--environment-id prod" in text
    assert ".yoke/deployment-flows.json" in text
    assert "yoke deployment-flows reconcile-project" in text
    assert "default_flow" in text


def test_onboard_seeds_work_through_the_idea_intake_shape():
    text = _read(ONBOARD_DIR / "seed-work.md")
    assert (
        'yoke items create "{title}" issue --entry-surface harness_skill '
        "--project {project} --deployment-flow {flow_id} --priority {priority}"
    ) in text
    assert "yoke project-structure deploy-defaults get --project {project}" in text
    assert "omit `--deployment-flow`" in text
    assert "never pass the literal string `none`" in text
    # One batched confirmation, then serial filing.
    assert "one confirmation for the whole batch" in text
    assert "one at a time" in text
    assert "/yoke do" in text


def test_onboard_honors_the_web_views_and_steers_boundary():
    text = _read(ONBOARD)
    assert "The web views and steers; it never invokes." in text
    assert "No web button runs this skill." in text
    # Harness connections are detected, never installed.
    assert "never install one" in text


def test_onboard_failure_floor_is_the_resume_point():
    text = _read(ONBOARD)
    assert "Failure floor" in text
    assert "resume point" in text
    assert "Completed writes stay in place" in text


def test_onboard_skill_avoids_forbidden_raw_surfaces():
    text = _onboard_bundle()
    forbidden = (
        "db_router",
        "service_client.py",
        "python3 -m yoke_core",
        "python3 -c",
        "curl localhost",
        "localhost:8765",
        "YOKE_API",
        "from runtime",
        "from yoke_core",
    )
    for phrase in forbidden:
        assert phrase not in text, f"forbidden raw surface {phrase!r} in onboard skill"
