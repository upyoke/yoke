"""Make hook-policy version skew visible inside relayed denials."""

from __future__ import annotations

from typing import Mapping

from yoke_harness.hooks.denial_notice import annotate_denial


_NOTICE_PREFIX = "Yoke guard version mismatch:"
_UNKNOWN_REVISIONS = frozenset({"", "unknown"})


def _revision(provenance: object) -> str:
    if not isinstance(provenance, Mapping):
        return ""
    value = provenance.get("source_sha")
    return value.strip().lower() if isinstance(value, str) else ""


def _same_revision(left: str, right: str) -> bool:
    return left == right or left.startswith(right) or right.startswith(left)


def guard_version_skew_notice(
    *,
    client: object,
    server: object,
) -> str:
    """Explain a known client/server guard revision mismatch."""
    client_revision = _revision(client)
    server_revision = _revision(server)
    if (
        client_revision in _UNKNOWN_REVISIONS
        or server_revision in _UNKNOWN_REVISIONS
        or _same_revision(client_revision, server_revision)
    ):
        return ""
    # One line: this rides along on a refusal the reader is already
    # diagnosing, so it names both revisions and the one recovery that
    # works, and spends no further lines on it.
    return (
        f"{_NOTICE_PREFIX} evaluated by server revision "
        f"{server_revision[:12]}, client hook is {client_revision[:12]} — "
        "restart the serving Yoke process at the intended revision "
        "(restarting this session will not update a behind server)."
    )


def annotate_guard_version_skew(
    stdout: str,
    *,
    client: object,
    server: object,
) -> str:
    """Append skew guidance without corrupting a harness deny envelope."""
    return annotate_denial(
        stdout,
        guard_version_skew_notice(client=client, server=server),
        marker=_NOTICE_PREFIX,
    )


__all__ = ["annotate_guard_version_skew", "guard_version_skew_notice"]
