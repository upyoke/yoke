"""Explicit source-dev/admin setup for a Yoke source checkout."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Mapping

from yoke_cli.config import dev_setup_machine_config
from yoke_cli.config import machine_config
from yoke_cli.config import secrets as machine_secrets
from yoke_cli.config import writer
from yoke_cli.config import source_checkout_activation
from yoke_cli.project_install import source_dev
from yoke_cli.project_install.files import MODE_SOURCE_LINK
from yoke_contracts.machine_config import schema as contract

DEFAULT_ADMIN_ENV = "source-dev-admin"


class DevSetupError(RuntimeError):
    pass


def build_report(
    *,
    checkout: str | Path | None,
    config_path: str | Path | None,
    env_name: str,
    dsn: str | None = None,
    dsn_file: str | Path | None = None,
    dsn_stdin_value: str | None = None,
    apply: bool,
    set_active_env: bool,
    editable_install: bool,
    with_test_postgres: bool = False,
    postgres: Mapping[str, Any] | None = None,
    authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(checkout or Path.cwd()).expanduser().resolve()
    if not source_dev.is_yoke_source_checkout(root):
        raise DevSetupError(
            f"{root} is not a Yoke source checkout; `yoke dev setup` "
            'requires pyproject.toml name = "yoke" and runtime/harness/'
        )
    if with_test_postgres and any(
        value is not None
        for value in (
            dsn,
            dsn_file,
            dsn_stdin_value,
        )
    ):
        raise DevSetupError(
            "--with-test-postgres is mutually exclusive with explicit DSN input"
        )
    if with_test_postgres:
        secret, credential_source = None, _dsn_source(env_name)
    else:
        secret, credential_source = _resolve_dsn(
            env_name,
            dsn=dsn,
            dsn_file=dsn_file,
            dsn_stdin_value=dsn_stdin_value,
        )
    plan = _plan(
        root,
        env_name,
        credential_source,
        set_active_env,
        editable_install,
        with_test_postgres=with_test_postgres,
        postgres=postgres,
        authority=authority,
    )
    report: dict[str, Any] = {
        "operation": "dev.setup",
        "applied": False,
        "checkout": {"path": str(root), "kind": "yoke-source"},
        "plan": plan,
    }
    if not apply:
        report["message"] = "write plan only; rerun with --yes to apply"
        return report

    # Source-link resolves the checkout via PYTHONPATH, so it precedes the
    # editable install, which replaces the product wheel this process uses.
    provisioned = install_source_checkout(root, editable_install=False)
    report["applied"] = True
    report["source_link"] = provisioned["source_link"]
    if with_test_postgres:
        postgres_report = _start_disposable_postgres()
        secret = postgres_report["dsn"]
        report["disposable_postgres"] = postgres_report
    wants_config = (
        secret is not None or bool(postgres) or bool(authority) or set_active_env
    )
    if wants_config:
        configured = _configure_admin_connection(
            env_name=env_name,
            dsn=secret,
            config_path=config_path,
            set_active_env=set_active_env,
            postgres=postgres,
            authority=authority,
        )
        report["admin_connection"] = configured
    # LAST in-process action — nothing yoke_cli-dependent may follow (the adapter
    # only renders the already-built report). run_editable_install_step never
    # raises: a failure lands in the report as {"ok": False, "error": ...}.
    if editable_install:
        report["editable_install"] = run_editable_install_step(root)
    report["message"] = "source-dev/admin setup applied"
    return report


def install_source_checkout(
    root: Path,
    *,
    editable_install: bool = True,
) -> dict[str, Any]:
    """Apply source-link and optionally repoint the tool environment."""
    return source_checkout_activation.install_source_checkout(
        root,
        editable=editable_install,
        error_type=DevSetupError,
    )


def run_editable_install_step(root: Path) -> dict[str, Any]:
    return source_checkout_activation.run_editable_install_step(
        root,
        error_type=DevSetupError,
    )


def dumps_json(report: Mapping[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def render_human(report: Mapping[str, Any]) -> str:
    lines = [
        "Yoke dev setup",
        f"  checkout: {report['checkout']['path']}",
        f"  applied: {str(report['applied']).lower()}",
        "",
        "Write plan:",
    ]
    for step in report["plan"]["steps"]:
        lines.append(f"  - {step['action']}: {step['target']}")
    editable = report.get("editable_install")
    if editable is not None:
        if editable.get("ok"):
            lines.append("  editable install: ok (yoke now runs from the checkout)")
        else:
            lines.append(
                f"  editable install: FAILED — {editable.get('error', 'unknown error')}"
            )
            lines.append(
                "  finish it with: "
                f"yoke dev setup {report['checkout']['path']} --editable-install --yes"
            )
    if not report["applied"]:
        lines.extend(["", "Rerun with --yes to apply this plan."])
    lines.append("")
    return "\n".join(lines)


def _plan(
    root: Path,
    env_name: str,
    credential_source: Mapping[str, str] | None,
    set_active_env: bool,
    editable_install: bool,
    with_test_postgres: bool,
    *,
    postgres: Mapping[str, Any] | None,
    authority: Mapping[str, Any] | None,
) -> dict[str, Any]:
    steps = [
        {"action": "validate-source-checkout", "target": str(root)},
        {"action": "repair-source-links", "target": str(root)},
        {"action": "install-git-hooks", "target": str(root / ".git/hooks")},
    ]
    if editable_install:
        steps.append({"action": "editable-install", "target": str(root)})
    if with_test_postgres:
        steps.append({"action": "start-disposable-postgres", "target": env_name})
    if credential_source:
        steps.append(
            {
                "action": "store-dsn-secret",
                "target": credential_source["path"],
            }
        )
        steps.append({"action": "configure-local-postgres-env", "target": env_name})
    if set_active_env:
        steps.append({"action": "set-active-env", "target": env_name})
    return {
        "owner": "dev.setup",
        "install_mode": MODE_SOURCE_LINK,
        "detected": {"yoke_source_checkout": True},
        "steps": steps,
        "admin_env": env_name,
        "with_test_postgres": with_test_postgres,
        "credential_source": dict(credential_source or {}),
        "postgres": dict(postgres or {}),
        "authority": dict(authority or {}),
    }


def _resolve_dsn(
    env_name: str,
    *,
    dsn: str | None,
    dsn_file: str | Path | None,
    dsn_stdin_value: str | None,
) -> tuple[str | None, dict[str, str] | None]:
    sources = [dsn is not None, dsn_file is not None, dsn_stdin_value is not None]
    if sum(1 for source in sources if source) > 1:
        raise DevSetupError("DSN sources are mutually exclusive")
    if dsn is None and dsn_file is None and dsn_stdin_value is None:
        return None, None
    if dsn_file is not None:
        try:
            value = machine_secrets.read_secret_file(dsn_file, "DSN")
        except machine_secrets.MachineSecretError as exc:
            raise DevSetupError(str(exc)) from exc
    else:
        value = (dsn if dsn is not None else dsn_stdin_value or "").strip()
    if not value:
        raise DevSetupError("DSN is empty")
    return value, _dsn_source(env_name)


def _dsn_source(env_name: str) -> dict[str, str]:
    return {"kind": "dsn_file", "path": str(_planned_secret_path(env_name))}


def _start_disposable_postgres() -> dict[str, Any]:
    try:
        pg_testcluster = importlib.import_module("yoke_core.tools.pg_testcluster")
    except ModuleNotFoundError as exc:
        raise DevSetupError(
            "--with-test-postgres requires the yoke-core engine's disposable "
            "test-cluster tool (yoke_core.tools.pg_testcluster), which is "
            "not importable here; reinstall Yoke or run from a source checkout"
        ) from exc
    rc = pg_testcluster.ensure_started()
    if rc != 0:
        raise DevSetupError(
            f"disposable Postgres cluster failed to start with exit code {rc}"
        )
    return {"ok": True, "dsn": pg_testcluster.dsn()}


def _planned_secret_path(env_name: str) -> Path:
    safe = "".join(
        char if char.isalnum() or char in "._-" else "_" for char in env_name.strip()
    ).strip("._-")
    if not safe:
        raise DevSetupError("--env must include a filesystem-safe label")
    return machine_config.yoke_home() / contract.SECRETS_DIR_NAME / f"{safe}.dsn"


def _configure_admin_connection(
    *,
    env_name: str,
    dsn: str | None,
    config_path: str | Path | None,
    set_active_env: bool,
    postgres: Mapping[str, Any] | None,
    authority: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if dsn is not None:
        result = writer.set_connection(
            env_name,
            transport="local-postgres",
            dsn=dsn,
            prod=False,
            path=config_path,
        )
        should_merge_metadata = bool(postgres) or bool(authority)
    else:
        result = _existing_connection(env_name, config_path)
        should_merge_metadata = (
            bool(postgres)
            or bool(authority)
            or _is_local_postgres(result["connection"])
        )
    if should_merge_metadata:
        result = _merge_connection_metadata(
            env_name,
            config_path,
            postgres=postgres,
            authority=authority,
        )
    if set_active_env:
        writer.set_active_env(env_name, path=config_path)
        result["active_env"] = env_name
    return result


def _existing_connection(
    env_name: str,
    config_path: str | Path | None,
) -> dict[str, Any]:
    cfg_path = machine_config.config_path(config_path)
    payload = machine_config.load_config(cfg_path)
    entry = (payload.get("connections") or {}).get(env_name)
    if not isinstance(entry, Mapping):
        raise DevSetupError(
            f"env {env_name!r} is not configured; provide --dsn, "
            "--dsn-file, or --dsn-stdin to create it"
        )
    return {"env": env_name, "connection": dict(entry), "config": str(cfg_path)}


def _is_local_postgres(entry: Mapping[str, Any]) -> bool:
    transport = str(entry.get("transport") or "").strip()
    return transport in contract.POSTGRES_TRANSPORTS


def _merge_connection_metadata(
    env_name: str,
    config_path: str | Path | None,
    *,
    postgres: Mapping[str, Any] | None,
    authority: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return dev_setup_machine_config.merge_connection_metadata(
        env_name,
        config_path,
        postgres=postgres,
        authority=authority,
        error_type=DevSetupError,
    )


__all__ = [
    "DEFAULT_ADMIN_ENV",
    "DevSetupError",
    "build_report",
    "dumps_json",
    "install_source_checkout",
    "render_human",
    "run_editable_install_step",
]
