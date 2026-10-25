"""Read JSON probe inputs for release-pin agreement."""

from __future__ import annotations

import json
from typing import Any, Mapping
from urllib.request import Request, urlopen


def fetch_probe_json(url: str) -> Mapping[str, Any]:
    """Read the configured health probe without adding transport policy."""
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=15) as response:
        body = response.read().decode("utf-8")
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError(f"health probe at {url!r} did not return a JSON object")
    return payload
