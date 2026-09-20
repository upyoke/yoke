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


def _field(provenance: object, key: str) -> str:
    if not isinstance(provenance, Mapping):
        return ""
    value = provenance.get(key)
    return value.strip() if isinstance(value, str) else ""


def _recovery(server: object) -> str:
    """Name the action that actually moves the server off its revision.

    A process stamps its revision once, when it imports — deliberately, so a
    checkout advancing underneath a long-running API is not reported as
    current. What closes the gap therefore depends on where that process
    loaded its code from, and only one of the two answers is a restart.
    """
    if _field(server, "install_kind") == "source_checkout":
        tree = _field(server, "install_path") or "its checkout"
        return (
            "the serving process stamped its revision when it imported, so "
            f"restarting it re-reads {tree} at whatever revision that tree is "
            "on now (restarting this session changes nothing)"
        )
    return (
        "the server runs an installed build, so restarting it re-imports the "
        "same revision — the gap closes when a build at the intended revision "
        "is installed there, not before (restarting this session changes "
        "nothing either)"
    )


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
    # diagnosing, so it names both revisions and the recovery that applies
    # to this server, and spends no further lines on it.
    return (
        f"{_NOTICE_PREFIX} evaluated by server revision "
        f"{server_revision[:12]}, client hook is {client_revision[:12]} — "
        f"{_recovery(server)}."
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
