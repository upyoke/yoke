"""Shared keys for the project-owned release-pin capability contract."""

from __future__ import annotations


RELEASE_PIN_CAPABILITY = "release_pin"
DESIRED_PIN_PATH_KEY = "desired_pin_path"
ENVIRONMENT_BY_TARGET_KEY = "environment_by_target"
PROBE_URL_PATH_KEY = "probe_url_path"
SERVED_PIN_RESPONSE_PATH_KEY = "served_pin_response_path"


__all__ = [
    "DESIRED_PIN_PATH_KEY",
    "ENVIRONMENT_BY_TARGET_KEY",
    "PROBE_URL_PATH_KEY",
    "RELEASE_PIN_CAPABILITY",
    "SERVED_PIN_RESPONSE_PATH_KEY",
]
