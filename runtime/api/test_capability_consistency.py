"""Regression: harness manifest, lifecycle docs, and harness docs must agree.

The Yoke-owned harness contract is that command/path truth flows from the
shared Yoke registry, with each harness manifest only declaring identity and
explicit substrate limitations. This module locks the agreement so that:

1. The shared registry declares every command-boundary that the issue
   lifecycle requires (``/yoke idea``, ``/yoke do``, ``/yoke refine``,
   ``/yoke advance``, ``/yoke polish``, ``/yoke usher``).
2. ``CODEX.md`` lists the same entrypoints and downstream paths in its
   operator-facing tables.
3. ``CODEX.md``, ``docs/OVERVIEW.md``, and ``docs/harness-bootstrap.md``
   never simultaneously claim that ``/yoke advance`` is required (by the
   issue lifecycle) and unsupported (by the harness).
4. Harness-shared bootstrap doctrine treats ``/yoke advance YOK-N
   implementation`` as the operator-facing issue implementation entry, not
   as an internal-only sub-skill.

These checks operate on the tracked filesystem (manifest JSON + markdown
files) without touching the database, git, or any network.
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
HARNESS = REPO / "runtime" / "harness"


def _read(path: Path) -> str:
    assert path.is_file(), f"expected file to exist: {path}"
    return path.read_text(encoding="utf-8")


# Required by the issue lifecycle for any harness that supports issues
# end-to-end. The four other entrypoints (``/yoke idea``, ``/yoke do``,
# ``/yoke refine``, ``/yoke polish``, ``/yoke usher``) round out the
# operator-facing happy path.
ISSUE_LIFECYCLE_ENTRYPOINTS = {
    "/yoke idea",
    "/yoke do",
    "/yoke refine",
    "/yoke advance",
    "/yoke polish",
    "/yoke usher",
}

ISSUE_LIFECYCLE_DOWNSTREAM_PATHS = {
    "shepherd",
    "refine",
    "advance",
    "polish",
    "usher",
}


@pytest.fixture(scope="module")
def codex_manifest() -> dict:
    return json.loads(_read(HARNESS / "codex" / "manifest.json"))


@pytest.fixture(scope="module")
def codex_md() -> str:
    return _read(REPO / "CODEX.md")


@pytest.fixture(scope="module")
def overview_md() -> str:
    return _read(DOCS / "OVERVIEW.md")


@pytest.fixture(scope="module")
def harness_bootstrap_md() -> str:
    return _read(DOCS / "harness-bootstrap.md")


@pytest.fixture(scope="module")
def lifecycle_md() -> str:
    return _read(DOCS / "lifecycle.md")


@pytest.fixture(scope="module")
def advance_skill_md() -> str:
    return _read(REPO / ".agents" / "skills" / "yoke" / "advance" / "SKILL.md")


class TestSharedRegistryAdvertisesAdvance:
    """The shared registry must list ``/yoke advance`` so capability truth
    aligns with the operator-facing issue lifecycle."""

    def test_advance_in_entrypoints(self):
        entrypoints = shared_entrypoints()
        assert "/yoke advance" in entrypoints, (
            "shared registry must advertise /yoke advance as an entrypoint "
            "(issue lifecycle requires it as the implementation entry)"
        )

    def test_advance_in_downstream_paths(self):
        paths = shared_downstream_paths()
        assert "advance" in paths, (
            "shared registry must advertise 'advance' as a downstream path"
        )

    def test_full_issue_lifecycle_in_entrypoints(self):
        entrypoints = set(shared_entrypoints())
        missing = ISSUE_LIFECYCLE_ENTRYPOINTS - entrypoints
        assert not missing, (
            f"shared registry is missing issue lifecycle entrypoints: {missing}"
        )

    def test_full_issue_lifecycle_in_downstream_paths(self):
        paths = set(shared_downstream_paths())
        missing = ISSUE_LIFECYCLE_DOWNSTREAM_PATHS - paths
        assert not missing, (
            f"shared registry is missing issue lifecycle downstream paths: {missing}"
        )

    def test_codex_manifest_does_not_copy_command_truth(self, codex_manifest):
        supports = codex_manifest.get("supports", {})
        assert supports.get("command_source") == "shared_yoke_registry"
        assert "entrypoints" not in supports
        assert "downstream_paths" not in supports


class TestCodexMdMatchesRegistry:
    """``CODEX.md`` must render registry truth, not stale capability
    prose. The user-facing supported-entrypoints table must list every
    shared entrypoint, and the supported-downstream-paths table must
    list every shared path."""

    def test_supported_entrypoints_table_lists_advance(self, codex_md):
        # The supported entrypoints section is the table immediately after
        # ``### Supported entrypoints``. We grab it up to the next ``###``.
        match = re.search(
            r"### Supported entrypoints\b(.*?)(?=\n### |\Z)",
            codex_md,
            re.DOTALL,
        )
        assert match, "CODEX.md missing '### Supported entrypoints' section"
        section = match.group(1)
        assert "/yoke advance" in section, (
            "CODEX.md supported entrypoints table must list /yoke advance"
        )

    def test_supported_downstream_paths_table_lists_advance(self, codex_md):
        match = re.search(
            r"### Supported downstream paths\b(.*?)(?=\n### |\Z)",
            codex_md,
            re.DOTALL,
        )
        assert match, (
            "CODEX.md missing '### Supported downstream paths' section"
        )
        section = match.group(1)
        # Pull the table lines that look like ``| `name` | … |``.
        rows = re.findall(r"^\|\s*`([^`]+)`\s*\|", section, re.MULTILINE)
        assert "advance" in rows, (
            "CODEX.md supported downstream paths table must list 'advance' "
            f"(got rows: {rows})"
        )

    def test_no_advance_in_unsupported_list(self, codex_md):
        # The Limitations section names structural compat gaps as bullet
        # lines. /yoke advance must never be named as a structural
        # limitation; mentioning it elsewhere in prose is fine.
        match = re.search(
            r"### Limitations\b(.*?)(?=\n## |\Z)",
            codex_md,
            re.DOTALL,
        )
        assert match, "CODEX.md missing '### Limitations' section"
        section = match.group(1)
        limitation_bullets = re.findall(
            r"^- `(/yoke \S+)`", section, re.MULTILINE
        )
        assert "/yoke advance" not in limitation_bullets, (
            f"CODEX.md still lists /yoke advance as a structural limitation "
            f"(bullets found: {limitation_bullets})"
        )

    def test_no_stale_advance_unsupported_phrasing(self, codex_md):
        # The previous fallthrough sentence implied advance was unsupported.
        # Gate against any future drift by ensuring 'advance' is never named
        # as part of the not-yet-supported set.
        assert not re.search(
            r"not yet supported in Codex[^\n]*advance",
            codex_md,
        ), "CODEX.md still claims /yoke advance is not yet supported"
        assert not re.search(
            r"advance[^\n]*not yet supported in Codex",
            codex_md,
        ), "CODEX.md still claims /yoke advance is not yet supported"


class TestOverviewMatchesRegistry:
    """``docs/OVERVIEW.md`` must render the same registry truth in its
    Codex-adapter description."""

    def test_overview_does_not_call_advance_out_of_scope(self, overview_md):
        # Match the exact stale phrasing rather than any mention of 'advance' —
        # OVERVIEW.md legitimately mentions advance in lifecycle context.
        # Match comma- or list-formatted "out of scope" assertions that include
        # `advance`.
        match = re.search(
            r"\(([^)]*?)\s+are\s+deliberately\s+out\s+of\s+scope",
            overview_md,
        )
        if match:
            out_of_scope = match.group(1).lower()
            assert "advance" not in out_of_scope, (
                "OVERVIEW.md still lists `advance` as deliberately out of scope; "
                "the shared registry now advertises advance as an entrypoint."
            )

    def test_overview_lists_advance_in_codex_capability(self, overview_md):
        # The OVERVIEW.md paragraph describing the shared Codex command surface
        # must include /yoke advance.
        capability_phrase_match = re.search(
            r"shared Yoke registry[^.]*entrypoints[^.]*\.",
            overview_md,
            re.DOTALL,
        )
        assert capability_phrase_match, (
            "OVERVIEW.md missing the Codex capability description sentence"
        )
        section = capability_phrase_match.group(0)
        assert "/yoke advance" in section, (
            "OVERVIEW.md Codex registry description must include /yoke advance"
        )


class TestHarnessBootstrapClassifiesAdvance:
    """``docs/harness-bootstrap.md`` must classify the operator-facing
    ``/yoke advance YOK-N implementation`` as a Tier 1 command (or a
    dual-tier surface explicitly), not as Tier 2 internal-only."""

    def test_safe_operator_commands_table_lists_advance(self, harness_bootstrap_md):
        # The table sits between ``## 2. Safe Operator Commands`` and the
        # next top-level heading.
        match = re.search(
            r"## 2\. Safe Operator Commands\b(.*?)(?=\n## )",
            harness_bootstrap_md,
            re.DOTALL,
        )
        assert match, "harness-bootstrap.md missing '## 2. Safe Operator Commands'"
        section = match.group(1)
        assert "/yoke advance YOK-N implementation" in section, (
            "harness-bootstrap.md Safe Operator Commands table must list "
            "/yoke advance YOK-N implementation as an operator-facing entry"
        )

    def test_tier_2_clarifies_advance_is_dual_classified(
        self, harness_bootstrap_md
    ):
        # The Tier 2 section is between '### Tier 2: Internal sub-skills' and
        # the next '###' heading.
        match = re.search(
            r"### Tier 2: Internal sub-skills\b(.*?)(?=\n### )",
            harness_bootstrap_md,
            re.DOTALL,
        )
        assert match, (
            "harness-bootstrap.md missing '### Tier 2: Internal sub-skills'"
        )
        section = match.group(1)
        # The section must call out that the `implementation` form is also
        # operator-facing so Tier 1 vs Tier 2 stays honest.
        assert "operator-facing" in section.lower(), (
            "harness-bootstrap.md Tier 2 section must clarify that "
            "/yoke advance implementation is also operator-facing"
        )


class TestAdvanceSkillNotInternalOnly:
    """The ``advance`` skill body must not claim it is purely internal —
    that wording contradicts the issue lifecycle and the harness manifest."""

    def test_skill_does_not_claim_not_operator_facing(self, advance_skill_md):
        assert "Not operator-facing" not in advance_skill_md, (
            ".agents/skills/yoke/advance/SKILL.md still claims the skill is "
            "'Not operator-facing'; /yoke advance YOK-N implementation IS "
            "the issue implementation entry."
        )


class TestLifecycleDocsAlignWithManifest:
    """The lifecycle command-family doc must continue to name ``/yoke
    advance ... implementation`` as the issue implementation entry. This
    locks the agreement: lifecycle says "use advance", manifests say
    "we support advance", harness docs say "we support advance"."""

    def test_lifecycle_md_names_advance_implementation_entry(self, lifecycle_md):
        assert "/yoke advance YOK-N implementation" in lifecycle_md, (
            "docs/lifecycle.md must continue to name "
            "/yoke advance YOK-N implementation as the issue implementation entry"
        )

    def test_lifecycle_command_boundary_table_includes_advance(self, lifecycle_md):
        match = re.search(
            r"## Command Boundary Summary\b(.*?)(?=\n## )",
            lifecycle_md,
            re.DOTALL,
        )
        assert match, "docs/lifecycle.md missing '## Command Boundary Summary'"
        section = match.group(1)
        assert "/yoke advance" in section, (
            "lifecycle.md Command Boundary Summary must list /yoke advance"
        )


