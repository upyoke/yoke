"""Compare a project's configured desired pin to a configured JSON probe."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional
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
    "evaluate_pin_health_agreement",
    "fetch_served_pin",
]
