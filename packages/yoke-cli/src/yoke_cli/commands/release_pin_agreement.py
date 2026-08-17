"""Compare a project's configured desired pin to a configured JSON probe."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class PinHealthAgreement:
    """Outcome of comparing the desired pin to a health probe."""

    agreed: bool
    desired_pin: Optional[str] = None
    served_pin: Optional[str] = None
    probe_url: Optional[str] = None
    error: Optional[str] = None


def environment_by_target_map(settings: Mapping[str, Any]) -> dict[str, str]:
    """Return the capability's target→environment-id map, dropping empties."""
    mapping = settings.get("environment_by_target") or {}
    if not isinstance(mapping, dict):
        return {}
    cleaned: dict[str, str] = {}
    for raw_target, raw_environment_id in mapping.items():
        target = str(raw_target or "").strip()
        environment_id = str(raw_environment_id or "").strip()
        if target and environment_id:
            cleaned[target] = environment_id
    return cleaned


def _environment_name_to_id(
    environments: Mapping[str, str] | Sequence[Mapping[str, Any]] | None,
) -> dict[str, str]:
    if environments is None:
        return {}
    if isinstance(environments, Mapping):
        return {
            str(name).strip(): str(environment_id).strip()
            for name, environment_id in environments.items()
            if str(name or "").strip() and str(environment_id or "").strip()
        }
    name_to_id: dict[str, str] = {}
    for row in environments:
        if not isinstance(row, Mapping):
            continue
        name = str(row.get("name") or "").strip()
        environment_id = str(row.get("id") or "").strip()
        if name and environment_id:
            name_to_id[name] = environment_id
    return name_to_id


def environment_id_for_target(
    settings: Mapping[str, Any],
    environment_name: str,
    *,
    environments: Mapping[str, str] | Sequence[Mapping[str, Any]] | None = None,
) -> Optional[str]:
    """Resolve a control-plane environment id from a deploy-target token.

    Accepts, in order: a key in ``environment_by_target``, a mapped environment
    id value, or (when ``environments`` is provided) the environment's own
    ``name`` for a mapped id.
    """
    needle = str(environment_name or "").strip()
    if not needle:
        return None
    mapping = environment_by_target_map(settings)
    if not mapping:
        return None
    if needle in mapping:
        return mapping[needle]
    mapped_ids = set(mapping.values())
    if needle in mapped_ids:
        return needle
    candidate = _environment_name_to_id(environments).get(needle)
    if candidate and candidate in mapped_ids:
        return candidate
    return None


def accepted_environment_targets(
    settings: Mapping[str, Any],
    *,
    environments: Mapping[str, str] | Sequence[Mapping[str, Any]] | None = None,
) -> list[str]:
    """Sorted tokens ``--environment`` may accept for the configured map."""
    mapping = environment_by_target_map(settings)
    accepted: set[str] = set(mapping.keys()) | set(mapping.values())
    mapped_ids = set(mapping.values())
    for name, environment_id in _environment_name_to_id(environments).items():
        if environment_id in mapped_ids:
            accepted.add(name)
    return sorted(accepted)


def format_accepted_environment_targets(targets: Iterable[str]) -> str:
    """Render accepted tokens for a USAGE error, or ``(none)`` when empty."""
    ordered = [str(token).strip() for token in targets if str(token).strip()]
    return ", ".join(ordered) if ordered else "(none)"


def fetch_served_pin(
    probe_url: str,
    response_path: str,
    *,
    opener: Callable[[str], Mapping[str, Any]] | None = None,
) -> str:
    """Return the configured scalar from a JSON probe response."""
    payload = (opener or _get_json)(probe_url)
    if not isinstance(payload, Mapping):
        raise ValueError(f"health probe at {probe_url!r} did not return a JSON object")
    value = _response_value(payload, response_path)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"health probe at {probe_url!r} has no non-empty string at "
            f"{response_path!r}"
        )
    return value.strip()


def evaluate_pin_health_agreement(
    *,
    desired_pin: Optional[str],
    probe_url: Optional[str],
    desired_path: str,
    probe_url_path: str,
    served_pin_response_path: str,
    opener: Callable[[str], Mapping[str, Any]] | None = None,
) -> PinHealthAgreement:
    """Compare the desired pin to the probe's configured served-pin leaf."""
    if not desired_pin:
        return PinHealthAgreement(
            agreed=False,
            desired_pin=desired_pin,
            probe_url=probe_url,
            error=f"{desired_path} is unset",
        )
    if not probe_url:
        return PinHealthAgreement(
            agreed=False,
            desired_pin=desired_pin,
            probe_url=probe_url,
            error=f"{probe_url_path} is unset",
        )
    try:
        served = fetch_served_pin(
            probe_url,
            served_pin_response_path,
            opener=opener,
        )
    except (OSError, ValueError, HTTPError, URLError) as exc:
        return PinHealthAgreement(
            agreed=False,
            desired_pin=desired_pin,
            probe_url=probe_url,
            error=str(exc),
        )
    return PinHealthAgreement(
        agreed=served == desired_pin,
        desired_pin=desired_pin,
        served_pin=served,
        probe_url=probe_url,
    )


def _response_value(payload: Mapping[str, Any], path: str) -> Any:
    parts = path.split(".")
    if not path or any(not part for part in parts):
        raise ValueError(f"invalid served-pin response path {path!r}")
    value: Any = payload
    for part in parts:
        if isinstance(value, Mapping):
            if part not in value:
                return None
            value = value[part]
            continue
        if isinstance(value, list) and part.isdigit():
            index = int(part)
            if index >= len(value):
                return None
            value = value[index]
            continue
        return None
    return value


def _get_json(url: str) -> Mapping[str, Any]:
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=15) as response:
        body = response.read().decode("utf-8")
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError(f"health probe at {url!r} did not return a JSON object")
    return payload


__all__ = [
    "PinHealthAgreement",
    "accepted_environment_targets",
    "environment_by_target_map",
    "environment_id_for_target",
    "evaluate_pin_health_agreement",
    "fetch_served_pin",
    "format_accepted_environment_targets",
]
