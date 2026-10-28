"""Scripted install readiness refusals against the installed candidate."""

import shlex

from yoke_core.domain.machine_qa_fixture_constants import YOKE_BIN

INSTALL_HEALTH_FAILURE_SCRIPT = r"""
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import sys
from yoke_core.engines import doctor_install as checks
from yoke_core.engines import doctor_install_guidance as guidance
from yoke_core.engines import doctor_hc_machine_registry as machine
from yoke_core.engines import doctor_hc_hook_resident as resident
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
with TemporaryDirectory(prefix="install-health-") as directory:
    root = Path(directory)
    paths = SimpleNamespace(socket=root / "socket", log=root / "log")
    cases = {
        "harness-auth-missing": (checks.hc_harness_cli_auth, "HARNESS_CLI_MISSING", [
            (checks, "resolve_harness_clis", lambda path: []),
        ]),
        "dashboard-stale": (checks.hc_dashboard_current_build, "DASHBOARD_BUILD_UNVERIFIED", [
            (checks, "active_https_connection", lambda: None),
            (checks, "dashboard_identity", lambda: ("b" * 40, "")),
            (checks, "collect_execution_provenance", lambda: {"source_sha": "a" * 40}),
        ]),
        "session-hook-unobserved": (checks.hc_session_hook_registration, "SESSION_HOOK_UNOBSERVED", [
            (checks, "build_actor", lambda: SimpleNamespace(session_id="fixture-session")),
            (checks, "relay", lambda function, payload: {"value": 42} if function == "projects.get" else {"session_id": "fixture-session", "project_id": 42}),
            (checks, "orientation_delivered", lambda session: False),
        ]),
        "foreign-install-binding": (guidance.hc_install_residue, "INSTALL_RESIDUE", [
            (guidance, "project_root", lambda args: root),
            (guidance, "canonical_shim_path", lambda: root / "yoke"),
            (guidance, "hook_config_yoke_problems", lambda *args: []),
            (guidance, "enumerate_shadow_installs", lambda **kwargs: []),
            (guidance, "load_manifest", lambda checkout: {"project_id": 99}),
            (guidance.machine_config, "load_config", lambda: {"projects": [{"checkout": str(root), "project_id": 42}]}),
        ]),
        "guidance-unknown": (guidance.hc_installed_guidance, "INSTALLED_GUIDANCE_UNVERIFIED", [
            (guidance, "project_root", lambda args: root),
            (guidance.project_installed_layer, "scan", lambda checkout: SimpleNamespace(present=False)),
        ]),
        "instruction-pointer-missing": (guidance.hc_instruction_discovery, "INSTRUCTION_DISCOVERY_UNVERIFIED", [
            (guidance, "project_root", lambda args: root),
        ]),
        "machine-unregistered": (machine.hc_machine_registry, "MACHINE_NOT_REGISTERED", [
            (machine, "_local_machine_id", lambda: ""),
        ]),
        "resident-stale": (resident.hc_hook_resident, "YOKE_HOOK_VERSION_MISMATCH", [
            (resident, "resident_paths", lambda: paths),
            (resident, "resident_revision_problem", lambda *args: "YOKE_HOOK_VERSION_MISMATCH"),
        ]),
    }
    recovery_tokens = dict([
        ("harness-auth-missing", "npm install -g @openai/codex"),
        ("dashboard-stale", "yoke ui down"),
        ("session-hook-unobserved", "Start a new harness session"),
        ("foreign-install-binding", "yoke setup"),
        ("guidance-unknown", "yoke project install"),
        ("instruction-pointer-missing", "yoke project install"),
        ("machine-unregistered", "yoke setup"),
        ("resident-stale", "yoke hook resident restart"),
    ])
    fn, reason, patches = cases[scenario]
    with ExitStack() as stack:
        for owner, name, value in patches:
            stack.enter_context(patch.object(owner, name, value))
        records = RecordCollector()
        fn(None, DoctorArgs(project="42", only=",".join(checks.INSTALL_SLUGS)), records)
    expected = "WARN" if scenario == "harness-auth-missing" else "FAIL"
    if not records.results or any(row.result != expected or reason not in row.detail or recovery_tokens[scenario] not in row.detail for row in records.results):
        sys.exit("install_health_refusal_missing: inspect the candidate readiness check before rerunning")
    print(scenario + ": " + reason + "; diagnosed recovery verified")
"""

_FAILURE_KEYS = (
    "harness-auth-missing",
    "dashboard-stale",
    "session-hook-unobserved",
    "foreign-install-binding",
    "guidance-unknown",
    "instruction-pointer-missing",
    "machine-unregistered",
    "resident-stale",
)


def install_health_cases(command_case):
    """Run isolated evidence injections without changing real account state."""
    return tuple(
        command_case(
            position,
            "install-health-" + key,
            YOKE_BIN
            + ' --version; "$(uv tool dir)/yoke-cli-releases/current/tools/yoke-cli/bin/python3" -c '
            + shlex.quote(
                "from yoke_core.domain.installer_campaign_install_health_cases import run_failure_probe; import sys; run_failure_probe(sys.argv[1])"
            )
            + " "
            + shlex.quote(key),
            instructions=(
                "Run the installed candidate's readiness refusal with isolated injected evidence; preserve real sign-in, hook and machine configuration."
            ),
            outcome=(
                "Missing CLI evidence produces WARN; other unknown, stale or foreign evidence produces FAIL, each with named recovery; configuration alone never proves observed delivery."
            ),
        )
        for position, key in enumerate(_FAILURE_KEYS, 17)
    )


def run_failure_probe(scenario: str) -> None:
    """Exercise one isolated diagnosed refusal using the installed candidate."""
    exec(
        compile(INSTALL_HEALTH_FAILURE_SCRIPT, "install-health-failure", "exec"),
        {"scenario": scenario},
    )
