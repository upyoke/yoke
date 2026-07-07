"""/ AC-5 / AC-12 regressions for the bootstrap main_agent packet.

Lives in its own sibling test module File Budget so
``test_bootstrap.py`` does not press the file-line cap. Verifies that:

- The ``main_agent`` packet is rendered through the shared
  ``runtime.harness.bootstrap_packets`` helper (compact + full).
- Bootstrap compact / full orientation injects the ``main_agent`` packet
  via the same shared bootstrap path that Codex and Claude startup
  surfaces consume — no hand-copied prose in either rendered orientation.
- The ``harness_contract`` substrate name is mentioned in the helper's
  prefix so the operator orientation distinguishes the LLM-facing packet
  layer from the substrate manifest contract.
- The packet is generated, never hand-copied: the rendered body matches
  ``schema_api_context.render_role_packet("main_agent")``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain import schema_api_context
from yoke_core.tools import python_interpreter_probe
from runtime.harness.bootstrap import load_spec, render_compact, render_full
from runtime.harness.bootstrap_packets import (
    INSTALL_ADVISORY_COMMAND,
    INSTALL_ADVISORY_HEADING,
    INSTALL_ADVISORY_POINTER,
    MAIN_AGENT_ROLE,
    RENDER_FAILURE_PREFIX,
    append_main_agent_compact,
    append_main_agent_full,
    render_install_advisory_block,
    render_interpreter_advisory_block,
    render_main_agent_block,
    render_main_agent_block_full,
)


@pytest.fixture
def repo_root() -> Path:
    """Resolve the workspace-anchored live Yoke checkout root.

    Re-uses the shared renderer-test helper so this bootstrap-side test
    targets the same checkout the renderer tests do, regardless of the
    pytest subprocess cwd.
    """
    from runtime.api.domain.test_agents_render_workspace_fixtures import (
        resolve_live_repo_root,
    )

    return resolve_live_repo_root()


@pytest.fixture
def spec(repo_root: Path) -> dict:
    return load_spec(repo_root / "runtime/harness/bootstrap-spec.json")


def test_main_agent_role_constant_matches_seed() -> None:
    """The bootstrap packet helper resolves to the canonical
    ``main_agent`` role declared in the schema_api_context seed."""

    from yoke_core.domain import schema_api_context_seed as seed

    assert MAIN_AGENT_ROLE == "main_agent"
    assert MAIN_AGENT_ROLE in seed.ROLE_TOPICS


def test_render_main_agent_block_returns_generated_body() -> None:
    """The compact block embeds the freshly generated packet body —
    never a hand-copied snippet of schema text."""

    block = render_main_agent_block()
    assert block, "compact main_agent block must not be empty"
    fresh = schema_api_context.render_role_packet("main_agent").rstrip()
    for line in fresh.splitlines():
        if not line.strip():
            continue
        assert line in block, (
            f"generated packet line not found in compact block: {line!r}"
        )


def test_render_main_agent_block_full_includes_heading_and_body() -> None:
    block = render_main_agent_block_full()
    assert block, "full main_agent block must not be empty"
    assert block.startswith("=== "), (
        "full block must lead with an ``=== ... ===`` heading to match "
        "the surrounding bootstrap render_full layout"
    )
    fresh = schema_api_context.render_role_packet("main_agent").rstrip()
    for line in fresh.splitlines():
        if not line.strip():
            continue
        assert line in block


def test_render_compact_injects_main_agent_packet(
    repo_root: Path, spec: dict
) -> None:
    """the shared bootstrap render path used by Codex /
    Claude startup surfaces injects the ``main_agent`` packet."""

    rendered = render_compact(repo_root, spec)
    assert "main_agent" in rendered
    block = render_main_agent_block()
    for line in block.splitlines():
        if not line.strip():
            continue
        assert line in rendered, (
            f"compact orientation missing packet line: {line!r}"
        )


def test_render_full_injects_main_agent_packet(
    repo_root: Path, spec: dict
) -> None:
    rendered = render_full(repo_root, spec)
    assert "main_agent" in rendered
    block = render_main_agent_block_full()
    for line in block.splitlines():
        if not line.strip():
            continue
        assert line in rendered, (
            f"full orientation missing packet line: {line!r}"
        )


def test_main_agent_block_names_harness_contract_distinction() -> None:
    """/ AC-12: the bootstrap orientation distinguishes
    the LLM-facing packet layer (``main_agent`` / ``*_agent``) from the
    substrate manifest contract (``harness_contract``). Operators reading
    the rendered orientation must see both names so the layers are not
    conflated."""

    block = render_main_agent_block()
    assert "harness_contract" in block, (
        "compact main_agent block must name the harness_contract layer "
        "to keep the LLM packet vs. substrate manifest distinction visible"
    )
    for role in (
        "architect_agent",
        "engineer_agent",
        "tester_agent",
        "simulator_agent",
        "boss_agent",
    ):
        assert role in block, (
            f"compact block must name subagent packet role {role!r}"
        )


def test_append_helpers_no_op_when_packet_unavailable(monkeypatch) -> None:
    """When the schema_api_context generator is unavailable (fresh
    checkout, broken bootstrap state), the append helpers must be a no-op so the
    bootstrap path stays fail-open."""

    import runtime.harness.bootstrap_packets as bp

    monkeypatch.setattr(bp, "_render_packet_body", lambda: "")
    lines: list = []
    bp.append_main_agent_compact(lines)
    assert lines == []
    parts: list = []
    bp.append_main_agent_full(parts)
    assert parts == []


def test_render_install_advisory_block_empty_when_yoke_on_path(
    monkeypatch,
) -> None:
    """When ``shutil.which("yoke")`` resolves, the advisory is empty so
    installed sessions see no noise."""

    import runtime.harness.bootstrap_packets as bp

    monkeypatch.setattr(bp.shutil, "which", lambda _name: "/usr/local/bin/yoke")
    assert render_install_advisory_block() == ""


def test_render_install_advisory_block_three_lines_when_missing(
    monkeypatch,
) -> None:
    """When ``shutil.which("yoke")`` returns None, the advisory renders
    the canonical 3-line block: heading, indented install command, and
    docs pointer."""

    import runtime.harness.bootstrap_packets as bp

    monkeypatch.setattr(bp.shutil, "which", lambda _name: None)
    block = render_install_advisory_block()
    lines = block.splitlines()
    assert lines == [
        INSTALL_ADVISORY_HEADING,
        INSTALL_ADVISORY_COMMAND,
        INSTALL_ADVISORY_POINTER,
    ]
    # Command line names the canonical install module (Refinement
    # Addendum CR-3 — must match Task 003's module name exactly).
    assert "install_yoke_launcher" in INSTALL_ADVISORY_COMMAND


def test_main_agent_block_prepends_advisory_when_yoke_missing(
    monkeypatch,
) -> None:
    """The compact ``main_agent`` block prepends the install advisory
    above the packet heading when ``yoke`` is not on PATH."""

    import runtime.harness.bootstrap_packets as bp

    monkeypatch.setattr(bp.shutil, "which", lambda _name: None)
    block = render_main_agent_block()
    assert block.startswith(INSTALL_ADVISORY_HEADING), (
        "advisory must appear at the very top of the compact block"
    )
    assert INSTALL_ADVISORY_COMMAND in block
    assert INSTALL_ADVISORY_POINTER in block


def test_main_agent_block_omits_advisory_when_yoke_on_path(
    monkeypatch,
) -> None:
    """The compact ``main_agent`` block omits the install advisory when
    ``yoke`` resolves on PATH — installed sessions see only the packet
    heading and body."""

    import runtime.harness.bootstrap_packets as bp

    monkeypatch.setattr(bp.shutil, "which", lambda _name: "/usr/local/bin/yoke")
    block = render_main_agent_block()
    assert INSTALL_ADVISORY_HEADING not in block
    assert INSTALL_ADVISORY_COMMAND not in block
    # Packet body still rendered.
    assert "main_agent" in block


def test_main_agent_block_full_prepends_advisory_when_yoke_missing(
    monkeypatch,
) -> None:
    """The full ``main_agent`` block prepends the install advisory above
    the ``=== ... ===`` heading when ``yoke`` is not on PATH."""

    import runtime.harness.bootstrap_packets as bp

    monkeypatch.setattr(bp.shutil, "which", lambda _name: None)
    block = render_main_agent_block_full()
    assert block.startswith(INSTALL_ADVISORY_HEADING)
    assert INSTALL_ADVISORY_COMMAND in block
    # The packet heading still follows the advisory.
    assert "=== " in block


class _SimulatedDriftError(RuntimeError):
    """Stand-in for ``schema_api_context.DriftError`` used by the
    render-failure regression test below. Defined as a subclass of a
    stdlib exception so the test does not couple to the live drift
    type, while still exercising the structured-banner code path."""


def test_render_main_agent_block_emits_loud_banner_on_render_failure(
    monkeypatch,
) -> None:
    """``_render_packet_body`` must NOT silently return ``""`` when
    ``render_role_packet`` raises. Instead it must return the
    structured render-failure banner so the compact and full bootstrap
    consumers surface it loudly. The banner must be non-empty, lead
    with the canonical :data:`RENDER_FAILURE_PREFIX`, and name the
    underlying error class so operators can identify the drift."""

    failure_message = "items.kind column not in seed"

    def _raises(_role: str) -> str:
        raise _SimulatedDriftError(failure_message)

    monkeypatch.setattr(schema_api_context, "render_role_packet", _raises)

    block = render_main_agent_block()
    assert block, "render-failure banner must be non-empty"
    assert RENDER_FAILURE_PREFIX in block, (
        "compact block must include the canonical "
        f"{RENDER_FAILURE_PREFIX!r} prefix"
    )
    assert _SimulatedDriftError.__name__ in block, (
        "banner must name the underlying error class"
    )
    assert failure_message in block, (
        "banner must propagate the underlying error message"
    )

    full = render_main_agent_block_full()
    assert RENDER_FAILURE_PREFIX in full, (
        "full block must propagate the render-failure banner"
    )
    assert _SimulatedDriftError.__name__ in full
    assert failure_message in full


# Interpreter-advisory coverage. Probe behavior is
# covered by test_python_interpreter_probe; these tests verify wiring.

_PR = python_interpreter_probe.ProbeResult
_BAD = _PR(False, "/usr/bin/python3", python_interpreter_probe.SENTINEL_MODULE, False)
_OK = _PR(True, "/opt/homebrew/bin/python3", None, False)


def test_compact_includes_interpreter_advisory(monkeypatch) -> None:
    monkeypatch.setattr(python_interpreter_probe, "probe", lambda: _BAD)
    block = render_main_agent_block()
    assert python_interpreter_probe.SENTINEL_MODULE in block
    assert "/usr/bin/python3" in block
    assert python_interpreter_probe.OVERRIDE_ENV_VAR in block


def test_compact_omits_interpreter_advisory_when_probe_ok(monkeypatch) -> None:
    monkeypatch.setattr(python_interpreter_probe, "probe", lambda: _OK)
    assert "Yoke interpreter check" not in render_main_agent_block()


def test_install_advisory_preserved_when_interpreter_fires(monkeypatch) -> None:
    """AC-8: both advisories may render; interpreter leads."""
    import runtime.harness.bootstrap_packets as bp

    monkeypatch.setattr(python_interpreter_probe, "probe", lambda: _BAD)
    monkeypatch.setattr(bp.shutil, "which", lambda _name: None)
    block = render_main_agent_block()
    assert INSTALL_ADVISORY_HEADING in block
    assert INSTALL_ADVISORY_COMMAND in block
    assert INSTALL_ADVISORY_POINTER in block
    interp_idx = block.find("Yoke interpreter check")
    install_idx = block.find(INSTALL_ADVISORY_HEADING)
    assert 0 <= interp_idx < install_idx


def test_full_variant_includes_interpreter_advisory(monkeypatch) -> None:
    monkeypatch.setattr(python_interpreter_probe, "probe", lambda: _BAD)
    block = render_main_agent_block_full()
    assert 0 <= block.find("Yoke interpreter check") < block.find("=== ")


def test_advisory_fail_open_on_probe_exception(monkeypatch) -> None:
    def _boom():
        raise RuntimeError("wedged")
    monkeypatch.setattr(python_interpreter_probe, "probe", _boom)
    assert render_interpreter_advisory_block() == ""
