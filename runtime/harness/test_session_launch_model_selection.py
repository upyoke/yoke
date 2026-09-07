"""Per-harness launch selection validation and native encoding."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_contracts.session_control.launch_bootstrap import native_launch_bootstrap
from yoke_contracts.session_control.model_selection import (
    LaunchModelSelection,
    LaunchModelSelectionError,
    native_model_selector,
    parse_context_window_tokens,
    validate_launch_model_selection,
)
from yoke_contracts.session_control.native_model_parsers import parse_cursor_models
from yoke_contracts.session_control.observed_model_selection import (
    resolve_observed_model_selection,
)
from yoke_harness.session_relay_claude_native import native_invocation
from yoke_harness.session_relay_codex import CodexNativeRequest
from yoke_harness.session_relay_codex_invocation import codex_base_command
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

    command = codex_base_command("/opt/codex", request)

    assert command[-4:] == [
        "--model",
        "gpt-5.6-sol",
        "-c",
        "model_reasoning_effort=xhigh",
    ]


def test_cursor_keeps_the_advertised_selector_without_duplicate_effort() -> None:
    selector = cursor_model_selector(
        _context(
            "cursor-cli",
            requested_model="cursor-grok-4.6-high",
            requested_reasoning_effort="high",
        )
    )

    assert selector == "cursor-grok-4.6-high"


def test_cursor_availability_comes_from_native_list_models() -> None:
    models = parse_cursor_models(
        "Available models\n\n"
        "claude-opus-4-8-high - Opus 4.8 high\ncomposer-2 - Composer 2\n"
    )

    assert [entry["model"] for entry in models] == [
        "claude-opus-4-8-high",
        "composer-2",
    ]
    assert models[0]["reasoning_efforts"] == ["high"]
    # Cursor publishes no effort suffix for this token, and an absent field is
    # how the record says the vendor did not name one.
    assert "reasoning_efforts" not in models[1]


def test_launch_model_refuses_embedded_provider_parameters() -> None:
    with pytest.raises(LaunchModelSelectionError) as raised:
        native_model_selector(
            "cursor-cli",
            LaunchModelSelection("composer-2[effort=high]", None, None),
        )
    assert raised.value.code == "cursor_model_invalid"


def _reading(status="ok"):
    return {
        "status": status,
        "models": parse_cursor_models(
            "cursor-grok-4.6-high - Cursor Grok 4.6\n"
            "cursor-grok-4.6-medium - Cursor Grok 4.6 Medium\n"
            "cursor-grok-4.6-high-fast - Cursor Grok 4.6 Fast\n"
            "claude-opus-4-8-high - Claude Opus 4.8 1M\n"
            "claude-4.6-opus-high-thinking - Claude Opus 4.6 1M Thinking\n"
            "composer-2.5 - Composer 2.5\n"
        ),
    }


@pytest.mark.parametrize("status", ["ok", "stale"])
@pytest.mark.parametrize(
    ("model", "effort", "expected"),
    [
        ("cursor-grok-4.6-high", None, "cursor-grok-4.6-high"),
        ("cursor-grok-4.6-high", "high", "cursor-grok-4.6-high"),
        ("cursor-grok-4.6", "medium", "cursor-grok-4.6-medium"),
        ("cursor-grok-4.6-fast", "high", "cursor-grok-4.6-high-fast"),
        ("claude-4.6-opus-thinking", "high", "claude-4.6-opus-high-thinking"),
        ("claude-4.6-opus-high-thinking", "high", "claude-4.6-opus-high-thinking"),
    ],
)
def test_cursor_resolves_only_observed_native_variants(status, model, effort, expected):
    selected = resolve_observed_model_selection(
        "cursor-cli", LaunchModelSelection(model, effort), _reading(status)
    )
    assert selected.model == expected
    assert native_model_selector("cursor-cli", selected) == expected
    assert selected.context_window_tokens is None


@pytest.mark.parametrize(
    ("model", "effort", "context", "code"),
    [
        ("cursor-grok-4.6-high", "medium", None, "cursor_reasoning_effort_conflict"),
        ("cursor-grok-4.6-high-fast", "low", None, "cursor_reasoning_effort_conflict"),
        ("cursor-grok-4.6-high-high", "high", None, "cursor_model_unsupported"),
        ("cursor-grok-4.6", "max", None, "cursor_model_unsupported"),
        ("cursor-grok-4.6", None, None, "cursor_model_unsupported"),
        ("composer-2.5", "high", None, "cursor_model_unsupported"),
        (
            "cursor-grok-4.6-high",
            "high",
            1_000_000,
            "cursor_context_window_unsupported",
        ),
        ("claude-opus-4-8-high", "high", 200_000, "cursor_context_window_unsupported"),
    ],
)
def test_cursor_refuses_unadvertised_combinations(model, effort, context, code):
    with pytest.raises(LaunchModelSelectionError) as raised:
        resolve_observed_model_selection(
            "cursor-cli", LaunchModelSelection(model, effort, context), _reading()
        )
    assert raised.value.code == code


def test_cursor_selects_a_native_variant_with_an_explicitly_advertised_window():
    selected = resolve_observed_model_selection(
        "cursor-cli",
        LaunchModelSelection("claude-opus-4-8", "high", 1_000_000),
        _reading(),
    )
    assert native_model_selector("cursor-cli", selected) == "claude-opus-4-8-high"
    assert selected.context_window_tokens == 1_000_000


def test_cursor_unknown_availability_does_not_invent_parameter_support():
    with pytest.raises(LaunchModelSelectionError) as raised:
        resolve_observed_model_selection(
            "cursor-cli", LaunchModelSelection("cursor-grok-4.6", "high"), None
        )
    assert raised.value.code == "cursor_model_availability_unknown"


def test_codex_uses_the_models_own_efforts_without_rewriting_its_selector():
    reading = {
        "status": "ok",
        "models": [{"model": "gpt-5.6-sol", "reasoning_efforts": ["high"]}],
    }
    selected = LaunchModelSelection("gpt-5.6-sol", "high")
    assert resolve_observed_model_selection("codex-cli", selected, reading) == selected
    with pytest.raises(LaunchModelSelectionError) as raised:
        resolve_observed_model_selection(
            "codex-cli", LaunchModelSelection("gpt-5.6-sol", "ultra"), reading
        )
    assert raised.value.code == "codex_reasoning_effort_unsupported"
