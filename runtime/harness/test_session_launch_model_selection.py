"""Per-harness launch selection validation, catalogs, and native encoding."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from yoke_contracts.session_control.launch_bootstrap import native_launch_bootstrap
from yoke_contracts.session_control.model_selection import (
    LaunchModelSelection,
    LaunchModelSelectionError,
    model_catalog,
    native_model_selector,
    parse_context_window_tokens,
    parse_cursor_model_catalog,
    validate_launch_model_selection,
)
from yoke_harness.session_relay_claude_native import native_invocation
from yoke_harness.session_relay_codex import CodexNativeRequest
from yoke_harness.session_relay_codex_cli import _base_command
from yoke_harness.session_relay_cursor_requests import cursor_model_selector
from yoke_harness.session_relay_runtime import RelayExecutionContext


LAUNCH_ID = "11111111-1111-4111-8111-111111111111"
BOOTSTRAP = native_launch_bootstrap(LAUNCH_ID)


def _context(surface: str, **selection) -> RelayExecutionContext:
    return RelayExecutionContext(
        job_kind="launch",
        job_id=LAUNCH_ID,
        lease_id="lease-1",
        surface=surface,
        surface_version="current",
        project_id=1,
        checkout=Path("/project"),
        native_instruction=BOOTSTRAP,
        launch_attestation="secret",
        **selection,
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("1000000", 1_000_000), ("1000k", 1_000_000), ("1m", 1_000_000)],
)
def test_context_window_accepts_integer_and_compact_tokens(raw, expected) -> None:
    assert parse_context_window_tokens(raw) == expected


@pytest.mark.parametrize("raw", ["", "0", "-1", "1.5m", True])
def test_context_window_refuses_non_positive_or_ambiguous_tokens(raw) -> None:
    with pytest.raises(ValueError, match="context window"):
        parse_context_window_tokens(raw)


@pytest.mark.parametrize(
    ("surface", "selection", "code"),
    [
        (
            "claude-cli",
            LaunchModelSelection("claude-opus-4-8", "ultra", None),
            "claude_reasoning_effort_unsupported",
        ),
        (
            "codex-cli",
            LaunchModelSelection("gpt-5.6-sol", "high", 1_000_000),
            "codex_context_window_unsupported",
        ),
        (
            "cursor-cli",
            LaunchModelSelection(None, "high", None),
            "cursor_model_required_for_reasoning_effort",
        ),
    ],
)
def test_unsupported_knob_names_the_harness_and_knob(surface, selection, code) -> None:
    with pytest.raises(LaunchModelSelectionError) as raised:
        validate_launch_model_selection(surface, selection)
    assert raised.value.code == code


def test_claude_maps_model_effort_and_context_to_native_argv() -> None:
    invocation = native_invocation(
        _context(
            "claude-cli",
            requested_model="claude-opus-4-8",
            requested_reasoning_effort="max",
            requested_context_window_tokens=1_000_000,
        ),
        "/opt/claude",
        BOOTSTRAP,
    )

    assert invocation is not None
    assert ("--model", "claude-opus-4-8[1m]") in tuple(
        zip(invocation.argv, invocation.argv[1:])
    )
    assert ("--effort", "max") in tuple(zip(invocation.argv, invocation.argv[1:]))


def test_codex_maps_model_and_effort_to_argv_config() -> None:
    request = CodexNativeRequest(
        "launch",
        LAUNCH_ID,
        "codex-cli",
        "current",
        Path("/project"),
        "gpt-5.6-sol",
        None,
        None,
        None,
        None,
        f"launch:{LAUNCH_ID}",
        BOOTSTRAP,
        requested_reasoning_effort="xhigh",
    )

    command = _base_command("/opt/codex", request)

    assert command[-4:] == [
        "--model",
        "gpt-5.6-sol",
        "-c",
        "model_reasoning_effort=xhigh",
    ]


def test_cursor_maps_all_knobs_to_one_parameterized_model() -> None:
    selector = cursor_model_selector(
        _context(
            "cursor-cli",
            requested_model="claude-opus-4-8",
            requested_reasoning_effort="high",
            requested_context_window_tokens=1_000_000,
        )
    )

    assert selector == "claude-opus-4-8[context=1m,effort=high]"


def test_cursor_catalog_comes_from_native_list_models(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: "/opt/cursor-agent")
    completed = subprocess.CompletedProcess(
        ["cursor-agent", "--list-models"],
        0,
        "claude-opus-4-8-high - Opus 4.8 high\ncomposer-2 - Composer 2\n",
        "",
    )
    catalog = model_catalog("cursor-cli", runner=lambda _argv: completed)

    assert catalog == parse_cursor_model_catalog(completed.stdout)
    assert catalog.models == ("claude-opus-4-8-high", "composer-2")
    assert catalog.effort_levels == ("high",)


def test_launch_model_refuses_embedded_provider_parameters() -> None:
    with pytest.raises(LaunchModelSelectionError) as raised:
        native_model_selector(
            "cursor-cli",
            LaunchModelSelection("composer-2[effort=high]", None, None),
        )
    assert raised.value.code == "cursor_model_invalid"
