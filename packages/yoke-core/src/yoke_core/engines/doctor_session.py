"""Session readiness: can this harness session do Yoke work right now?

Install health asks about the whole machine. Before onboarding, a session
asks a narrower question: is it registered, is its own harness CLI signed in,
and does its own harness run ``yoke`` without approval prompts? Another
harness installed on the same machine does not block it, so both harness
checks read the harness the control plane registered for this session.

``yoke doctor run --session`` runs these three checks. Setup's agent mode
ends with it, and ``/yoke onboard`` runs it first.
"""

from __future__ import annotations

from yoke_contracts.executor_labels import canonical_harness_id
from yoke_contracts.harness_cli_manifest import harness_cli_manifest
from yoke_contracts.harness_unattended_posture import POSTURE_RECOVERY
from yoke_cli.transport.dispatcher import build_actor
from yoke_core.domain.control_plane_transport import relay
from yoke_core.engines.doctor_hc_harness_unattended_posture import harness_posture
from yoke_core.engines.doctor_install import (
    harness_auth,
    installed_harness_clis,
)
from yoke_core.engines.doctor_registry_types import HealthCheck
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector

AUTH_SLUG = "session-harness-cli-auth"
AUTH_TITLE = "This session's harness CLI is signed in"
POSTURE_SLUG = "session-harness-unattended-posture"
POSTURE_TITLE = "This session's harness runs yoke without approval prompts"

SESSION_SLUGS = ("session-hook-registration", AUTH_SLUG, POSTURE_SLUG)

UNKNOWN_HARNESS = (
    "SESSION_HARNESS_UNKNOWN: this session is not registered, so its harness "
    "is unknown. Fix the session registration check first, then rerun "
    "`yoke doctor run --session`."
)


def session_harness() -> tuple[str, str | None] | None:
    """The registered harness family and surface, or ``None``."""
    session_id = build_actor().session_id
    if not session_id:
        return None
    try:
        identity = relay("sessions.identity", {})
        if identity.get("session_id") != session_id:
            return None
        harness_id = canonical_harness_id(identity.get("executor"))
        return (harness_id, identity.get("executor_surface")) if harness_id else None
    except Exception:  # an unread identity is an unknown harness, not a guess
        return None


def hc_session_harness_cli_auth(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    harness = session_harness()
    if harness is None:
        rec.record(AUTH_SLUG, AUTH_TITLE, "FAIL", UNKNOWN_HARNESS)
        return
    harness_id, _surface_id = harness
    manifest = harness_cli_manifest(harness_id)
    executable = installed_harness_clis().get(harness_id)
    if executable is None:
        rec.record(
            AUTH_SLUG,
            AUTH_TITLE,
            "FAIL",
            f"HARNESS_CLI_MISSING: this session runs {harness_id}, but "
            f"`{manifest.executable}` is not on PATH. Install the "
            f"{manifest.executable} CLI, sign in, and rerun "
            "`yoke doctor run --session`.",
        )
        return
    signed_in, detail = harness_auth(manifest, executable)
    rec.record(AUTH_SLUG, AUTH_TITLE, "PASS" if signed_in else "FAIL", detail)


def hc_session_harness_unattended_posture(
    conn, args: DoctorArgs, rec: RecordCollector
) -> None:
    harness = session_harness()
    if harness is None:
        rec.record(POSTURE_SLUG, POSTURE_TITLE, "FAIL", UNKNOWN_HARNESS)
        return
    harness_id, surface_id = harness
    if harness_id == "claude-code" and not surface_id:
        rec.record(
            POSTURE_SLUG,
            POSTURE_TITLE,
            "FAIL",
            "SESSION_HARNESS_SURFACE_UNKNOWN: this Claude session's surface "
            "is not registered. Restore hook registration and rerun "
            "`yoke doctor run --session`.",
        )
        return
    # The session is running this harness, so a missing config is a failure.
    verdict, detail = harness_posture(harness_id, installed=True, surface_id=surface_id)
    if harness_id == "claude-code" and surface_id not in (
        "claude-cli",
        "claude-desktop",
    ):
        rec.record(POSTURE_SLUG, POSTURE_TITLE, verdict, detail)
        return
    if verdict == "PASS":
        rec.record(
            POSTURE_SLUG, POSTURE_TITLE, "PASS", f"{harness_id} runs yoke unattended."
        )
        return
    rec.record(
        POSTURE_SLUG,
        POSTURE_TITLE,
        "FAIL",
        f"{detail}\n  {POSTURE_RECOVERY} Then start a new session.",
    )


SESSION_HEALTH_CHECKS = [
    HealthCheck(AUTH_SLUG, AUTH_TITLE, hc_session_harness_cli_auth),
    HealthCheck(POSTURE_SLUG, POSTURE_TITLE, hc_session_harness_unattended_posture),
]

__all__ = [
    "SESSION_HEALTH_CHECKS",
    "SESSION_SLUGS",
    "hc_session_harness_cli_auth",
    "hc_session_harness_unattended_posture",
    "session_harness",
]
