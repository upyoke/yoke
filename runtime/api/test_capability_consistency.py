"""Regression: harness manifest, lifecycle docs, and harness docs must agree.

The Yoke-owned harness contract is that command/path truth flows from the
shared Yoke registry, with each harness manifest only declaring identity and
explicit substrate limitations. This module locks the agreement so that:

1. The shared registry declares the registered operator entrypoints used by
   current immutable workflow-version skill bindings.
2. ``docs/public/guides/codex-harness.md`` lists the same entrypoints and downstream paths in its
   operator-facing tables.
3. ``docs/public/guides/codex-harness.md``, ``docs/OVERVIEW.md``, and ``docs/harness-bootstrap.md``
   never claim that the registered ``/yoke implement`` entrypoint is
   unsupported by the harness.
4. Harness-shared bootstrap doctrine treats ``/yoke implement YOK-N`` as an
   operator-facing entrypoint with registered lifecycle writes.

These checks operate on the tracked filesystem (manifest JSON + markdown
files) without touching the database, git, or any network.
"""

from __future__ import annotations

from yoke_contracts.skill_registry import SKILLS_BY_ID

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
HARNESS = REPO / "runtime" / "harness"


def _read(path: Path) -> str:
    assert path.is_file(), f"expected file to exist: {path}"
    return path.read_text(encoding="utf-8")


# Registered command capabilities are independent of which immutable workflow
# versions currently bind them.
SHARED_WORKFLOW_ENTRYPOINTS = {
    "/yoke idea",
    "/yoke refine",
    "/yoke implement",
    "/yoke polish",
    "/yoke usher",
}

SHARED_WORKFLOW_DOWNSTREAM_PATHS = {
    "shepherd",
    "refine",
    "implement",
    "polish",
    "usher",
}


@pytest.fixture(scope="module")
def codex_manifest() -> dict:
    return json.loads(_read(HARNESS / "codex" / "manifest.json"))


@pytest.fixture(scope="module")
def codex_md() -> str:
    return _read(REPO / "docs/public/guides/codex-harness.md")


@pytest.fixture(scope="module")
def overview_md() -> str:
    return _read(DOCS / "OVERVIEW.md")


@pytest.fixture(scope="module")
def harness_bootstrap_md() -> str:
    return _read(DOCS / "harness-bootstrap.md")


@pytest.fixture(scope="module")
def lifecycle_md() -> str:
    return _read(YOKE_DOCS / "lifecycle.md")


class TestSharedRegistryAdvertisesImplement:
    """The shared registry must list ``/yoke implement`` so capability truth
    aligns with registered workflow skill bindings."""

    def test_implement_in_entrypoints(self):
        entrypoints = shared_entrypoints()
        assert "/yoke implement" in entrypoints, (
            "shared registry must advertise /yoke implement as an entrypoint"
        )

    def test_implement_in_downstream_paths(self):
        paths = shared_downstream_paths()
        assert "implement" in paths, (
            "shared registry must advertise 'implement' as a downstream path"
        )

    def test_registered_workflow_commands_in_entrypoints(self):
        entrypoints = set(shared_entrypoints())
        missing = SHARED_WORKFLOW_ENTRYPOINTS - entrypoints
        assert not missing, (
            f"shared registry is missing workflow entrypoints: {missing}"
        )

    def test_registered_workflow_commands_in_downstream_paths(self):
        paths = set(shared_downstream_paths())
        missing = SHARED_WORKFLOW_DOWNSTREAM_PATHS - paths
        assert not missing, (
            f"shared registry is missing workflow downstream paths: {missing}"
        )

    def test_codex_manifest_does_not_copy_command_truth(self, codex_manifest):
        supports = codex_manifest.get("supports", {})
        assert supports.get("command_source") == "shared_yoke_registry"
        assert "entrypoints" not in supports
        assert "downstream_paths" not in supports


class TestCodexMdMatchesRegistry:
    """``docs/public/guides/codex-harness.md`` must render registry truth, not stale capability
    prose. The user-facing supported-entrypoints table must list every
    shared entrypoint, and the supported-downstream-paths table must
    list every shared path."""

    def test_supported_entrypoints_table_lists_implement(self, codex_md):
        # The supported entrypoints section is the table immediately after
        # ``### Supported entrypoints``. We grab it up to the next ``###``.
        match = re.search(
            r"### Supported entrypoints\b(.*?)(?=\n### |\Z)",
            codex_md,
            re.DOTALL,
        )
        assert match, (
            "docs/public/guides/codex-harness.md missing '### Supported entrypoints' section"
        )
        section = match.group(1)
        assert "/yoke implement" in section, (
            "docs/public/guides/codex-harness.md supported entrypoints table must list /yoke implement"
        )

    def test_supported_downstream_paths_table_lists_implement(self, codex_md):
        match = re.search(
            r"### Supported downstream paths\b(.*?)(?=\n### |\Z)",
            codex_md,
            re.DOTALL,
        )
        assert match, (
            "docs/public/guides/codex-harness.md missing '### Supported downstream paths' section"
        )
        section = match.group(1)
        # Pull the table lines that look like ``| `name` | … |``.
        rows = re.findall(r"^\|\s*`([^`]+)`\s*\|", section, re.MULTILINE)
        assert "implement" in rows, (
            "docs/public/guides/codex-harness.md supported downstream paths table must list 'implement' "
            f"(got rows: {rows})"
        )

    def test_no_implement_in_unsupported_list(self, codex_md):
        # The Limitations section names structural compat gaps as bullet
        # lines. /yoke implement must never be named as a structural
        # limitation; mentioning it elsewhere in prose is fine.
        match = re.search(
            r"### Limitations\b(.*?)(?=\n## |\Z)",
            codex_md,
            re.DOTALL,
        )
        assert match, (
            "docs/public/guides/codex-harness.md missing '### Limitations' section"
        )
        section = match.group(1)
        limitation_bullets = re.findall(r"^- `(/yoke \S+)`", section, re.MULTILINE)
        assert "/yoke implement" not in limitation_bullets, (
            f"docs/public/guides/codex-harness.md still lists /yoke implement as a structural limitation "
            f"(bullets found: {limitation_bullets})"
        )

    def test_no_stale_implement_unsupported_phrasing(self, codex_md):
        # The previous fallthrough sentence implied implement was unsupported.
        # Gate against any future drift by ensuring 'implement' is never named
        # as part of the not-yet-supported set.
        assert not re.search(
            r"not yet supported in Codex[^\n]*implement",
            codex_md,
        ), (
            "docs/public/guides/codex-harness.md still claims /yoke implement is not yet supported"
        )
        assert not re.search(
            r"implement[^\n]*not yet supported in Codex",
            codex_md,
        ), (
            "docs/public/guides/codex-harness.md still claims /yoke implement is not yet supported"
        )


class TestOverviewMatchesRegistry:
    """``docs/OVERVIEW.md`` must render the same registry truth in its
    Codex-adapter description."""

    def test_overview_does_not_call_implement_out_of_scope(self, overview_md):
        # Match the exact stale phrasing rather than any mention of 'implement' —
        # OVERVIEW.md legitimately mentions implement in lifecycle context.
        # Match comma- or list-formatted "out of scope" assertions that include
        # `implement`.
        match = re.search(
            r"\(([^)]*?)\s+are\s+deliberately\s+out\s+of\s+scope",
            overview_md,
        )
        if match:
            out_of_scope = match.group(1).lower()
            assert "implement" not in out_of_scope, (
                "OVERVIEW.md still lists `implement` as deliberately out of scope; "
                "the shared registry now advertises implement as an entrypoint."
            )

    def test_overview_points_to_capability_owners(self, overview_md):
        assert "runtime/harness/{claude,codex,cursor}/manifest.json" in overview_md
        assert "shared registry plus the manifest" in overview_md
        assert "harness-bootstrap.md" in overview_md


class TestHarnessBootstrapClassifiesImplement:
    """``docs/harness-bootstrap.md`` must classify ``/yoke implement YOK-N``
    as an operator command and teach registered lifecycle writes."""

    def test_safe_operator_commands_table_lists_implement(self, harness_bootstrap_md):
        match = re.search(
            r"## Safe Operator Commands\b(.*?)(?=\n## )",
            harness_bootstrap_md,
            re.DOTALL,
        )
        assert match, "harness-bootstrap.md missing '## Safe Operator Commands'"
        section = match.group(1)
        assert SKILLS_BY_ID["implement"].display in section, (
            "harness-bootstrap.md Safe Operator Commands table must list "
            "/yoke implement YOK-N as an operator-facing entry"
        )
        assert "/yoke " + "advance" not in section

    def test_classification_teaches_registered_lifecycle_writes(self, harness_bootstrap_md):
        match = re.search(
            r"## Command Classification\b(.*?)(?=\n## )",
            harness_bootstrap_md,
            re.DOTALL,
        )
        assert match, "harness-bootstrap.md missing '## Command Classification'"
        section = match.group(1)
        assert "Registered CLI/function" in section
        assert "yoke lifecycle transition" in section


class TestLifecycleDocsAlignWithManifest:
    """Lifecycle docs must derive commands from immutable skill bindings."""

    def test_lifecycle_md_names_registered_skill_resolution(self, lifecycle_md):
        assert "immutable workflow version" in lifecycle_md
        assert "skill_bindings" in lifecycle_md
        assert "/yoke <skill_id>" in lifecycle_md

    def test_lifecycle_registered_skill_table_includes_implement(self, lifecycle_md):
        match = re.search(
            r"## Registered Skill Boundaries\b(.*?)(?=\n## )",
            lifecycle_md,
            re.DOTALL,
        )
        assert match, (
            ".yoke/docs/reference/lifecycle.md missing '## Registered Skill Boundaries'"
        )
        section = match.group(1)
        assert "`implement`" in section, (
            "lifecycle.md registered skill table must list implement"
        )
        assert "from_stage_id <= current_stage < through_stage_id" in section


def test_operator_commands_resolve_to_existing_skills():
    from yoke_core.domain.harness_capability_registry import safe_operator_surface

    for command in safe_operator_surface():
        skill_id = command.entrypoint.split()[-1]
        assert (REPO / ".agents/skills/yoke" / skill_id / "SKILL.md").is_file()
        packaged = REPO / "packages/yoke-core/src/yoke_core/install_bundle_tree"
        assert (packaged / ".agents/skills/yoke" / skill_id / "SKILL.md").is_file()
