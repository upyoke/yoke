"""Shared bootstrap block composition and machine advisories."""

from __future__ import annotations

from yoke_cli.config.install_advice import install_command

from pathlib import Path

import pytest

from yoke_core.tools import python_interpreter_probe
from yoke_core.hooks.bootstrap import load_spec, render_compact, render_full
from yoke_core.domain.main_agent_packet import (
    INSTALL_ADVISORY_HEADING,
    INSTALL_ADVISORY_POINTER,
    MAIN_AGENT_ROLE,
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


def test_startup_block_fits_the_smallest_inline_channel() -> None:
    """Measured, not assumed: the block fits every harness inline ceiling."""

    from yoke_contracts.hook_inline_context import INLINE_CONTEXT_BYTES

    spent = len(render_main_agent_block().encode("utf-8"))
    smallest = min(INLINE_CONTEXT_BYTES.values())
    assert spent < smallest, (
        f"startup block spends {spent} bytes against the smallest inline "
        f"ceiling of {smallest}"
    )


def test_render_main_agent_block_full_leads_with_its_heading() -> None:
    block = render_main_agent_block_full()
    assert block, "full main_agent block must not be empty"
    assert block.startswith("=== "), (
        "full block must lead with an ``=== ... ===`` heading to match "
        "the surrounding bootstrap render_full layout"
    )


def test_render_compact_injects_main_agent_block(repo_root: Path, spec: dict) -> None:
    """The shared bootstrap render path injects the startup block."""

    rendered = render_compact(repo_root, spec)
    assert "main_agent" in rendered
    for line in render_main_agent_block().splitlines():
        if line.strip():
            assert line in rendered, f"compact orientation missing block line: {line!r}"


def test_render_full_injects_main_agent_block(repo_root: Path, spec: dict) -> None:
    rendered = render_full(repo_root, spec)
    assert "main_agent" in rendered
    for line in render_main_agent_block_full().splitlines():
        if line.strip():
            assert line in rendered, f"full orientation missing block line: {line!r}"


def test_append_helpers_always_contribute_the_block() -> None:
    """The block no longer depends on a packet render, so it cannot be empty.

    It used to be skipped whenever the packet generator was unavailable,
    which meant a fresh checkout got no orientation at all. The block is now
    built from constants plus machine-local advisories, so the only thing a
    broken generator costs is the packet the block points at.
    """

    import yoke_core.domain.main_agent_packet as bp

    lines: list = []
    bp.append_main_agent_compact(lines)
    assert any(render_main_agent_block() in part for part in lines)
    parts: list = []
    bp.append_main_agent_full(parts)
    assert any(render_main_agent_block_full() in part for part in parts)


def test_render_install_advisory_block_empty_when_yoke_on_path(
    monkeypatch,
) -> None:
    """When ``shutil.which("yoke")`` resolves, the advisory is empty so
    installed sessions see no noise."""

    import yoke_core.domain.main_agent_packet as bp

    monkeypatch.setattr(bp.shutil, "which", lambda _name: "/usr/local/bin/yoke")
    assert render_install_advisory_block() == ""


def test_render_install_advisory_block_three_lines_when_missing(
    monkeypatch,
) -> None:
    """When ``shutil.which("yoke")`` returns None, the advisory renders
    the canonical 3-line block: heading, indented install command, and
    docs pointer."""

    import yoke_core.domain.main_agent_packet as bp

    monkeypatch.setattr(bp.shutil, "which", lambda _name: None)
    block = render_install_advisory_block()
    lines = block.splitlines()
    assert lines == [
        INSTALL_ADVISORY_HEADING,
        "    " + install_command(),
        INSTALL_ADVISORY_POINTER,
    ]
    assert lines[1] == "    " + install_command()


def test_main_agent_block_prepends_advisory_when_yoke_missing(
    monkeypatch,
) -> None:
    """The compact ``main_agent`` block prepends the install advisory
    above the packet heading when ``yoke`` is not on PATH."""

    import yoke_core.domain.main_agent_packet as bp

    monkeypatch.setattr(bp.shutil, "which", lambda _name: None)
    block = render_main_agent_block()
    assert block.startswith(INSTALL_ADVISORY_HEADING), (
        "advisory must appear at the very top of the compact block"
    )
    assert install_command() in block
    assert INSTALL_ADVISORY_POINTER in block


def test_main_agent_block_omits_advisory_when_yoke_on_path(
    monkeypatch,
) -> None:
    """The compact ``main_agent`` block omits the install advisory when
    ``yoke`` resolves on PATH — installed sessions see only the packet
    heading and body."""

    import yoke_core.domain.main_agent_packet as bp

    monkeypatch.setattr(bp.shutil, "which", lambda _name: "/usr/local/bin/yoke")
    block = render_main_agent_block()
    assert INSTALL_ADVISORY_HEADING not in block
    assert install_command() not in block
    # Packet body still rendered.
    assert "main_agent" in block


def test_main_agent_block_full_prepends_advisory_when_yoke_missing(
    monkeypatch,
) -> None:
    """The full ``main_agent`` block prepends the install advisory above
    the ``=== ... ===`` heading when ``yoke`` is not on PATH."""

    import yoke_core.domain.main_agent_packet as bp

    monkeypatch.setattr(bp.shutil, "which", lambda _name: None)
    block = render_main_agent_block_full()
    assert block.startswith(INSTALL_ADVISORY_HEADING)
    assert install_command() in block
    # The packet heading still follows the advisory.
    assert "=== " in block


# Interpreter-advisory coverage. Probe behavior is
# covered by test_python_interpreter_probe; these tests verify wiring.

_PR = python_interpreter_probe.ProbeResult
_HEADING = python_interpreter_probe.ADVISORY_HEADING
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
    assert _HEADING not in render_main_agent_block()


def test_install_advisory_preserved_when_interpreter_fires(monkeypatch) -> None:
    """Both advisories may render; interpreter leads."""
    import yoke_core.domain.main_agent_packet as bp

    monkeypatch.setattr(python_interpreter_probe, "probe", lambda: _BAD)
    monkeypatch.setattr(bp.shutil, "which", lambda _name: None)
    block = render_main_agent_block()
    assert INSTALL_ADVISORY_HEADING in block
    assert install_command() in block
    assert INSTALL_ADVISORY_POINTER in block
    interp_idx = block.find(_HEADING)
    install_idx = block.find(INSTALL_ADVISORY_HEADING)
    assert 0 <= interp_idx < install_idx


def test_full_variant_includes_interpreter_advisory(monkeypatch) -> None:
    monkeypatch.setattr(python_interpreter_probe, "probe", lambda: _BAD)
    block = render_main_agent_block_full()
    assert 0 <= block.find(_HEADING) < block.find("=== ")


def test_advisory_fail_open_on_probe_exception(monkeypatch) -> None:
    def _boom():
        raise RuntimeError("wedged")

    monkeypatch.setattr(python_interpreter_probe, "probe", _boom)
    assert render_interpreter_advisory_block() == ""
