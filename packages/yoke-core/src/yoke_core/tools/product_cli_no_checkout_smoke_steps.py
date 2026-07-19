"""Steps for the product-wheel no-checkout CLI smoke.

Each step runs machine-installed ``yoke`` commands from an empty
"project" directory (no Yoke checkout) through an injected runner and
returns a ``{"step", "status", "failures", "evidence"}`` dict, so the
whole sequence is unit-testable with canned command results.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from yoke_core.tools import product_cli_remote_steps as _remote_steps
from yoke_core.tools.checkout_clean_room_smoke_helpers import CommandResult, tail


STEP_WHEEL_INSTALL = "wheel_install_isolation"
STEP_MISSING_CONFIG = "missing_config_failure"
STEP_WRITER_BOOTSTRAP = "writer_bootstrap"
STEP_MISSING_CREDENTIAL = "missing_credential_failure"
STEP_RELAY_DENIAL = "relay_denial"
STEP_UNKNOWN_ENV = "unknown_env_failure"
STEP_BROWSER_HYGIENE = "browser_substrate_hygiene"
STEP_NO_PROJECT_WRITES = "no_project_dir_writes"

STATUS_PASS = "pass"
STATUS_FAIL = "fail"
STATUS_SKIPPED_OFFLINE = "skipped:offline"

ENV_SMOKE = "smoke"
ENV_MISSING_CREDENTIAL = "smoke2"
ENV_GHOST = "ghost"
SMOKE_TOKEN_VALUE = "smoke-invalid-token"
SMOKE_PROJECT_ID = 1
DENIAL_CODES = ("authentication_malformed", "authentication_unknown")
BROWSER_RUNTIME_DIR_NAME = "browser-runtime"
FORBIDDEN_PROJECT_ENTRIES = ("browser", "node_modules")

STEP_NETWORK_UNREACHABLE = _remote_steps.STEP_NETWORK_UNREACHABLE
STEP_PACKS_LIST_PRODUCT = _remote_steps.STEP_PACKS_LIST_PRODUCT
step_network_unreachable = _remote_steps.step_network_unreachable
step_packs_list_product_client = _remote_steps.step_packs_list_product_client

# Runner contract: (command, step_name) -> CommandResult, never raising
# on non-zero exit — most steps assert that failures ARE non-zero.
StepRunner = Callable[[list, str], CommandResult]


@dataclass(frozen=True)
class SmokeContext:
    """Paths and switches the steps operate against."""

    api_url: str
    online: bool
    project_dir: Path
    machine_home: Path
    yoke: Path
    venv_python: Path
    token_path: Path

    @property
    def config_path(self) -> Path:
        return self.machine_home / "config.json"


def execute_steps(ctx: SmokeContext, run: StepRunner) -> list[dict[str, Any]]:
    """Run smoke steps 2-9 in order, recording pass/fail per step."""
    return [
        step_missing_config(ctx, run),
        step_writer_bootstrap(ctx, run),
        step_missing_credential(ctx, run),
        step_network_unreachable(ctx, run),
        step_packs_list_product_client(ctx, run),
        step_relay_denial(ctx, run),
        step_unknown_env(ctx, run),
        step_browser_hygiene(ctx, run),
        step_no_project_dir_writes(ctx),
    ]


def step_missing_config(ctx: SmokeContext, run: StepRunner) -> dict[str, Any]:
    result = run([str(ctx.yoke), "status", "--json"], STEP_MISSING_CONFIG)
    codes = issue_codes(parse_json_output(result.stdout))
    failures = _expect_nonzero(result)
    for required in ("config_missing", "connections_required"):
        if required not in codes:
            failures.append(f"status issues did not include {required!r}")
    return step_entry(STEP_MISSING_CONFIG, failures, {
        "returncode": result.returncode,
        "issue_codes": sorted(codes),
        "stderr_tail": tail(result.stderr),
    })


def step_writer_bootstrap(ctx: SmokeContext, run: StepRunner) -> dict[str, Any]:
    write_token_file(ctx.token_path)
    failures: list[str] = []
    connection = run(
        [str(ctx.yoke), "connection", "set", ENV_SMOKE,
         "--transport", "https", "--api-url", ctx.api_url,
         "--token-file", str(ctx.token_path)],
        STEP_WRITER_BOOTSTRAP,
    )
    # An unmapped cwd is a status error (project_mapping_missing), so the
    # bootstrap also registers the empty project dir — a machine-config
    # write, never a project-dir write — to make `ok: true` reachable.
    register = run(
        [str(ctx.yoke), "project", "register", str(ctx.project_dir),
         "--project-id", str(SMOKE_PROJECT_ID)],
        STEP_WRITER_BOOTSTRAP,
    )
    for label, result in (("connection set", connection),
                          ("project register", register)):
        if result.returncode != 0:
            failures.append(
                f"{label} failed with {result.returncode}: {tail(result.stderr)}"
            )
    status = run([str(ctx.yoke), "status", "--json"], STEP_WRITER_BOOTSTRAP)
    payload = parse_json_output(status.stdout) or {}
    if payload.get("ok") is not True:
        failures.append(
            "status ok was not true; issues: "
            + json.dumps(payload.get("issues") or [])
        )
    envs = ((payload.get("connection") or {}).get("envs"))
    if envs != [ENV_SMOKE]:
        failures.append(f"connection.envs was {envs!r}, expected [{ENV_SMOKE!r}]")
    mode = _owner_only_mode(ctx.config_path)
    if mode is None:
        failures.append(f"machine config missing: {ctx.config_path}")
    elif mode & 0o077:
        failures.append(f"machine config is not 0600: mode {oct(mode)}")
    return step_entry(STEP_WRITER_BOOTSTRAP, failures, {
        "status_returncode": status.returncode,
        "status_ok": payload.get("ok"),
        "connection_envs": envs,
        "config_path": str(ctx.config_path),
        "config_mode": (oct(mode) if mode is not None else None),
    })


def step_missing_credential(ctx: SmokeContext, run: StepRunner) -> dict[str, Any]:
    missing_path = ctx.machine_home / "secrets" / "missing.token"
    _seed_missing_credential_env(ctx, missing_path)
    status = run(
        [str(ctx.yoke), "--env", ENV_MISSING_CREDENTIAL, "status", "--json"],
        STEP_MISSING_CREDENTIAL,
    )
    codes = issue_codes(parse_json_output(status.stdout))
    failures = _expect_nonzero(status)
    if "credential_missing" not in codes:
        failures.append("status issues did not include 'credential_missing'")
    return step_entry(STEP_MISSING_CREDENTIAL, failures, {
        "missing_credential_path": str(missing_path),
        "status_returncode": status.returncode,
        "issue_codes": sorted(codes),
    })


def step_relay_denial(ctx: SmokeContext, run: StepRunner) -> dict[str, Any]:
    if not ctx.online:
        entry = step_entry(STEP_RELAY_DENIAL, [], {
            "reason": "offline run; pass --online to exercise the live relay",
        })
        entry["status"] = STATUS_SKIPPED_OFFLINE
        return entry
    query = run(
        [str(ctx.yoke), "--env", ENV_SMOKE,
         "events", "query", "--limit", "1", "--json"],
        STEP_RELAY_DENIAL,
    )
    failures = _expect_nonzero(query)
    output = _combined_output(query)
    matched = [code for code in DENIAL_CODES if code in output]
    if not matched:
        failures.append(
            f"output carried none of the typed denial codes {DENIAL_CODES}"
        )
    return step_entry(STEP_RELAY_DENIAL, failures, {
        "returncode": query.returncode,
        "denial_codes_seen": matched,
        "stdout_tail": tail(query.stdout),
        "stderr_tail": tail(query.stderr),
    })


def step_unknown_env(ctx: SmokeContext, run: StepRunner) -> dict[str, Any]:
    status = run(
        [str(ctx.yoke), "--env", ENV_GHOST, "status", "--json"],
        STEP_UNKNOWN_ENV,
    )
    failures = _expect_nonzero(status)
    payload = parse_json_output(status.stdout) or {}
    messages = " ".join(
        str(issue.get("message") or "")
        for issue in payload.get("issues") or []
        if isinstance(issue, Mapping)
    )
    if ENV_SMOKE not in messages:
        failures.append(
            "unknown-env issue did not name the configured envs "
            f"(expected {ENV_SMOKE!r} in: {messages!r})"
        )
    return step_entry(STEP_UNKNOWN_ENV, failures, {
        "returncode": status.returncode,
        "issue_messages": messages,
    })


def step_browser_hygiene(ctx: SmokeContext, run: StepRunner) -> dict[str, Any]:
    result = run(
        [str(ctx.venv_python), "-m", "yoke_core.domain.browser_client",
         "daemon", "status"],
        STEP_BROWSER_HYGIENE,
    )
    failures: list[str] = []
    entries = dir_entries(ctx.project_dir)
    polluted = [name for name in FORBIDDEN_PROJECT_ENTRIES if name in entries]
    if polluted:
        failures.append(
            "project dir gained browser substrate entries: " + ", ".join(polluted)
        )
    runtime_dir = ctx.machine_home / BROWSER_RUNTIME_DIR_NAME
    if runtime_dir.is_dir():
        outcome = "materialized_machine_side"
        if not (runtime_dir / "package.json").is_file():
            failures.append(
                f"{runtime_dir} exists without package.json — materialization "
                "did not land machine-side"
            )
    else:
        outcome = "not_materialized"
    return step_entry(STEP_BROWSER_HYGIENE, failures, {
        "returncode": result.returncode,
        "stdout_tail": tail(result.stdout),
        "outcome": outcome,
        "project_dir_entries": entries,
    })


def step_no_project_dir_writes(ctx: SmokeContext) -> dict[str, Any]:
    entries = dir_entries(ctx.project_dir)
    failures = []
    if entries:
        failures.append(
            "project dir is not empty after the smoke — the no-checkout "
            "promise is broken: " + ", ".join(entries)
        )
    return step_entry(STEP_NO_PROJECT_WRITES, failures, {
        "project_dir_entries": entries,
    })


def step_entry(
    step: str,
    failures: list[str],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {"step": step, "status": STATUS_FAIL if failures else STATUS_PASS,
            "failures": list(failures), "evidence": evidence}


def write_token_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SMOKE_TOKEN_VALUE + "\n", encoding="utf-8")
    path.chmod(0o600)


def _seed_missing_credential_env(ctx: SmokeContext, missing_path: Path) -> None:
    payload = parse_json_output(ctx.config_path.read_text(encoding="utf-8")) or {}
    payload.setdefault("connections", {})[ENV_MISSING_CREDENTIAL] = {
        "transport": "https",
        "api_url": ctx.api_url,
        "credential_source": {"kind": "token_file", "path": str(missing_path)},
    }
    ctx.config_path.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8",
    )
    ctx.config_path.chmod(0o600)


def parse_json_output(stdout: str) -> Optional[dict[str, Any]]:
    try:
        payload = json.loads(stdout)
    except (ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def issue_codes(payload: Optional[Mapping[str, Any]]) -> set:
    if not isinstance(payload, Mapping):
        return set()
    return {
        str(issue.get("code") or "")
        for issue in payload.get("issues") or []
        if isinstance(issue, Mapping)
    }


def dir_entries(path: Path) -> list[str]:
    if not path.is_dir():
        return []
    return sorted(entry.name for entry in path.iterdir())


def _expect_nonzero(result: CommandResult) -> list[str]:
    if result.returncode == 0:
        return [f"{result.step}: expected a non-zero exit, got 0"]
    return []


def _combined_output(result: CommandResult) -> str:
    return f"{result.stdout}\n{result.stderr}"


def _owner_only_mode(path: Path) -> Optional[int]:
    if not path.is_file():
        return None
    return path.stat().st_mode & 0o777
