"""Doc regression guards for workflow-version lifecycle and routing truth.

The runtime interprets every live item through its immutable workflow pin.
These tests keep the human-readable surfaces aligned with that authority while
preserving the independent generated-task lifecycle.

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
# Reference docs shipped to managed projects live under .yoke/docs/reference.
YOKE_DOCS = REPO / ".yoke" / "docs" / "reference"


def _read(path: Path) -> str:
    assert path.is_file(), f"expected file to exist: {path}"
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# TestBootstrapSpec — canonical lifecycle guide is loaded at bootstrap
# ---------------------------------------------------------------------------


class TestBootstrapSpec:
    """Bootstrap must load yoke/.yoke/docs/reference/lifecycle.md."""

    @pytest.fixture
    def spec(self) -> dict:
        path = REPO / "runtime" / "harness" / "bootstrap-spec.json"
        return json.loads(_read(path))

    def test_required_files_includes_lifecycle(self, spec):
        required = spec.get("required_files", [])
        assert ".yoke/docs/reference/lifecycle.md" in required, (
            "bootstrap-spec.json must include yoke/.yoke/docs/reference/lifecycle.md in required_files"
        )

    def test_lifecycle_loaded_after_commands(self, spec):
        """lifecycle.md should follow commands.md so readers get command
        vocabulary before the lifecycle tables that use it."""
        required = spec.get("required_files", [])
        assert ".yoke/docs/reference/commands.md" in required
        assert required.index(".yoke/docs/reference/lifecycle.md") > required.index(
            ".yoke/docs/reference/commands.md"
        )


# ---------------------------------------------------------------------------
# TestLifecycleDoc — canonical human lifecycle guide covers command boundaries
# ---------------------------------------------------------------------------


class TestLifecycleDoc:
    """The lifecycle guide must teach immutable workflow-version authority."""

    @pytest.fixture
    def text(self) -> str:
        return _read(YOKE_DOCS / "lifecycle.md")

    def test_names_immutable_item_pin(self, text):
        assert "`workflow_id` / `workflow_version_id` pin" in text
        assert "exact pinned version" in text

    def test_definition_owns_lifecycle_shape(self, text):
        assert "Definitions own ordered stages" in text
        assert "target-stage gate" in text
        assert re.search(r"registered\s+skill bindings", text)
        assert "Do not copy a progression" in text

    def test_executor_boundary_is_half_open(self, text):
        assert "## Registered Skill Boundaries" in text
        assert "from_stage_id <= current_stage < through_stage_id" in text
        assert "/yoke <skill_id>" in text

    def test_shepherd_is_policy_bound(self, text):
        assert "`shepherd`" in text
        assert "compatible generated-task policy" in text
        assert "epic-only" not in text.lower()
        assert "epic command family" not in text.lower()

    def test_epic_task_lifecycle_remains_independent(self, text):
        match = re.search(
            r"## Canonical Epic Task Progression\b(.*?)(?=\n## |\Z)",
            text,
            re.DOTALL,
        )
        assert match, "lifecycle.md missing canonical epic-task progression"
        section = match.group(1)
        assert "planning" in section
        assert "reviewed-implementation" in section
        assert "polishing-implementation" in section
        assert "release" in section
        assert "done" in section

    def test_handoff_boundaries_require_fresh_entrypoints(self, text):
        assert "fresh command entrypoints" in text or "fresh command entrypoint" in text
        assert "through_stage_id" in text
        assert "next skill" in text

    def test_routes_to_canonical_routing_docs(self, text):
        assert "session-offer.md" in text
        assert "charge-frontier.md" in text


# ---------------------------------------------------------------------------
# TestCommandsDoc — refine/polish advance status, no stale supported-paths env var
# ---------------------------------------------------------------------------


class TestCommandsDoc:
    """Commands.md must match the live refine/polish skills and
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
        section_end = (
            section_start + 1 + (next_heading.start() if next_heading else len(text))
        )
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
        section_end = (
            section_start + 1 + (next_heading.start() if next_heading else len(text))
        )
        section = text[section_start:section_end]
        assert "does not advance status" not in section, (
            "commands.md polish section still claims polish 'does not advance status'"
        )
        assert (
            "reviewed-implementation" in section
            and "polishing-implementation" in section
            and "implemented" in section
        ), (
            "commands.md polish section must describe reviewed-implementation -> polishing-implementation -> implemented"
        )
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
    """State-management.md must derive item state from immutable pins."""

    @pytest.fixture
    def text(self) -> str:
        return _read(DOCS / "state-management.md")

    def test_definition_fields_own_item_state(self, text):
        assert "`workflow_id` and `workflow_version_id`" in text
        assert "ordered `stages`, `transitions`, and `terminal_stage_ids`" in text
        assert "gates referenced by each target stage" in text
        assert "`skill_bindings`, interpreted as half-open" in text

    def test_item_flow_has_no_workflow_id_branch(self, text):
        assert "## Pinned Item Stage Flow" in text
        assert "There is no global backlog-item progression" in text
        assert "no Issue/Epic item-type" in text
        for stale_heading in (
            "**Dash items:**",
            "**Blitz items:**",
            "**Issue items:**",
            "**Epic items:**",
        ):
            assert stale_heading not in text

    def test_live_routing_reads_exact_version(self, text):
        assert "yoke workflows item get YOK-N" in text
        assert "yoke workflows version get WORKFLOW VERSION" in text
        assert "Find the active half-open skill binding" in text
        assert "Invoke `/yoke <skill_id>`" in text

    def test_release_boundary_is_policy_and_binding_owned(self, text):
        match = re.search(
            r"### Release-stage skill boundary\b(.*?)(?=\n### |\Z)",
            text,
            re.DOTALL,
        )
        assert match, "state-management.md missing release-stage skill boundary"
        section = match.group(1)
        assert "`usher` binding" in section
        assert "`through_stage_id`" in section
        assert re.search(r"shared\s+stage ids do not imply", section)
        assert "Definitions without an `usher` binding" in section

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
        assert not re.search(r"reviewing-implementation\s*→\s*implemented", section), (
            "state-management.md Epic Task Status Flow still skips reviewed-implementation/polish"
        )

    def test_backlog_item_flow_uses_workflow_pin(self, text):
        assert "`workflow_id` is a registry key" in text
        assert "`workflow_version_id` selects the only authoritative" in text
        assert "target-stage gate references" in text


# ---------------------------------------------------------------------------
# TestCodexCapabilityDocs — OVERVIEW.md and harness docs must match registry truth
# ---------------------------------------------------------------------------


class TestCodexCapabilityDocs:
    """OVERVIEW.md and other Codex-capability surfaces must not
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
