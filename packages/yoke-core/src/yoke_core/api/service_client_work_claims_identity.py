"""Self-only CLI identity validation for claim/release work-claim commands.

The ordinary ``claim-work`` and ``release-work-claim`` CLI surfaces are
*self-only*: a caller may not supply ``--session-id OTHER`` to act on
another live session's behalf. This module owns the boundary check that
enforces it.

The check sits between argparse and any DB mutation in every code path:

- before ``_validate_active_session``,
- before ``_delegate_claim`` (claim path),
- before ``release_work_claim_for_execution`` (release path),
- before ``emit_release_override`` (operator-rationale path).

Authority sources:

- *ambient*: the canonical ambient chain walked by
  :func:`yoke_core.api.service_client_shared_session_resolver._resolve_session_id`
  (env vars, then the hook-written process-anchor registry).
- *explicit*: the optional ``--session-id`` flag.

Decision matrix:

- explicit empty, ambient set -> accept ambient (omit-flag happy path).
- explicit empty, ambient empty -> refuse ``ambient_session_missing``.
- explicit == ambient (both set) -> accept (explicit-self happy path).
- explicit set, ambient empty -> refuse ``ambient_session_missing``;
  an unprovable explicit value is never authority.
- explicit != ambient (both set) -> refuse ``session_id_mismatch``.

Operator takeover via an explicit ``--session-id OTHER`` is **not**
supported here. A future operator-only surface may be added; until
then, the only sanctioned cross-session release path is
``ItemClaimReleaseOverride`` driven by infrastructure (the SessionEnd
hook, stale-claim reclaim), never by an ordinary CLI caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from yoke_core.api.service_client_shared_session_resolver import (
    _resolve_session_id,
)


ERROR_CODE_AMBIENT_MISSING = "ambient_session_missing"
ERROR_CODE_MISMATCH = "session_id_mismatch"


@dataclass(frozen=True)
class SelfIdentityCheck:
    """Outcome of the self-only identity check.

    On success (``ok=True``), ``effective_session_id`` is the value all
    downstream helpers must use as authority. On failure (``ok=False``),
    ``code`` is a stable machine-readable identifier (see
    ``ERROR_CODE_*`` constants) and ``message`` is the operator-facing
    explanation; the CLI surfaces both in the refusal JSON.
    """

    ok: bool
    effective_session_id: Optional[str] = None
    code: Optional[str] = None
    message: Optional[str] = None


_AmbientResolver = Callable[[], Optional[str]]


def _default_ambient_resolver() -> Optional[str]:
    return _resolve_session_id(None)


def check_self_only_session_identity(
    explicit: Optional[str],
    *,
    ambient_resolver: _AmbientResolver = _default_ambient_resolver,
) -> SelfIdentityCheck:
    """Validate that the optional ``--session-id`` matches the ambient session.

    ``explicit`` is the raw value parsed from ``--session-id``. Pass
    ``None`` or ``""`` when the flag was omitted.

    The ambient session is read from the env chain by default. The
    ``ambient_resolver`` keyword exists so unit tests can pin the
    ambient value without monkeypatching ``os.environ``.
    """
    ambient = ambient_resolver()
    ambient_norm = ambient.strip() if ambient else ""
    explicit_norm = explicit.strip() if explicit else ""

    if not ambient_norm:
        return SelfIdentityCheck(
            ok=False,
            code=ERROR_CODE_AMBIENT_MISSING,
            message=(
                "No ambient session identity (env chain + process-anchor "
                "registry both empty) — a Yoke infrastructure gap to "
                "report, not something to work around. claim-work and "
                "release-work-claim are self-only, so an explicit "
                "--session-id is not accepted without a matching ambient "
                "session."
            ),
        )

    if explicit_norm and explicit_norm != ambient_norm:
        return SelfIdentityCheck(
            ok=False,
            code=ERROR_CODE_MISMATCH,
            message=(
                f"--session-id {explicit_norm!r} does not match ambient "
                f"session {ambient_norm!r}. claim-work and "
                "release-work-claim are self-only; supply --session-id "
                "only when it equals your ambient session, or omit it."
            ),
        )

    return SelfIdentityCheck(ok=True, effective_session_id=ambient_norm)


__all__ = [
    "ERROR_CODE_AMBIENT_MISSING",
    "ERROR_CODE_MISMATCH",
    "SelfIdentityCheck",
    "check_self_only_session_identity",
]
