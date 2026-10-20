"""Doc regressions for the harness-side /yoke onboard adoption skill."""

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
    REPO / ".yoke" / "docs" / "agents" / "commands.md",
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
    "verification-command-binding",
    "migration-model-setup",
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
        "yoke setup",
        "yoke project install",
        "yoke project create",
        "yoke project import",
        "yoke onboard project",
        "yoke status",
        "yoke dev setup",
        "yoke init --local",
    ):
        assert surface in text, f"{surface!r} missing from active setup docs"


def test_yoke_skill_refs_teach_setup_and_agentic_handoff():
    text = "\n\n".join(_read(path) for path in _SETUP_SKILL_REFS)
    for surface in ("yoke setup", "/yoke onboard"):
        assert surface in text, f"{surface!r} missing from Yoke skill refs"


def test_onboard_skill_exists_with_expected_frontmatter():
    text = _read(ONBOARD)
    assert "name: onboard" in text
    assert "first item is done" in text
    assert '"[--project P] [--run-id RUN]"' in text


def test_router_lists_onboard():
    router = _read(SKILLS / "SKILL.md")
    assert "/yoke onboard" in router


def test_onboard_initializes_and_resumes_the_durable_checklist():
    text = _onboard_bundle()
    assert "yoke onboard checklist get --project {project} --json" in text
    assert (
        "yoke onboard checklist init --project {project} "
        "--checkout {checkout} --json" in text
    )
    assert "init only when none exists" in text
    assert "The checklist read is authority" in text
    # A requested reconfigure goes back through the gate, never a blind reapply.
    assert "never reapply silently" in text


def test_onboard_names_every_checklist_row():
    text = _onboard_bundle()
    for row in _EXECUTION_READINESS_ROWS + _ADOPTION_ROWS:
        assert row in text, f"checklist row {row!r} missing from onboard skill"
    assert "--row-status" in text
    assert "--evidence" in text
    assert "--blocker" in text


def test_onboard_router_reaches_every_step_file():
    """Every onboard step file is linked from the router or a linked step."""
    linked = set()
    for path in ONBOARD_DIR.glob("*.md"):
        linked.update(re.findall(r"\]\(([\w-]+\.md)\)", _read(path)))
    router_links = set(re.findall(r"\]\(([\w-]+\.md)\)", _read(ONBOARD)))
    assert "run-and-rows.md" in router_links
    for path in ONBOARD_DIR.glob("*.md"):
        if path.name != "SKILL.md":
            assert path.name in linked, f"{path.name} is unreachable from onboard"


def test_onboard_binds_two_stop_pacing_and_the_apply_gate():
    text = _onboard_bundle()
    assert "Only two stops" in text
    assert "[y/N]" in text
    assert "default No records `deferred`" in text
    # Gated-apply failure posture: keep it up, record blocked, no retry.
    assert "keep it up, write `blocked`, no retry" in text
    assert "profile_changed" in text


def test_onboard_teaches_preview_first_packs():
    text = _onboard_bundle()
    assert "yoke packs get webapp-scaffold {checkout} --project {project}" in text
    assert "--apply" in text
    assert "Preview without" in text
    # A Pack already installed is verified, never reinstalled or moved.
    assert "`.yoke/packs.json` is verified, not reinstalled" in " ".join(text.split())


def test_onboard_teaches_strategy_seed_topup_and_all_five_docs():
    text = _read(ONBOARD_DIR / "strategy-conversation.md")
    assert "yoke strategy seed-defaults" in text
    for slug in ("MISSION", "VISION", "MASTER-PLAN", "LANDSCAPE", "CURRENT-PLAN"):
        assert slug in text, f"strategy slug {slug!r} missing"
    assert "yoke strategy doc replace" in text
    assert "--base-updated-at" in text
    assert "yoke claims work acquire --process STRATEGIZE" in text


def test_onboard_profile_always_carries_a_test_setup_box():
    """The wizard never asks how tests run, so the profile confirmation must."""
    text = _read(ONBOARD_DIR / "profile-and-scaffold.md").lower()
    # Every outcome is named; none is a silent default.
    for outcome in (
        "surveyed command",
        "scaffold suite",
        "review-only",
        "attested no-tests",
    ):
        assert outcome in text, f"test-setup outcome {outcome!r} missing"
    # A descriptive project-structure entry is never the gate command.
    doc = _read(REPO / ".yoke" / "docs" / "verification" / "index.md")
    assert "`verification_profiles.test_command` entry is descriptive" in doc


def test_onboard_binds_the_confirmed_test_setup_to_the_gate():
    """AC-bearing gate commands come from the binding, not from prose."""
    text = _read(ONBOARD_DIR / "verification-binding.md")
    assert "yoke qa registered-command set --project {project} --scope quick" in text
    assert "`full` only when broader" in text
    assert "ci_workflow_file" in text
    # The declaration must name the workflow that runs the tests.
    assert "never deploy/release" in text


def test_onboard_teaches_hosting_probe_and_stdin_secrets():
    text = " ".join(_read(ONBOARD_DIR / "hosting-and-environments.md").split())
    # An operator whose pair is already saved is never asked for it again.
    assert "yoke aws admin-status --project {project} --json" in text
    assert "never re-request a saved pair or use ambient" in text
    assert "write `hosting-setup=blocked` and stop" in text
    assert "--value-stdin" in _read(ONBOARD)
    assert "Never print secrets" in _read(REPO / "AGENTS.md")


def test_onboard_teaches_environment_and_flow_registration():
    text = _read(ONBOARD_DIR / "hosting-and-environments.md")
    assert "register site and environments" in text
    assert "never overwrite an existing one" in text
    assert "execution_supported=false" in text
    assert "Disable a referenced flow rather than edit it" in text
    assert "--environment-id" not in text
    # An existing project deploy file is a hint, never a contract onboarding
    # must parse, author, or repair.
    assert "`.yoke/deployment-flows.json` are hints" in text
    assert "never edit or depend on them" in text
    assert "reconcile-project" not in text


def test_onboard_never_installs_a_harness():
    assert "never switch projects or install a harness" in _read(ONBOARD).lower()


def test_onboard_failure_floor_is_the_resume_point():
    text = _read(ONBOARD_DIR / "run-and-rows.md")
    assert "On failure write `blocked`" in text
    assert "never undo prior steps" in " ".join(text.split())


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
