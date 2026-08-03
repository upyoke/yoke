"""Fail closed when a QA case mixes execution environments."""

from __future__ import annotations

import re
from typing import Any, Mapping


_ENV_CHANNEL = re.compile(r"\bYOKE_CHANNEL=([A-Za-z0-9][A-Za-z0-9._-]{0,63})\b")


def _walk(value: Any, *, path: str = "$"):
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield from _walk(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, path=f"{path}[{index}]")
    else:
        yield path, value


def _mapping_nodes(value: Any, *, path: str = "$"):
    if isinstance(value, Mapping):
        yield path, value
        for key, child in value.items():
            yield from _mapping_nodes(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _mapping_nodes(child, path=f"{path}[{index}]")


def require_case_environment_bindings(
    case: Mapping[str, Any],
    *,
    target: Mapping[str, Any],
) -> None:
    """Reject channel or interactive-target bindings outside *target*."""
    environment = target["environment"]
    endpoints = target["endpoints"]
    expected_environment_id = str(environment.get("id") or "").strip()
    expected_base_url = str(endpoints.get("installer_base_url") or "").rstrip("/")
    expected_channel = str(endpoints.get("release_channel") or "").strip()
    for path, node in _mapping_nodes(case):
        if node.get("step") != "destination-picker":
            if node.get("id") == "installer.current-release-prepare":
                parameters = node.get("parameters")
                parameters = parameters if isinstance(parameters, Mapping) else {}
                declared_base_url = str(parameters.get("base_url") or "").rstrip("/")
                declared_channel = str(parameters.get("channel") or "").strip()
                if declared_base_url != expected_base_url:
                    raise ValueError(
                        f"mixed-environment QA installer endpoint at {path}: "
                        f"{declared_base_url or 'missing'!r}"
                    )
                if declared_channel != expected_channel:
                    raise ValueError(
                        f"mixed-environment QA release channel at {path}: "
                        f"{declared_channel or 'missing'!r}"
                    )
            continue
        declared = str(node.get("target_environment_id") or "").strip()
        if not expected_environment_id:
            raise ValueError("QA execution target has no environment id")
        if declared != expected_environment_id:
            raise ValueError(
                f"mixed-environment QA destination binding at {path}: "
                f"{declared or 'missing'!r}"
            )
    for path, value in _walk(case):
        key = path.rsplit(".", 1)[-1]
        declared = value if key == "channel" and isinstance(value, str) else None
        if declared is None and isinstance(value, str):
            match = _ENV_CHANNEL.search(value)
            declared = match.group(1) if match is not None else None
        if declared is not None and expected_channel and declared != expected_channel:
            raise ValueError(
                f"mixed-environment QA release channel at {path}: {declared!r}"
            )
        if (
            key == "target_environment_id"
            and str(value).strip() != expected_environment_id
        ):
            raise ValueError(
                f"mixed-environment QA target binding at {path}: {value!r}"
            )


__all__ = ["require_case_environment_bindings"]
