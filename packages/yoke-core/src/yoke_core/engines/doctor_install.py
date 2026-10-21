"""Install readiness roster and machine-local observations."""

from __future__ import annotations

import json
import shlex
import os
import urllib.request
from contextlib import nullcontext

from yoke_contracts.engine_version import ENGINE_VERSION_HEADER, local_handshake_version
from yoke_contracts.execution_provenance import collect_execution_provenance
from yoke_contracts.executor_labels import harness_display_name
from yoke_contracts.harness_cli_manifest import HARNESS_CLI_MANIFESTS
from yoke_contracts.harness_hook_approval import HARNESS_HOOK_APPROVAL
from yoke_contracts.machine_config.schema import (
    TRANSPORT_HTTPS,
    MachineConfigContractError,
)
from yoke_contracts.machine_config.served_view_connection import server_workbench_url
from yoke_contracts.runtime_identity import SERVED_BUILD_PATH
from yoke_cli.config import machine_config, universe_ui_daemon_state
from yoke_cli.config.path_harness_clis import resolve_harness_clis
from yoke_cli.transport.dispatcher import build_actor
from yoke_core.domain.control_plane_transport import relay
from yoke_core.domain.project_scratch_dir import scratch_project
from yoke_core.domain.session_orientation_delivery import orientation_delivered
from yoke_core.engines.doctor_registry_types import HealthCheck
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector, _run

# Guidance checks are kept with their filesystem evidence owner.
from yoke_core.engines.doctor_install_guidance import (
    hc_install_residue,
    hc_installed_guidance,
    hc_instruction_discovery,
)


from yoke_core.engines.doctor_hc_connections import (
    active_connection_failure as active_connection_failure,
    hc_connections,
)


INSTALL_SLUGS = (
    "connections",
    "machine-registry",
    "session-relay",
    "hook-resident",
    "harness-unattended-posture",
    "harness-setup",
    "project-gh-auth",
    "harness-cli-auth",
    "dashboard-current-build",
    "session-hook-registration",
    "install-residue",
    "installed-guidance",
    "instruction-discovery",
)


def harness_auth(manifest, executable: str) -> tuple[bool, str]:
    """Whether one harness CLI is signed in, and the line that says so."""
    probe = _run([executable, *manifest.auth_args], timeout=5)
    signed_in = probe.returncode == 0
    if manifest.auth_signed_in_key:
        try:
            document = json.loads(probe.stdout)
            signed_in = signed_in and document.get(manifest.auth_signed_in_key) is True
        except (ValueError, AttributeError):
            signed_in = False
    # Native auth documents contain private account data. Keep only the verdict.
    if signed_in:
        return True, f"{manifest.executable} is signed in."
    login = shlex.join((manifest.executable, *manifest.login_args))
    return False, (
        f"HARNESS_AUTH_UNVERIFIED: {manifest.executable} sign-in could not be "
        f"verified. Run `{login}`."
    )


def installed_harness_clis() -> dict[str, str]:
    """Harness id -> CLI path for every supported harness CLI on PATH."""
    return {
        entry.harness_id: entry.path
        for entry in resolve_harness_clis(os.environ.get("PATH"))
        if entry.path
    }


def hc_harness_cli_auth(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    available = installed_harness_clis()
    for manifest in HARNESS_CLI_MANIFESTS:
        executable = available.get(manifest.harness_id)
        if executable is None:
            continue
        signed_in, detail = harness_auth(manifest, executable)
        rec.record(
            "harness-cli-auth",
            "Harness CLI sign-in",
            "PASS" if signed_in else "FAIL",
            detail,
        )
    if not available:
        rec.record(
            "harness-cli-auth",
            "Harness CLI sign-in",
            "FAIL",
            "HARNESS_CLI_MISSING: no supported harness CLI is installed. Install a harness CLI, sign in, and rerun Doctor.",
        )


def dashboard_identity() -> tuple[str, str]:
    record = universe_ui_daemon_state.read_record()
    if record is None or not universe_ui_daemon_state.process_alive(record.pid):
        raise ValueError("DASHBOARD_NOT_RUNNING")
    host = "127.0.0.1" if record.host in {"0.0.0.0", "::"} else record.host
    if ":" in host:
        host = f"[{host}]"
    with urllib.request.urlopen(
        f"http://{host}:{record.port}{SERVED_BUILD_PATH}", timeout=3
    ) as response:
        return response.read(256).decode("utf-8").strip(), response.headers.get(
            ENGINE_VERSION_HEADER, ""
        )


def active_https_connection():
    """The active connection when it relays over https, else ``None``."""
    try:
        connection = machine_config.active_connection()
    except MachineConfigContractError:
        return None
    if str(connection.get("transport") or "").strip() != TRANSPORT_HTTPS:
        return None
    return connection


def hc_dashboard_current_build(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    hosted = active_https_connection()
    if hosted is not None:
        rec.record(
            "dashboard-current-build",
            "Dashboard runs the installed build",
            "N/A",
            f"The active connection {hosted.get('env')!r} is https: its server "
            "serves the workbench, so no local dashboard runs here. Open "
            f"{server_workbench_url(hosted)} in a browser.",
        )
        return
    try:
        build, version = dashboard_identity()
        expected = collect_execution_provenance()["source_sha"]
        installed = local_handshake_version()
        if expected != "unknown":
            current = bool(expected) and build == expected
        else:
            current = bool(installed and installed != "0.1.0") and version == installed
        if not current:
            raise ValueError("DASHBOARD_BUILD_UNVERIFIED")
    except (OSError, ValueError, UnicodeError):
        rec.record(
            "dashboard-current-build",
            "Dashboard runs the installed build",
            "FAIL",
            "DASHBOARD_BUILD_UNVERIFIED: the dashboard is stopped, stale, or has no matching build identity. Run `yoke ui down`, then `yoke ui up`.",
        )
        return
    rec.record(
        "dashboard-current-build",
        "Dashboard runs the installed build",
        "PASS",
        "The running dashboard matches the installed code identity.",
    )


class _SessionHookUnproven(ValueError):
    """A registered session or its orientation could not be proven."""


def session_hook_recovery(reason: str = "SESSION_HOOK_UNOBSERVED") -> str:
    """The unproven-registration line: what happened and the one next step."""
    approvals = "".join(
        f" In {harness_display_name(harness_id)}, first approve this project's "
        f"hooks in {gate['trust_surface']}."
        for harness_id, gate in HARNESS_HOOK_APPROVAL.items()
    )
    return (
        f"{reason}: registration and hook delivery for this "
        "session are not both proven. Start a new harness session in the "
        "installed project (quit and reopen the harness app if it stays open), "
        "then rerun the same `yoke doctor run` command." + approvals
    )


def hc_session_hook_registration(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    try:
        session_id = build_actor().session_id
        if not session_id:
            raise _SessionHookUnproven("SESSION_HOOK_UNOBSERVED")
        identity = relay("sessions.identity", {})
        if identity.get("session_id") != session_id:
            raise _SessionHookUnproven("SESSION_REGISTRATION_UNVERIFIED")
        if args.project:
            from yoke_core.domain.project_checkout_locations import project_id_for_slug

            requested = str(args.project)
            expected_project = (
                int(requested)
                if requested.isdigit()
                else project_id_for_slug(requested)
            )
            if expected_project is None or str(identity.get("project_id")) != str(
                expected_project
            ):
                raise _SessionHookUnproven("SESSION_HOOK_PROJECT_MISMATCH")
        project_id = identity.get("project_id")
        # Outside-project hooks use the authority's machine scratch namespace.
        with scratch_project(str(project_id)) if project_id else nullcontext():
            if not orientation_delivered(session_id):
                raise _SessionHookUnproven("SESSION_HOOK_UNOBSERVED")
    except _SessionHookUnproven as exc:
        rec.record(
            "session-hook-registration",
            "This session received a registering hook",
            "FAIL",
            session_hook_recovery(str(exc)),
        )
        return
    except (OSError, RuntimeError, ValueError, LookupError) as exc:
        rec.record(
            "session-hook-registration",
            "This session received a registering hook",
            "FAIL",
            f"SESSION_HOOK_CHECK_FAILED: {exc}. Resolve the reported failure, "
            "then rerun the same `yoke doctor run` command.",
        )
        return
    rec.record(
        "session-hook-registration",
        "This session received a registering hook",
        "PASS",
        "The control plane registered this session and its local hook confirmed orientation delivery.",
    )


INSTALL_HEALTH_CHECKS = [
    HealthCheck(
        "connections", "Connection credentials and operating actors", hc_connections
    ),
    HealthCheck("harness-cli-auth", "Harness CLI sign-in", hc_harness_cli_auth),
    HealthCheck(
        "dashboard-current-build",
        "Dashboard runs the installed build",
        hc_dashboard_current_build,
    ),
    HealthCheck(
        "session-hook-registration",
        "This session received a registering hook",
        hc_session_hook_registration,
    ),
    HealthCheck(
        "install-residue", "No configuration from another install", hc_install_residue
    ),
    HealthCheck(
        "installed-guidance",
        "Installed guidance matches the running code",
        hc_installed_guidance,
    ),
    HealthCheck(
        "instruction-discovery",
        "Canonical instructions are reachable",
        hc_instruction_discovery,
    ),
]
