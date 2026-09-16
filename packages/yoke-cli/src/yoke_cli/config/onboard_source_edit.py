"""Plan and apply public Yoke-source activation without project authority."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_cli.config import dev_setup, onboard_apply_progress
from yoke_cli.config import project_clone_support
from yoke_cli.config.project_onboard_apply import record_pending_dev_install
from yoke_cli.local_core import LocalCoreLauncher
from yoke_cli.project_install import source_dev


class SourceEditError(RuntimeError):
    """A source checkout could not be cloned, activated, or served."""


def build_report(
    *,
    checkout: str,
    remote_url: str | None,
    destination: str,
    same_host_self_host: bool,
    self_host_directory: str | None,
    config_path: str,
    apply: bool,
    progress: onboard_apply_progress.ProgressCallback | None = None,
) -> dict[str, Any]:
    root = Path(checkout).expanduser().resolve()
    steps = []
    if remote_url and not source_dev.is_yoke_source_checkout(root):
        steps.append({"action": "clone-yoke-source", "target": str(root)})
    steps.append({"action": "activate-yoke-source", "target": str(root)})
    if same_host_self_host:
        steps.append({"action": "run-yoke-server-from-source", "target": str(root)})
    server_effect = (
        "checkout-built server on this machine"
        if same_host_self_host
        else "in-process local engine uses checkout"
        if destination == "local"
        else "remote server stays on its deployed build"
    )
    report: dict[str, Any] = {
        "operation": "onboard.edit-yoke-source",
        "applied": False,
        "checkout": str(root),
        "remote_url": remote_url,
        "server_effect": server_effect,
        "steps": steps,
    }
    if not apply:
        return report
    if remote_url and not source_dev.is_yoke_source_checkout(root):
        with onboard_apply_progress.step(progress, "clone-yoke-source", str(root)):
            root.parent.mkdir(parents=True, exist_ok=True)
            try:
                project_clone_support.clone_with_connected_access(
                    root.parent, root.name, remote_url,
                )
            except Exception as exc:
                raise SourceEditError(
                    f"Could not clone Yoke source. Check the repository URL and access, then retry: {exc}"
                ) from exc
    if not source_dev.is_yoke_source_checkout(root):
        raise SourceEditError(
            f"{root} is not a Yoke source checkout. Choose a checkout or clone whose source contains Yoke's pyproject.toml and runtime/harness directory."
        )
    with onboard_apply_progress.step(progress, "activate-yoke-source", str(root)):
        try:
            report["source_link"] = dev_setup.install_source_checkout(
                root, editable_install=False,
            )
        except dev_setup.DevSetupError as exc:
            raise SourceEditError(str(exc)) from exc
        record_pending_dev_install(root, config_path)
    if same_host_self_host:
        with onboard_apply_progress.step(progress, "run-yoke-server-from-source", str(root)):
            _stop_guided_bundle(self_host_directory)
            core = LocalCoreLauncher().start(
                from_checkout=str(root), build=True, config_path=config_path,
            )
            report["local_core"] = core
            if not core.get("ok"):
                issues = "; ".join(
                    str(issue.get("message") or issue.get("code"))
                    for issue in core.get("issues") or []
                    if isinstance(issue, dict)
                )
                raise SourceEditError(
                    "The checkout was activated, but its local server did not start. "
                    f"Run `yoke core start --from-checkout {root} --build` after fixing: {issues or 'the reported local-core issue'}"
                )
    report["applied"] = True
    return report


def _stop_guided_bundle(directory: str | None) -> None:
    if not directory:
        return
    from yoke_cli.config import onboard_docker_prerequisites
    from yoke_cli.config import onboard_self_host_server

    prerequisites = onboard_docker_prerequisites.check_docker_prerequisites()
    result = onboard_self_host_server.stop_preserving_bundle(
        Path(directory), prerequisites.executable,
    )
    if result.returncode != 0:
        raise SourceEditError(
            "The published-image self-host server could not be stopped before starting the checkout build. "
            f"The bundle remains at {directory}; run `docker compose down` there, then retry."
        )


__all__ = ["SourceEditError", "build_report"]
