"""Shared keys for the project-owned release-pin capability contract."""

from __future__ import annotations


RELEASE_PIN_CAPABILITY = "release_pin"
DESIRED_PIN_PATH_KEY = "desired_pin_path"
PROBE_URL_PATH_KEY = "probe_url_path"
SERVED_PIN_RESPONSE_PATH_KEY = "served_pin_response_path"
#: Repository path that holds the pinned release at a deployed commit.
CANDIDATE_PIN_FILE_KEY = "candidate_pin_file"


__all__ = [
    "CANDIDATE_PIN_FILE_KEY",
    "DESIRED_PIN_PATH_KEY",
    "PROBE_URL_PATH_KEY",
    "RELEASE_PIN_CAPABILITY",
    "SERVED_PIN_RESPONSE_PATH_KEY",
]
