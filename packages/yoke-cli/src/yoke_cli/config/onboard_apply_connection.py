"""Per-destination connection apply lanes for ``yoke onboard``.

``build_report`` (:mod:`yoke_cli.config.onboard`) delegates its connection
writes here once the plan is confirmed: the local destination births (or
verifies) the machine-local universe in place of any sign-in write, while
the hosted browser flow or explicit server destination resolves a token, optionally validates
identity, and write the https connection. Callers pass their error class
(the :class:`onboard.OnboardError` shape) so this module carries no import
back into the report assembler.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from yoke_cli.config import local_universe_setup
from yoke_cli.config import onboard_apply_progress
from yoke_cli.config import writer
from yoke_cli.config import yoke_token_verify
from yoke_cli.config import secrets as machine_secrets


def apply_local_universe(
    cfg_path: Path,
    env_name: str,
    reuse: Dict[str, Any],
    progress: onboard_apply_progress.ProgressCallback | None,
    report: Dict[str, Any],
    *,
    error_cls: type[Exception],
) -> None:
    """Birth (or verify) the local universe in place of the sign-in writes.

    ``run_local_init`` owns the whole birth: engine binaries, embedded
    cluster, schema bootstrap, org card, human actor, and the ``local``
    machine-config connection. Completing the local flow always leaves
    ``local`` active — an existing connection for another env coexists,
    it is never removed.
    """
    report["identity"] = {"checked": False, "ok": None, "status": "local-universe"}
    universe_target = str(reuse.get("local_universe") or "create")
    onboard_apply_progress.emit(
        progress,
        "local-universe-init",
        universe_target,
        "running",
    )
    try:
        local_report = local_universe_setup.run_local_init(
            config_path=str(cfg_path),
        )
    except local_universe_setup.LocalUniverseSetupError as exc:
        raise error_cls(str(exc)) from exc
    onboard_apply_progress.emit(
        progress,
        "local-universe-init",
        universe_target,
        "done",
    )
    report["local_universe"] = {
        "born": bool(local_report.get("born")),
        "repaired": bool(local_report.get("repaired")),
        "connection_written": bool(
            (local_report.get("connection") or {}).get("written")
        ),
    }
    if not reuse.get("active_env"):
        onboard_apply_progress.emit(progress, "set-active-env", env_name, "running")
        if str(local_report.get("active_env") or "") != env_name:
            writer.set_active_env(env_name, path=cfg_path)
        onboard_apply_progress.emit(progress, "set-active-env", env_name, "done")


def apply_sign_in_connection(
    cfg_path: Path,
    env_name: str,
    api_url: str,
    reuse: Dict[str, Any],
    progress: onboard_apply_progress.ProgressCallback | None,
    report: Dict[str, Any],
    *,
    token: str | None,
    token_file: str | Path | None,
    token_source_kind: str,
    check_identity: bool,
    error_cls: type[Exception],
) -> None:
    """Write the HTTPS connection and its resolved credential reference."""
    secret = _resolve_token_source(
        token=token,
        token_file=token_file,
        source_kind=token_source_kind,
        error_cls=error_cls,
    )
    if check_identity:
        report["identity"] = _validate_identity(api_url, secret, error_cls)
    else:
        report["identity"] = {"checked": False, "ok": None, "status": "skipped"}
    if not (reuse.get("connection") and reuse.get("token_reference")):
        connection_steps = tuple(
            step
            for step in (
                None
                if reuse.get("yoke_home")
                else ("create-or-validate-dir", str(cfg_path.parent)),
                None if reuse.get("connection") else ("set-https-api-url", api_url),
                None if reuse.get("token_reference") else ("store-token-reference", ""),
            )
            if step is not None
        )
        onboard_apply_progress.emit_many(progress, connection_steps, "running")
        writer.set_connection(
            env_name,
            transport="https",
            api_url=api_url,
            token=secret,
            path=cfg_path,
        )
        onboard_apply_progress.emit_many(progress, connection_steps, "done")
    if not reuse.get("active_env"):
        onboard_apply_progress.emit(progress, "set-active-env", env_name, "running")
        writer.set_active_env(env_name, path=cfg_path)
        onboard_apply_progress.emit(progress, "set-active-env", env_name, "done")


def _resolve_token_source(
    *,
    token: str | None,
    token_file: str | Path | None,
    source_kind: str,
    error_cls: type[Exception],
) -> str:
    if token_file is not None:
        try:
            return machine_secrets.read_secret_file(token_file, "token")
        except machine_secrets.MachineSecretError as exc:
            raise error_cls(str(exc)) from exc
    secret = (token or "").strip()
    if not secret:
        label = "stdin" if source_kind == "stdin" else "argument"
        raise error_cls(f"token from {label} is empty")
    return secret


def _validate_identity(
    api_url: str,
    token: str,
    error_cls: type[Exception],
) -> Dict[str, Any]:
    try:
        return yoke_token_verify.verify(api_url, token)
    except yoke_token_verify.YokeTokenVerificationError as exc:
        raise error_cls(str(exc)) from exc


__all__ = ["apply_local_universe", "apply_sign_in_connection"]
