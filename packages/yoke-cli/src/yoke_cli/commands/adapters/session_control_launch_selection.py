"""Build and validate the selection a launch preview or create sends."""

from __future__ import annotations

import argparse
from typing import Any, List

from yoke_cli.commands._helpers import add_json_arg, usage_error
from yoke_contracts.session_control.launch_requests import LaunchPreviewRequest
from yoke_contracts.session_control.model_selection import (
    LaunchModelSelection,
    LaunchModelSelectionError,
    validate_launch_model_selection,
)


_EXPLICIT_FLAGS = (
    ("executor_surface", "--surface"),
    ("model", "--model"),
    ("reasoning_effort", "--reasoning-effort"),
    ("context_window_tokens", "--context-window"),
    ("allow_surface_fallback", "--allow-surface-fallback"),
)


def _level_payload(parsed: argparse.Namespace) -> dict[str, Any] | None:
    named = [flag for attr, flag in _EXPLICIT_FLAGS if getattr(parsed, attr, None)]
    if named:
        usage_error(
            "level_selection_conflict: --level chooses the surface, model, effort, "
            f"and context itself; drop {', '.join(named)} to launch by level, or "
            "drop --level to launch that exact selection"
        )
        return None
    payload: dict[str, Any] = {"project": parsed.project, "level": parsed.level}
    machine_id = getattr(parsed, "machine_id", None)
    if machine_id:
        payload["machine_id"] = machine_id
    # Checked against this build's own request model first, so a payload
    # refusal from the server can only mean it predates the argument.
    try:
        LaunchPreviewRequest.model_validate(payload)
    except ValueError as exc:
        usage_error(f"level_invalid: {exc}")
        return None
    return payload


def _explicit_payload(parsed: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "project": parsed.project,
        "executor_surface": parsed.executor_surface,
        "allow_surface_fallback": parsed.allow_surface_fallback,
    }
    machine_id = getattr(parsed, "machine_id", None)
    if machine_id:
        payload["machine_id"] = machine_id
    model = str(getattr(parsed, "model", None) or "").strip()
    if model:
        payload["model"] = model
    effort = str(getattr(parsed, "reasoning_effort", None) or "").strip().lower()
    if effort:
        payload["reasoning_effort"] = effort
    context = getattr(parsed, "context_window_tokens", None)
    if context is not None:
        payload["context_window_tokens"] = context
    return payload


def selector_payload(
    parsed: argparse.Namespace, *, stage_default: bool = False
) -> dict[str, Any] | None:
    """Send a level, or only the explicit values a named surface accepts."""
    if getattr(parsed, "level", None):
        return _level_payload(parsed)
    if not parsed.executor_surface:
        if stage_default:
            named = [
                flag for attr, flag in _EXPLICIT_FLAGS if getattr(parsed, attr, None)
            ]
            if named:
                usage_error(
                    f"launch_selection_missing: {', '.join(named)} needs --surface S; omit selection flags to use the item stage level"
                )
                return None
            payload = {"project": parsed.project, "use_stage_level": True}
            if parsed.machine_id:
                payload["machine_id"] = parsed.machine_id
            return payload
        usage_error(
            "launch_selection_missing: name --item PREFIX-N to preview its stage "
            "level route, --level LEVEL for Yoke to place a level, or --surface S "
            "to preview an exact selection"
        )
        return None
    try:
        payload = _explicit_payload(parsed)
        validate_launch_model_selection(
            parsed.executor_surface,
            LaunchModelSelection(
                model=payload.get("model"),
                reasoning_effort=payload.get("reasoning_effort"),
                context_window_tokens=payload.get("context_window_tokens"),
            ),
        )
        return payload
    except LaunchModelSelectionError as exc:
        usage_error(f"{exc.code}: {exc}")
        return None


def preview_payload(parsed: argparse.Namespace) -> dict[str, Any] | None:
    """A preview's selection; an item alone previews its stage level."""
    payload = selector_payload(parsed, stage_default=bool(parsed.item))
    if payload is None:
        return None
    # ``item`` carries the preview's own serving floor; the stage marker is a
    # create argument.
    payload.pop("use_stage_level", None)
    if parsed.item:
        payload["item"] = parsed.item
    return payload


def add_item_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--item",
        default=None,
        metavar="PREFIX-N",
        help="Work item the session works on, as PREFIX-N. Without selection "
        "flags its effective workflow stage level decides the route.",
    )


def add_launch_selector(parser: argparse.ArgumentParser) -> None:
    from yoke_contracts.session_control.model_selection import (
        parse_context_window_tokens,
    )

    parser.add_argument(
        "--project", required=True, metavar="P", help="Project to launch in."
    )
    parser.add_argument(
        "--level",
        default=None,
        help="Override: launch at this level instead of the item's effective "
        "stage level (`yoke settings get levels`); Yoke still chooses the option "
        "and machine. An item-bound create also records it as the item's level "
        "for every stage (explain with --level-reason); a preview or itemless "
        "create places one launch only.",
    )
    parser.add_argument(
        "--surface",
        default=None,
        dest="executor_surface",
        metavar="SURFACE",
        help="Override: use this surface. With --item and no --model, choose "
        "an option at the item stage level on this surface; omit effort/context "
        "knobs in that form. With --model, launch that exact selection.",
    )
    parser.add_argument(
        "--machine",
        default=None,
        dest="machine_id",
        metavar="MACHINE_ID",
        help="Override: place on this registered Machine id (`yoke machine "
        "list`); a name resolves only when one live Machine carries it. A test "
        "machine is not a Machine: it is reached through its QA lease.",
    )
    parser.add_argument(
        "--model", default=None, metavar="MODEL", help="Model; needs --surface."
    )
    parser.add_argument(
        "--reasoning-effort",
        default=None,
        metavar="EFFORT",
        help="Reasoning effort; needs --surface.",
    )
    parser.add_argument(
        "--context-window",
        dest="context_window_tokens",
        type=parse_context_window_tokens,
        default=None,
        metavar="TOKENS",
        help="Context window size in tokens; needs --surface.",
    )
    parser.add_argument(
        "--allow-surface-fallback",
        action="store_true",
        help="Use another surface when no relay serves the named one.",
    )
    # maybe_list_models answers --list-models before this parser runs; it is
    # declared here so the help page lists it.
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="Print the models each surface offers (with --surface, that "
        "surface only) and exit without launching.",
    )


def maybe_list_models(args: List[str]) -> int | None:
    if "--list-models" not in args:
        return None
    from yoke_contracts.session_control.launch_model_listing import (
        list_launch_models,
        render_launch_models,
    )

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--surface",
        dest="executor_surface",
        default=None,
        help="List models for this surface only.",
    )
    add_json_arg(parser)
    parsed, _unknown = parser.parse_known_args(args)
    from yoke_harness.session_relay_native_models import observe_native_models

    report = list_launch_models(
        parsed.executor_surface, availability=observe_native_models()
    )
    print(render_launch_models(report, json_mode=parsed.json_mode), end="")
    return 0


__all__ = [
    "add_item_arg",
    "add_launch_selector",
    "maybe_list_models",
    "preview_payload",
    "selector_payload",
]
