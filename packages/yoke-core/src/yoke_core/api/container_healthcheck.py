"""Container healthcheck for the Yoke API service."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Mapping, Optional


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PATH = "/v1/health"
DEFAULT_PORT = 8765
DEFAULT_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True)
class HealthcheckSettings:
    host: str
    path: str
    port: int
    timeout_seconds: float


def _parse_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise ValueError(f"YOKE_API_PORT must be an integer, got {value!r}") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"YOKE_API_PORT must be between 1 and 65535, got {value!r}")
    return port


def _parse_timeout(value: str) -> float:
    try:
        timeout = float(value)
    except ValueError as exc:
        raise ValueError(
            f"YOKE_API_HEALTH_TIMEOUT must be numeric, got {value!r}"
        ) from exc
    if timeout <= 0:
        raise ValueError(
            f"YOKE_API_HEALTH_TIMEOUT must be positive, got {value!r}"
        )
    return timeout


def resolve_settings(env: Optional[Mapping[str, str]] = None) -> HealthcheckSettings:
    source = os.environ if env is None else env
    return HealthcheckSettings(
        host=source.get("YOKE_API_HEALTH_HOST", DEFAULT_HOST),
        path=source.get("YOKE_API_HEALTH_PATH", DEFAULT_PATH),
        port=_parse_port(source.get("YOKE_API_PORT", str(DEFAULT_PORT))),
        timeout_seconds=_parse_timeout(
            source.get("YOKE_API_HEALTH_TIMEOUT", str(DEFAULT_TIMEOUT_SECONDS))
        ),
    )


def build_url(settings: HealthcheckSettings) -> str:
    path = settings.path if settings.path.startswith("/") else f"/{settings.path}"
    return f"http://{settings.host}:{settings.port}{path}"


def check_health(
    settings: HealthcheckSettings,
    opener: Callable[..., object] = urllib.request.urlopen,
) -> str:
    url = build_url(settings)
    with opener(url, timeout=settings.timeout_seconds) as response:
        status_code = getattr(response, "status", None)
        if status_code != 200:
            raise RuntimeError(f"health endpoint returned HTTP {status_code}")
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("status") != "ok":
        raise RuntimeError(f"health endpoint returned status {payload.get('status')!r}")
    if payload.get("schema_ready") is not True:
        missing = payload.get("schema_missing_tables")
        detail = (
            f" missing_tables={missing!r}"
            if isinstance(missing, list) and missing
            else ""
        )
        raise RuntimeError(
            "health endpoint did not report schema_ready=true" + detail
        )
    return url


def main() -> int:
    try:
        url = check_health(resolve_settings())
    except (
        OSError,
        RuntimeError,
        ValueError,
        json.JSONDecodeError,
        urllib.error.URLError,
    ) as exc:
        print(f"Yoke API healthcheck failed: {exc}", file=sys.stderr)
        return 1
    print(f"Yoke API healthcheck OK: {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
