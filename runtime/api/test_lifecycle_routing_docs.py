"""Doc regression guards for lifecycle + routing truth.

Lifecycle/routing doctrine parity: the runtime already ships the current
lifecycle and routing contracts, but several human-readable surfaces still carried
stale claims. This module locks in the consolidated doc state so the
drift cannot silently regress.

These are grep-style assertions against tracked markdown/JSON files in
the repo. They do not touch the database, git, or any network.

Coverage of `AGENTS.md ## Lifecycle & Routing` — the harness-neutral
canonical lifecycle wording — lives in test_lifecycle_routing_docs_session.py.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from yoke_core.domain.harness_capability_registry import (
    shared_downstream_paths,
    shared_entrypoints,
)


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError("Unable to locate repo root from test module location.")


REPO = _repo_root()
DOCS = REPO / "docs"
# Universal docs shipped to managed projects now live under .yoke/docs.
YOKE_DOCS = REPO / ".yoke" / "docs"


def _read(path: Path) -> str:
    assert path.is_file(), f"expected file to exist: {path}"
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# TestBootstrapSpec — canonical lifecycle guide is loaded at bootstrap
# ---------------------------------------------------------------------------


class TestBootstrapSpec:
    """AC-1: bootstrap must load yoke/.yoke/docs/lifecycle.md."""

    @pytest.fixture
    def spec(self) -> dict:
        path = REPO / "runtime" / "harness" / "bootstrap-spec.json"
        return json.loads(_read(path))

    def test_required_files_includes_lifecycle(self, spec):
        required = spec.get("required_files", [])
        assert ".yoke/docs/lifecycle.md" in required, (
            "bootstrap-spec.json must include yoke/.yoke/docs/lifecycle.md in required_files"
        )

    def test_lifecycle_loaded_after_commands(self, spec):
        """lifecycle.md should follow commands.md so readers get command
        vocabulary before the lifecycle tables that use it."""
        required = spec.get("required_files", [])
        assert ".yoke/docs/commands.md" in required
        assert required.index(".yoke/docs/lifecycle.md") > required.index(
            ".yoke/docs/commands.md"
        )


# ---------------------------------------------------------------------------
# TestLifecycleDoc — canonical human lifecycle guide covers command boundaries
# ---------------------------------------------------------------------------


class TestLifecycleDoc:
    """AC-1: lifecycle.md is the canonical human lifecycle guide."""

    @pytest.fixture
    def text(self) -> str:
        return _read(YOKE_DOCS / "lifecycle.md")

    def test_has_issue_command_family(self, text):
        assert "Issue command family" in text or "issue command family" in text.lower()

    def test_has_epic_command_family(self, text):
        assert "Epic command family" in text or "epic command family" in text.lower()

    def test_refine_owns_idea_refinement(self, text):
        # The command-boundary summary must name refine as the owner of idea refinement.
        assert "/yoke refine" in text
        assert "idea -> refining-idea -> refined-idea" in text or "idea → refining-idea → refined-idea" in text

    def test_shepherd_is_epic_only(self, text):
        # Shepherd must be labeled epic-only for refined-idea -> plan-drafted.
        assert "/yoke shepherd" in text
        # Look for "epic" and "shepherd" in the same command-boundary table row / prose.
        assert re.search(r"shepherd.*epic", text, re.IGNORECASE) or re.search(
            r"epic.*shepherd", text, re.IGNORECASE
        )

    def test_polish_owns_reviewed_to_implemented(self, text):
        assert "/yoke polish" in text
        assert "reviewed-implementation" in text
        assert "polishing-implementation" in text
        assert "implemented" in text

    def test_handoff_boundaries_require_fresh_entrypoints(self, text):
        assert "fresh command entrypoints" in text or "fresh command entrypoint" in text
        assert "/yoke polish" in text
        assert "/yoke usher" in text

    def test_routes_to_canonical_routing_docs(self, text):
        assert "session-offer-contract.md" in text
        assert "charge-frontier.md" in text


# ---------------------------------------------------------------------------
# TestCommandsDoc — refine/polish advance status, no stale supported-paths env var
# ---------------------------------------------------------------------------


class TestCommandsDoc:
    """AC-4: commands.md must match the live refine/polish skills and
    must not present YOKE_SUPPORTED_PATHS as an active Yoke-owned harness
    input for /yoke do."""

    @pytest.fixture
    def text(self) -> str:
        return _read(YOKE_DOCS / "commands.md")

    def test_refine_advances_status(self, text):
        """Refine must no longer be described as 'does not advance status'."""
        # Find the /yoke refine section.
        match = re.search(r"### refine\b", text)
        assert match, "commands.md missing '### refine' section"
        # Slice the refine section up to the next top-level ### heading.
        section_start = match.start()
        next_heading = re.search(r"\n### \w", text[section_start + 1 :])
        section_end = section_start + 1 + (next_heading.start() if next_heading else len(text))
        section = text[section_start:section_end]
        assert "does not advance status" not in section, (
            "commands.md refine section still claims refine 'does not advance status'"
        )
        assert "advances status" in section, (
            "commands.md refine section must explicitly describe status advancement"
        )

    def test_polish_advances_status(self, text):
        """Polish must no longer be described as 'does not advance status'."""
        match = re.search(r"### polish\b", text)
        assert match, "commands.md missing '### polish' section"
        section_start = match.start()
        next_heading = re.search(r"\n### \w", text[section_start + 1 :])
        section_end = section_start + 1 + (next_heading.start() if next_heading else len(text))
        section = text[section_start:section_end]
        assert "does not advance status" not in section, (
            "commands.md polish section still claims polish 'does not advance status'"
        )
        assert (
            "reviewed-implementation" in section
            and "polishing-implementation" in section
            and "implemented" in section
        ), "commands.md polish section must describe reviewed-implementation -> polishing-implementation -> implemented"
        assert "fresh `/yoke usher` command entrypoint" in section, (
            "commands.md polish section must say usher begins as a fresh command entrypoint"
        )

    def test_do_section_no_active_supported_paths_env_var(self, text):
        """YOKE_SUPPORTED_PATHS must not appear as an active Yoke-owned
        harness input. Supported paths are derived server-side from shared
        registry truth plus manifest limitations."""
        assert "YOKE_SUPPORTED_PATHS" not in text, (
            "commands.md must not reference YOKE_SUPPORTED_PATHS as an active env var "
            "(YOK-1299: capabilities derived server-side from shared registry plus manifest limitations)"
        )


# ---------------------------------------------------------------------------
# TestStateManagementDoc — ownership and transition truth
# ---------------------------------------------------------------------------


class TestStateManagementDoc:
    """AC-3: state-management.md must not misstate idea-refinement
    ownership or flatten the issue/epic split."""

    @pytest.fixture
    def text(self) -> str:
        return _read(DOCS / "state-management.md")

    def test_refining_idea_not_owned_by_shepherd(self, text):
        """The ownership table row for refining-idea must not claim Shepherd."""
        # Match the status table row.
        pattern = re.compile(r"^\|\s*`refining-idea`\s*\|\s*([^|]+?)\s*\|", re.MULTILINE)
        match = pattern.search(text)
        assert match, "state-management.md missing refining-idea ownership table row"
        owner = match.group(1)
        assert "Shepherd" not in owner, (
            f"state-management.md still claims Shepherd owns refining-idea (got: {owner!r})"
        )
        assert "Refine" in owner or "refine" in owner, (
            f"state-management.md refining-idea owner must be Refine (got: {owner!r})"
        )

    def test_refined_idea_not_owned_by_shepherd(self, text):
        pattern = re.compile(r"^\|\s*`refined-idea`\s*\|\s*([^|]+?)\s*\|", re.MULTILINE)
        match = pattern.search(text)
        assert match, "state-management.md missing refined-idea ownership table row"
        owner = match.group(1)
        assert "Shepherd" not in owner, (
            f"state-management.md still claims Shepherd owns refined-idea (got: {owner!r})"
        )

    def test_spec_refinement_no_longer_uses_shepherd(self, text):
        """The Backlog Item Lifecycle transitions table must not say
        /yoke shepherd starts spec refinement — that belongs to /yoke refine."""
        # Look for the stale pattern: "Spec refinement started | `/yoke shepherd`".
        assert not re.search(
            r"Spec refinement started\s*\|\s*`/yoke shepherd`", text
        ), "state-management.md still says /yoke shepherd starts spec refinement"
        assert "Shepherd starts spec refinement" not in text, (
            "state-management.md still contains stale prose claiming Shepherd starts spec refinement"
        )

    def test_usher_boundary_keeps_polish_as_pre_usher_owner(self, text):
        """The delivery-lifecycle ownership boundary must keep polish, not
        conduct/advance, as the owner of reviewed-implementation -> implemented."""
        match = re.search(
            r"### Usher Ownership Boundary\b(.*?)(?=\n### |\Z)", text, re.DOTALL
        )
        assert match, "state-management.md missing '### Usher Ownership Boundary' section"
        section = match.group(1)
        assert "Polish" in section, (
            "state-management.md Usher Ownership Boundary must name Polish as a separate owner"
        )
        assert (
            "reviewed-implementation" in section
            and "polishing-implementation" in section
            and "implemented" in section
        ), (
            "state-management.md Usher Ownership Boundary must describe the "
            "reviewed-implementation -> polishing-implementation -> implemented handoff"
        )
        assert not re.search(
            r"Conduct/Advance.*polishing-implementation.*implemented",
            section,
            re.DOTALL,
        ), (
            "state-management.md Usher Ownership Boundary still assigns the "
            "polishing-implementation -> implemented transition to Conduct/Advance"
        )

    def test_state_management_uses_structured_fields_not_raw_body_claim(self, text):
        assert "Specs live directly in backlog item bodies." not in text, (
            "state-management.md still claims specs live directly in raw backlog item bodies"
        )
        # body is now a virtual rendered field, not stored
        assert "virtual rendered field" in text, (
            "state-management.md should explain that body is a virtual rendered field"
        )

    def test_epic_task_flow_includes_reviewed_and_polish(self, text):
        match = re.search(
            r"## Epic Task Status Flow\b(.*?)(?=\n## |\Z)", text, re.DOTALL
        )
        assert match, "state-management.md missing '## Epic Task Status Flow' section"
        section = match.group(1)
        assert "reviewed-implementation" in section
        assert "polishing-implementation" in section
        assert not re.search(
            r"reviewing-implementation\s*→\s*implemented", section
        ), "state-management.md Epic Task Status Flow still skips reviewed-implementation/polish"

    def test_backlog_item_flow_splits_issue_and_epic_implementation_entry(self, text):
        assert "refined-idea / `planned` → `implementing`" not in text
        assert "refined-idea / planned → implementing" not in text
        assert "/yoke advance YOK-N implementation" in text
        assert "/yoke conduct YOK-N" in text


# ---------------------------------------------------------------------------
# TestCodexCapabilityDocs — OVERVIEW.md and harness docs must match registry truth
# ---------------------------------------------------------------------------


class TestCodexCapabilityDocs:
    """AC-5: OVERVIEW.md and other Codex-capability surfaces must not
    describe Codex as shepherd-only or reference deleted Codex shell wrappers
    as active entry surfaces."""

    @pytest.fixture
    def manifest(self) -> dict:
        path = REPO / "runtime" / "harness" / "codex" / "manifest.json"
        return json.loads(_read(path))

    def test_shared_registry_declares_canonical_entrypoints(self, manifest):
        supports = manifest.get("supports", {})
        assert supports.get("command_source") == "shared_yoke_registry"
        assert "entrypoints" not in supports
        entrypoints = shared_entrypoints()
        expected = {
            "/yoke idea",
            "/yoke do",
            "/yoke refine",
            "/yoke advance",
            "/yoke polish",
            "/yoke usher",
        }
        assert expected.issubset(set(entrypoints)), (
            f"shared registry must advertise {expected}, got {entrypoints}"
        )

    def test_shared_registry_declares_canonical_downstream_paths(self, manifest):
        supports = manifest.get("supports", {})
        assert "downstream_paths" not in supports
        paths = shared_downstream_paths()
        expected = {"shepherd", "refine", "advance", "polish", "usher"}
        assert expected.issubset(set(paths)), (
            f"shared registry must advertise {expected} downstream paths, got {paths}"
        )

    def test_overview_does_not_claim_one_downstream_path(self):
        text = _read(DOCS / "OVERVIEW.md")
        # Catch any wording like "one downstream path" that implies shepherd-only.
        assert not re.search(
            r"one\s+downstream\s+(delivery\s+)?path", text, re.IGNORECASE
        ), "OVERVIEW.md still claims Codex has one downstream path"

    def test_overview_does_not_claim_two_entrypoints(self):
        text = _read(DOCS / "OVERVIEW.md")
        # Catch wording like "two entrypoints (/yoke idea, /yoke do)".
        assert not re.search(
            r"two\s+entrypoints\s*\(\s*`?/yoke idea`?", text, re.IGNORECASE
        ), "OVERVIEW.md still claims Codex has only two entrypoints"

    def test_overview_does_not_reference_deleted_codex_shell_wrappers(self):
        text = _read(DOCS / "OVERVIEW.md")
        for dead in ("yoke-entry.sh", "resolve-model.sh", "open-app.sh"):
            assert dead not in text, (
                f"OVERVIEW.md still references deleted Codex shell wrapper {dead}"
            )
