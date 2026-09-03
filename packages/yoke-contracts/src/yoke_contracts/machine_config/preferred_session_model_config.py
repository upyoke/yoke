"""Storage-compatible model selectors and additive reasoning defaults."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.session_control.model_selection import (
    LaunchModelSelection,
    LaunchModelSelectionError,
    validate_launch_model_selection,
)
from yoke_contracts.session_model_facts import (
    CLAUDE_CONTEXT_TIER_SUFFIX,
    CLAUDE_CONTEXT_TIER_TOKENS,
)


PREFERRED_SESSION_MODELS_KEY = "preferred_session_models"
PREFERRED_SESSION_REASONING_EFFORTS_KEY = "preferred_session_reasoning_efforts"


def _string_map(payload: Mapping[str, Any] | None, key: str) -> dict[str, str]:
    raw = (payload or {}).get(key)
    if not isinstance(raw, Mapping):
        return {}
    return {
        str(surface).strip(): value.strip()
        for surface, value in raw.items()
        if str(surface).strip() and isinstance(value, str)
    }


def preferred_session_models(
    payload: Mapping[str, Any] | None,
) -> dict[str, str]:
    """Return the scalar selector map accepted by the previous release."""
    return _string_map(payload, PREFERRED_SESSION_MODELS_KEY)


def preferred_session_reasoning_efforts(
    payload: Mapping[str, Any] | None,
) -> dict[str, str]:
    """Return explicit per-surface effort defaults from the additive map."""
    return {
        surface: effort.lower()
        for surface, effort in _string_map(
            payload, PREFERRED_SESSION_REASONING_EFFORTS_KEY
        ).items()
    }


def launchable_preferred_surfaces() -> tuple[str, ...]:
    from yoke_contracts.session_control.capabilities import (
        SESSION_SURFACE_CAPABILITIES,
    )

    return tuple(
        sorted(
            surface
            for surface, capability in SESSION_SURFACE_CAPABILITIES.items()
            if capability.create == "supported"
        )
    )


def blank_preferred_session_models() -> dict[str, str]:
    return {surface: "" for surface in launchable_preferred_surfaces()}


def blank_preferred_session_reasoning_efforts() -> dict[str, str]:
    return {surface: "" for surface in launchable_preferred_surfaces()}


def seed_preferred_session_models(payload: dict[str, Any]) -> bool:
    changed = False
    if PREFERRED_SESSION_MODELS_KEY not in payload:
        payload[PREFERRED_SESSION_MODELS_KEY] = blank_preferred_session_models()
        changed = True
    if PREFERRED_SESSION_REASONING_EFFORTS_KEY not in payload:
        payload[PREFERRED_SESSION_REASONING_EFFORTS_KEY] = (
            blank_preferred_session_reasoning_efforts()
        )
        changed = True
    return changed


def _selection_error(surface: str, detail: str) -> LaunchModelSelectionError:
    prefix = surface.replace("-cli", "").replace("-", "_")
    return LaunchModelSelectionError(
        f"{prefix}_model_invalid",
        f"{surface} preferred model selector {detail}",
    )


def _decode_model_selector(surface: str, value: str) -> LaunchModelSelection:
    selector = str(value or "").strip()
    if not selector:
        return LaunchModelSelection()
    if surface == "claude-cli":
        if selector.endswith(CLAUDE_CONTEXT_TIER_SUFFIX):
            base = selector.removesuffix(CLAUDE_CONTEXT_TIER_SUFFIX)
            if not base or "[" in base or "]" in base:
                raise _selection_error(surface, "has an invalid 1m suffix")
            return LaunchModelSelection(
                model=base,
                context_window_tokens=CLAUDE_CONTEXT_TIER_TOKENS,
            )
        if "[" in selector or "]" in selector:
            raise _selection_error(surface, "supports only the [1m] suffix")
        return LaunchModelSelection(model=selector)
    if surface != "cursor-cli" or "[" not in selector:
        return LaunchModelSelection(model=selector)
    if not selector.endswith("]") or selector.count("[") != 1:
        raise _selection_error(surface, "has malformed bracket parameters")
    model, encoded = selector[:-1].split("[", 1)
    if not model:
        raise _selection_error(surface, "is missing its model")
    parameters: dict[str, str] = {}
    for raw_parameter in encoded.split(","):
        key, separator, raw_value = raw_parameter.partition("=")
        key = key.strip().lower()
        parameter = raw_value.strip().lower()
        if not separator or not key or key in parameters:
            raise _selection_error(surface, "has malformed bracket parameters")
        parameters[key] = parameter
    unknown = set(parameters) - {"context", "effort", "fast"}
    if unknown:
        raise _selection_error(
            surface, f"has unsupported parameters: {', '.join(sorted(unknown))}"
        )
    if parameters.get("fast", "false") != "false":
        raise _selection_error(surface, "cannot configure fast mode")
    context = parameters.get("context")
    if context not in (None, "1m"):
        raise _selection_error(surface, f"has unsupported context {context!r}")
    return LaunchModelSelection(
        model=model,
        reasoning_effort=parameters.get("effort") or None,
        context_window_tokens=CLAUDE_CONTEXT_TIER_TOKENS if context else None,
    )


def configured_preferred_selection(
    payload: Mapping[str, Any] | None,
    surface: str,
) -> tuple[LaunchModelSelection, dict[str, str]]:
    selector = preferred_session_models(payload).get(surface, "")
    selection = _decode_model_selector(surface, selector)
    configured_effort = preferred_session_reasoning_efforts(payload).get(surface, "")
    if (
        configured_effort
        and selection.reasoning_effort
        and configured_effort != selection.reasoning_effort
    ):
        raise LaunchModelSelectionError(
            "cursor_reasoning_effort_conflict",
            f"{surface} selector effort {selection.reasoning_effort!r} conflicts "
            f"with {PREFERRED_SESSION_REASONING_EFFORTS_KEY} value "
            f"{configured_effort!r}",
        )
    effort = configured_effort or selection.reasoning_effort
    sources: dict[str, str] = {}
    if selection.model:
        sources["model"] = f"{PREFERRED_SESSION_MODELS_KEY}.{surface}"
    if selection.context_window_tokens is not None:
        sources["context_window_tokens"] = (
            f"{PREFERRED_SESSION_MODELS_KEY}.{surface}"
        )
    if effort:
        key = (
            PREFERRED_SESSION_REASONING_EFFORTS_KEY
            if configured_effort
            else PREFERRED_SESSION_MODELS_KEY
        )
        sources["reasoning_effort"] = f"{key}.{surface}"
    return LaunchModelSelection(
        selection.model,
        effort or None,
        selection.context_window_tokens,
    ), sources


def _validate_string_map(
    payload: Mapping[str, Any],
    key: str,
    *,
    allowed_surfaces: set[str] | None = None,
) -> list[Any]:
    from yoke_contracts.machine_config.schema_projects import _error

    raw = payload.get(key)
    if raw is None:
        return []
    if not isinstance(raw, Mapping):
        return [_error(f"{key}_invalid", f"{key} must be an object", path=key)]
    issues = []
    for raw_surface, value in raw.items():
        surface = str(raw_surface).strip()
        path = f"{key}.{surface or '<blank>'}"
        if not surface:
            issues.append(
                _error(
                    f"{key}_surface_invalid",
                    f"{key} surfaces must be non-empty",
                    path=key,
                )
            )
        elif allowed_surfaces is not None and surface not in allowed_surfaces:
            issues.append(
                _error(
                    f"{key}_surface_invalid",
                    f"{surface} is not a launchable CLI surface",
                    path=path,
                )
            )
        elif not isinstance(value, str):
            code = (
                "preferred_session_models_model_invalid"
                if key == PREFERRED_SESSION_MODELS_KEY
                else f"{key}_value_invalid"
            )
            label = "model id" if key == PREFERRED_SESSION_MODELS_KEY else "value"
            issues.append(
                _error(
                    code,
                    f"{path} must be a string {label} (blank means unset)",
                    path=path,
                )
            )
    return issues


def validate_preferred_session_models(payload: Mapping[str, Any]) -> list[Any]:
    """Validate the previous-release model map plus additive effort defaults."""
    from yoke_contracts.machine_config.schema_projects import _error

    allowed = set(launchable_preferred_surfaces())
    issues = _validate_string_map(payload, PREFERRED_SESSION_MODELS_KEY)
    issues.extend(
        _validate_string_map(
            payload,
            PREFERRED_SESSION_REASONING_EFFORTS_KEY,
            allowed_surfaces=allowed,
        )
    )
    if issues:
        return issues
    for surface in allowed:
        try:
            selection, _sources = configured_preferred_selection(payload, surface)
            validate_launch_model_selection(surface, selection)
        except ValueError as exc:
            issues.append(
                _error(
                    getattr(exc, "code", "model_selection_invalid"),
                    str(exc),
                    path=f"{PREFERRED_SESSION_MODELS_KEY}.{surface}",
                )
            )
    return issues


__all__ = [
    "PREFERRED_SESSION_MODELS_KEY",
    "PREFERRED_SESSION_REASONING_EFFORTS_KEY",
    "blank_preferred_session_models",
    "blank_preferred_session_reasoning_efforts",
    "configured_preferred_selection",
    "launchable_preferred_surfaces",
    "preferred_session_models",
    "preferred_session_reasoning_efforts",
    "seed_preferred_session_models",
    "validate_preferred_session_models",
]
