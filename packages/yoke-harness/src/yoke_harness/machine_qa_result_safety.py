"""Secret redaction and submission guards shared across Machine QA."""

from __future__ import annotations

from typing import Any, Sequence


_FORBIDDEN_RESULT_KEYS = frozenset(
    {
        "secret",
        "secrets",
        "secret_path",
        "secret_paths",
        "ssh_private_key",
    }
)
_FORBIDDEN_RESULT_MARKERS = (
    "-----BEGIN OPENSSH PRIVATE KEY-----",
    "-----BEGIN RSA PRIVATE KEY-----",
)


def redact_machine_qa_value(value: Any, secrets: Sequence[str]) -> Any:
    """Return a recursively redacted host-control result."""
    if isinstance(value, dict):
        return {
            str(key): redact_machine_qa_value(item, secrets)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_machine_qa_value(item, secrets) for item in value]
    if isinstance(value, tuple):
        return [redact_machine_qa_value(item, secrets) for item in value]
    if isinstance(value, str):
        redacted = value
        for secret in secrets:
            if secret:
                redacted = redacted.replace(secret, "[REDACTED]")
        return redacted
    return value


def ensure_secret_free_result(value: Any) -> None:
    """Reject credential-shaped fields or private-key material recursively."""
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            if normalized in _FORBIDDEN_RESULT_KEYS:
                raise ValueError(
                    f"host-control result contains forbidden field {key!r}"
                )
            ensure_secret_free_result(child)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            ensure_secret_free_result(child)
        return
    if isinstance(value, str) and any(
        marker in value for marker in _FORBIDDEN_RESULT_MARKERS
    ):
        raise ValueError("host-control result contains private-key material")


__all__ = ["ensure_secret_free_result", "redact_machine_qa_value"]
