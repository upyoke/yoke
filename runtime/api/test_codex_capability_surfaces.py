"""Regression checks for Codex capability prose outside the primary docs.

The shared Yoke registry is the capability source. These checks cover
secondary operator surfaces that previously kept stale ``advance`` omissions
after the registry and main docs were corrected.

Note: collapsed Codex's session-lifecycle rendering into the shared
``yoke_core.hooks`` chain. The legacy
``ch._render_session_start_orientation`` / ``ch._render_prompt_submit_reminder``
helpers were deleted with the legacy ``codex_hooks`` module. The orientation
prose itself is now resolved through the runner's lifecycle dispatch and is
covered by ``runtime/harness/codex/SMOKE-TEST.md`` and the parity tests in
``runtime/harness/test_hook_runner_parity.py``. This file retains the
registry-based and doc-prose checks that survive the cutover.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.harness_capability_registry import (
    compact_entrypoint_display,
    safe_operator_surface_entrypoints,
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
EXPECTED_ADVANCE_COMMAND = "/yoke advance PREFIX-N implementation"
EXPECTED_PATHS = "shepherd, refine, advance, dash, blitz, polish, usher"


def _read(rel_path: str) -> str:
    path = REPO / rel_path
    assert path.is_file(), f"expected file to exist: {path}"
    return path.read_text(encoding="utf-8")


def test_codex_hook_orientation_lists_registry_advance_path():
    # Registry-based source-of-truth checks retained after the cutover.
    # The Codex per-event orientation rendering helpers were deleted with the
    # legacy ``codex_hooks`` module; the registry is the contract surface.
    assert EXPECTED_ADVANCE_COMMAND in compact_entrypoint_display()
    assert ", ".join(shared_downstream_paths()) == EXPECTED_PATHS


def test_conduct_is_direct_safe_surface_not_session_offer_path():
    assert "/yoke conduct" in safe_operator_surface_entrypoints("codex")
    assert "/yoke conduct" not in shared_entrypoints()
    assert "conduct" not in shared_downstream_paths()


def test_direct_execution_paths_are_offerable():
    # Dash and Blitz items are routable next_steps, so the shared registry must
    # advertise them or the offer-time compatibility filter drops every
    # candidate before a session ever sees one.
    paths = shared_downstream_paths()
    assert "dash" in paths
    assert "blitz" in paths


def test_codex_smoke_matrix_expects_advance_path():
    text = _read("runtime/harness/codex/SMOKE-TEST.md")

    assert f"Supported paths: {EXPECTED_PATHS}" in text
    assert f"supported_paths: {EXPECTED_PATHS}" in text
    assert "/yoke advance YOK-{N} implementation" in text
    assert "shepherd, refine, polish, usher" not in text


def test_hook_parity_map_matches_codex_shared_registry_summary():
    text = _read("docs/hook-parity-map.md")

    assert (
        "The shared Yoke registry exposes two intentionally different "
        "capability views."
    ) in text
    assert "safe operator surface" in text
    assert "narrower session-offer registry" in text
    assert "rather than copying either registry view" in text
    assert "/yoke advance" in text
    assert "/yoke conduct" in text
    assert "`advance`" in text
    assert "direct Codex invocation" in text
    assert "Conduct is not a session-offer entrypoint or downstream path" in text
    assert "five entrypoints" not in text
    assert "four downstream paths" not in text


def test_command_references_dual_classify_advance():
    for rel_path in (
        ".yoke/docs/reference/commands.md",
        ".agents/skills/yoke/SKILL.md",
        ".agents/skills/yoke/help/SKILL.md",
    ):
        text = _read(rel_path)
        # These files ship verbatim into target projects, so they teach the
        # generic ``PREFIX-N`` placeholder rather than this repo's item prefix
        # that ``EXPECTED_ADVANCE_COMMAND`` asserts against the live registry.
        assert "/yoke advance PREFIX-N implementation" in text
        assert "other than `implementation`" in text or (
            "advance targets other than implementation" in text
        )
