"""AWS Lambda client for process-only runner-fleet provider tokens."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
import hashlib
import hmac
import json
from typing import Any

from yoke_cli.transport.https import TransportError


_RESPONSE_LIMIT_BYTES = 64 * 1024


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _validated_intent(authority_intent: str) -> tuple[dict[str, object], str]:
    try:
        envelope = json.loads(authority_intent)
        authority = envelope["authority"]
        digest = str(envelope["sha256"])
        schema = envelope["schema"]
    except (KeyError, TypeError, ValueError) as exc:
        raise TransportError("runner-fleet authority intent is invalid") from exc
    if schema != 1 or not isinstance(authority, dict):
        raise TransportError("runner-fleet authority intent is invalid")
    actual = hashlib.sha256(
        _canonical_json(authority).encode("utf-8")
    ).hexdigest()
    if len(digest) != 64 or not hmac.compare_digest(digest, actual):
        raise TransportError("runner-fleet authority intent digest is invalid")
    return authority, digest


def _client_from_aws_env(
    aws_env: Mapping[str, str], region: str,
) -> Any:
    import boto3
    from botocore.config import Config

    access_key = str(aws_env.get("AWS_ACCESS_KEY_ID") or "").strip()
    secret_key = str(aws_env.get("AWS_SECRET_ACCESS_KEY") or "").strip()
    session_token = str(aws_env.get("AWS_SESSION_TOKEN") or "").strip()
    if not access_key or not secret_key:
        raise TransportError("runner-fleet AWS invocation credentials are absent")
    return boto3.client(
        "lambda",
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        aws_session_token=session_token or None,
        config=Config(
            connect_timeout=10,
            read_timeout=30,
            retries={"max_attempts": 2, "mode": "standard"},
        ),
    )


def fetch_runner_fleet_token(
    *,
    project: str,
    authority_intent: str,
    aws_env: Mapping[str, str],
    client_factory: Callable[[Mapping[str, str], str], Any] = (
        _client_from_aws_env
    ),
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> str:
    """Invoke the key-owning broker without exposing its response on errors."""
    authority, digest = _validated_intent(authority_intent)
    if str(authority.get("project") or "") != str(project or "").strip():
        raise TransportError("runner-fleet authority project does not match")
    region = str(authority.get("aws_region") or "").strip()
    function_name = str(
        authority.get("token_broker_function") or ""
    ).strip()
    expected_repository = str(authority.get("repo") or "").strip()
    if not region or not function_name or not expected_repository:
        raise TransportError("runner-fleet authority intent is incomplete")
    request = _canonical_json({
        "action": "provider_token",
        "authority": authority,
        "authority_sha256": digest,
    }).encode("utf-8")
    try:
        response = client_factory(aws_env, region).invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",
            Payload=request,
        )
        if response.get("FunctionError"):
            raise TransportError(
                "runner-fleet token broker invocation failed "
                f"(FunctionError={response.get('FunctionError')})"
            )
        stream = response.get("Payload")
        if stream is None:
            raise TransportError("runner-fleet token broker returned no payload")
        raw = stream.read(_RESPONSE_LIMIT_BYTES + 1)
    except TransportError:
        raise
    except Exception as exc:
        # The broker response body is never echoed; the transport error class
        # and first line are safe and distinguish a missing function from a
        # denied invoke without another AWS-side inventory pass.
        cause = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
        raise TransportError(
            "runner-fleet token broker invocation failed "
            f"({type(exc).__name__}: {cause[:200]})"
        ) from exc
    if len(raw) > _RESPONSE_LIMIT_BYTES:
        raise TransportError("runner-fleet token broker response was too large")
    try:
        grant = json.loads(raw)
        token = str(grant["token"]).strip()
        expires_at = datetime.fromisoformat(
            str(grant["expires_at"]).replace("Z", "+00:00")
        )
        repository = str(grant["repository"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TransportError(
            "runner-fleet token broker returned an invalid response"
        ) from exc
    if not token:
        raise TransportError("runner-fleet token broker returned an empty token")
    if repository != expected_repository:
        raise TransportError(
            "runner-fleet token broker returned a different repository binding"
        )
    if expires_at.tzinfo is None or expires_at <= now():
        raise TransportError("runner-fleet token broker returned an expired token")
    return token


__all__ = ["fetch_runner_fleet_token"]
