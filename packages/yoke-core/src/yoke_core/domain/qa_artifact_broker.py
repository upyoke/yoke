"""Hosted tenant client for the scoped QA-evidence signing broker."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from yoke_core.domain.qa_artifact_handle import (
    build_artifact_key,
    safe_storage_prefix,
)

BUCKET_ENV = "YOKE_QA_ARTIFACT_BUCKET"
PREFIX_ENV = "YOKE_QA_ARTIFACT_PREFIX"
BROKER_URL_ENV = "YOKE_QA_ARTIFACT_BROKER_URL"
TOKEN_FILE_ENV = "YOKE_QA_ARTIFACT_BROKER_TOKEN_FILE"
BROKER_RESPONSE_LIMIT = 64 * 1024


class ArtifactBrokerError(RuntimeError):
    """The hosted signing broker is misconfigured or refused a request."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ArtifactBrokerConfig:
    bucket: str
    prefix: str
    url: str
    token_file: Path


@dataclass(frozen=True)
class BrokerPresign:
    url: str
    method: str
    bucket: str
    key: str
    expires_in: int


def broker_config(
    env: Mapping[str, str] | None = None,
) -> ArtifactBrokerConfig | None:
    """Resolve tenant-published broker settings, failing on a partial set."""

    source = env if env is not None else os.environ
    names = (BUCKET_ENV, PREFIX_ENV, BROKER_URL_ENV, TOKEN_FILE_ENV)
    values = {name: str(source.get(name) or "").strip() for name in names}
    if not values[BROKER_URL_ENV]:
        if values[PREFIX_ENV] or values[TOKEN_FILE_ENV]:
            raise ArtifactBrokerError(
                "artifact_broker_configuration_invalid",
                f"{BROKER_URL_ENV} is required when tenant broker settings "
                "are published; restart after Platform convergence",
            )
        return None
    missing = [name for name in names if not values[name]]
    if missing:
        raise ArtifactBrokerError(
            "artifact_broker_configuration_invalid",
            "hosted QA artifact broker configuration is incomplete; missing "
            + ", ".join(missing)
            + ". Restart the tenant after its Platform runtime converges.",
        )
    try:
        prefix = safe_storage_prefix(values[PREFIX_ENV])
    except ValueError as exc:
        raise ArtifactBrokerError(
            "artifact_broker_configuration_invalid",
            f"{PREFIX_ENV} is invalid: {exc}",
        ) from exc
    parsed = urllib.parse.urlparse(values[BROKER_URL_ENV])
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ArtifactBrokerError(
            "artifact_broker_configuration_invalid",
            f"{BROKER_URL_ENV} must be an absolute HTTP(S) URL",
        )
    token_file = Path(values[TOKEN_FILE_ENV]).expanduser()
    if not token_file.is_absolute():
        raise ArtifactBrokerError(
            "artifact_broker_configuration_invalid",
            f"{TOKEN_FILE_ENV} must name an absolute path",
        )
    return ArtifactBrokerConfig(
        bucket=values[BUCKET_ENV],
        prefix=prefix,
        url=values[BROKER_URL_ENV],
        token_file=token_file,
    )


def _read_token(config: ArtifactBrokerConfig) -> str:
    try:
        token = config.token_file.read_text(encoding="utf-8").splitlines()[0].strip()
    except (OSError, IndexError) as exc:
        raise ArtifactBrokerError(
            "artifact_broker_token_unavailable",
            f"the hosted QA artifact broker token file cannot be read at "
            f"{config.token_file}; restart the tenant after token publication",
        ) from exc
    if not token:
        raise ArtifactBrokerError(
            "artifact_broker_token_unavailable",
            f"the hosted QA artifact broker token file is empty at "
            f"{config.token_file}; restart the tenant after token publication",
        )
    return token


def _broker_refusal(exc: urllib.error.HTTPError) -> ArtifactBrokerError:
    try:
        payload = json.loads(exc.read(BROKER_RESPONSE_LIMIT).decode("utf-8"))
        error = payload.get("error") if isinstance(payload, dict) else None
    except (OSError, UnicodeDecodeError, ValueError):
        error = None
    if isinstance(error, dict):
        remote_code = str(error.get("code") or "request_refused")
        message = str(error.get("message") or f"HTTP {exc.code}")
        recovery = str(error.get("recovery") or "").strip()
        detail = f"{message} Recovery: {recovery}" if recovery else message
        return ArtifactBrokerError(f"artifact_broker_{remote_code}", detail)
    return ArtifactBrokerError(
        "artifact_broker_request_refused",
        f"the hosted QA artifact broker refused the request with HTTP {exc.code}",
    )


def presign_with_broker(
    config: ArtifactBrokerConfig,
    *,
    operation: str,
    project: str,
    subject: int | str,
    run_id: int,
    filename: str,
) -> BrokerPresign:
    """Request and validate one server-derived PUT or GET URL."""

    if operation not in {"put", "get"}:
        raise ValueError("broker operation must be 'put' or 'get'")
    token = _read_token(config)
    body = json.dumps(
        {
            "operation": operation,
            "project": project,
            "subject": str(subject),
            "run_id": int(run_id),
            "filename": filename,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib.request.Request(
        config.url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(BROKER_RESPONSE_LIMIT + 1)
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        raise _broker_refusal(exc) from exc
    except (OSError, urllib.error.URLError, ValueError) as exc:
        raise ArtifactBrokerError(
            "artifact_broker_unavailable",
            "the hosted QA artifact broker could not be reached; verify the "
            "tenant runtime broker listener and retry",
        ) from exc
    if not 200 <= status < 300:
        raise ArtifactBrokerError(
            "artifact_broker_request_refused",
            f"the hosted QA artifact broker returned HTTP {status}",
        )
    if len(raw) > BROKER_RESPONSE_LIMIT:
        raise ArtifactBrokerError(
            "artifact_broker_response_invalid",
            "the hosted QA artifact broker response exceeded its size limit",
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
        result = BrokerPresign(
            url=str(payload["url"]),
            method=str(payload["method"]),
            bucket=str(payload["bucket"]),
            key=str(payload["key"]),
            expires_in=int(payload["expires_in"]),
        )
    except (KeyError, TypeError, UnicodeDecodeError, ValueError) as exc:
        raise ArtifactBrokerError(
            "artifact_broker_response_invalid",
            "the hosted QA artifact broker returned a malformed response",
        ) from exc
    expected_method = "PUT" if operation == "put" else "GET"
    expected_key = build_artifact_key(
        project, subject, run_id, filename, storage_prefix=config.prefix
    )
    if (
        result.method != expected_method
        or result.bucket != config.bucket
        or result.key != expected_key
        or not 1 <= result.expires_in <= 900
        or urllib.parse.urlparse(result.url).scheme != "https"
    ):
        raise ArtifactBrokerError(
            "artifact_broker_response_invalid",
            "the hosted QA artifact broker response did not match the requested "
            "method, configured bucket, immutable tenant prefix, or expiry",
        )
    return result


__all__ = [
    "ArtifactBrokerConfig", "ArtifactBrokerError", "BROKER_URL_ENV",
    "BUCKET_ENV", "BrokerPresign", "PREFIX_ENV", "TOKEN_FILE_ENV",
    "broker_config", "presign_with_broker",
]
