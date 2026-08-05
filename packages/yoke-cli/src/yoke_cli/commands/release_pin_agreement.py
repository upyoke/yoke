"""Compare a project's desired release pin to a live health probe.

Desired pin authority is the control-plane leaf
``environments.settings.release.yoke_pin``. The committed pin file on an
environment branch is build materialization only. A probe URL at
``release.health_probe_url`` reports the engine version the environment is
actually serving; disagreement is detectable without deploying.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DESIRED_PIN_SETTINGS_PATH = "release.yoke_pin"
HEALTH_PROBE_SETTINGS_PATH = "release.health_probe_url"


@dataclass(frozen=True)
class PinHealthAgreement:
    """Outcome of comparing the desired pin to a health probe."""

    agreed: bool
    desired_pin: Optional[str] = None
    served_engine_version: Optional[str] = None
    probe_url: Optional[str] = None
    skipped_reason: Optional[str] = None
    error: Optional[str] = None


def environment_id_for_target(settings: Mapping[str, Any], target_env: str) -> Optional[str]:
    """Resolve the control-plane environment id for a deploy target name."""
    mapping = settings.get("environment_by_target") or {}
    if not isinstance(mapping, dict):
        return None
    value = mapping.get(target_env)
    return str(value) if value else None


def fetch_health_engine_version(
    probe_url: str,
    *,
    opener: Callable[[str], Mapping[str, Any]] | None = None,
) -> str:
    """Return ``engine_version`` from a Yoke ``/v1/health`` JSON body."""
    payload = (opener or _get_json)(probe_url)
    version = payload.get("engine_version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError(
            f"health probe at {probe_url!r} has no engine_version field"
        )
    return version.strip()


def evaluate_pin_health_agreement(
    *,
    desired_pin: Optional[str],
    probe_url: Optional[str],
    desired_path: str = DESIRED_PIN_SETTINGS_PATH,
    opener: Callable[[str], Mapping[str, Any]] | None = None,
) -> PinHealthAgreement:
    """Compare desired pin to the probe's served engine version."""
    if not desired_pin:
        return PinHealthAgreement(
            agreed=False,
            desired_pin=desired_pin,
            probe_url=probe_url,
            skipped_reason=f"{desired_path} is unset",
        )
    if not probe_url:
        return PinHealthAgreement(
            agreed=False,
            desired_pin=desired_pin,
            probe_url=probe_url,
            skipped_reason=f"{HEALTH_PROBE_SETTINGS_PATH} is unset",
        )
    try:
        served = fetch_health_engine_version(probe_url, opener=opener)
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
        served_engine_version=served,
        probe_url=probe_url,
    )


def _get_json(url: str) -> Mapping[str, Any]:
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=15) as response:
        body = response.read().decode("utf-8")
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError(f"health probe at {url!r} did not return a JSON object")
    return payload


__all__ = [
    "DESIRED_PIN_SETTINGS_PATH",
    "HEALTH_PROBE_SETTINGS_PATH",
    "PinHealthAgreement",
    "environment_id_for_target",
    "evaluate_pin_health_agreement",
    "fetch_health_engine_version",
]
