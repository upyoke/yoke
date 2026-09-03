"""Report assembly and rendering for ``yoke onboard``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_contracts import harness_unattended_posture
from yoke_contracts import hosting_posture
from yoke_cli.config import onboard_project
from yoke_cli.config import onboard_path_plan
from yoke_cli.config import onboard_post_checkout_plan
from yoke_cli.config import onboard_project_modes
from yoke_cli.config import onboard_session_relay
from yoke_cli.config.onboard_report_render import render_human
from yoke_contracts.machine_config.schema import DEFAULT_TRANSPORT

PROJECT_MODE_MACHINE_ONLY = onboard_project.PROJECT_MODE_MACHINE_ONLY
PROJECT_MODE_LOCAL_CHECKOUT = onboard_project.PROJECT_MODE_LOCAL_CHECKOUT
_PROJECT_ACTION = {
    onboard_project.PROJECT_MODE_CREATE_REPO: "project-create-checkout",
    onboard_project.PROJECT_MODE_CLONE_REMOTE: "project-clone-remote",
    onboard_project.PROJECT_MODE_IMPORT_REMOTE: "project-import-remote",
    onboard_project.PROJECT_MODE_LOCAL_CHECKOUT: "project-onboard-local-checkout",
    onboard_project.PROJECT_MODE_SOURCE_DEV_ADMIN: "project-source-dev-admin",
}


def build_plan(
    cfg_path: Path,
    env_name: str,
    api_url: str,
    credential_source: dict[str, Any],
    source: dict[str, Any],
    mode: str,
    *,
    project_mode: str,
    project_inputs: dict[str, Any],
    machine_github: dict[str, Any],
    hosting_choice: str = hosting_posture.POSTURE_UNDECIDED,
    path_repair: dict[str, Any] | None = None,
    reuse: dict[str, Any] | None = None,
    local_destination: bool = False,
    harness_posture: bool = True,
) -> dict[str, Any]:
    reuse = dict(reuse or {})
    steps = onboard_path_plan.steps(path_repair)
    if not reuse.get("yoke_home"):
        steps.append(
            {
                "action": "create-or-validate-dir",
                "target": str(cfg_path.parent),
            }
        )
    if local_destination:
        # The universe birth replaces the sign-in writes: it records the
        # local connection (DSN reference) itself and verifies idempotently
        # on rerun, so it is always planned.
        steps.append(
            {
                "action": "local-universe-init",
                "target": str(reuse.get("local_universe") or "create"),
            }
        )
    if not reuse.get("active_env"):
        steps.append({"action": "set-active-env", "target": env_name})
    if not local_destination and not reuse.get("connection"):
        steps.append({"action": "set-https-api-url", "target": api_url})
    if not local_destination and not reuse.get("token_reference"):
        steps.append(
            {
                "action": "store-token-reference",
                "target": _credential_target(credential_source),
            }
        )
    if not reuse.get("machine_github"):
        steps.append(
            {
                "action": "machine-github-connection",
                "target": str(machine_github.get("choice") or "skip"),
            }
        )
    # The hosting credential belongs to a project Yoke deploys for, so only
    # those modes plan one. When it is already on this machine the reuse block
    # names it instead — the wizard stores it before Review, the same way the
    # machine GitHub authorization is saved before Review.
    if onboard_project_modes.offers_hosting_credential(project_mode) and not reuse.get(
        "aws_admin"
    ):
        steps.append(
            {
                "action": hosting_posture.HOSTING_POSTURE_ACTION,
                "target": str(
                    hosting_choice or hosting_posture.POSTURE_UNDECIDED
                ),
            }
        )
    # Every destination, because the harness a person opens prompts the same
    # way whether their control plane is local, a team server, or hosted.
    if harness_posture:
        steps.append(harness_unattended_posture.posture_plan_step())
    if not reuse.get("temp_root"):
        steps.append({"action": "create-runtime-dir", "target": "temp_root"})
    if not reuse.get("cache_dir"):
        steps.append({"action": "create-runtime-dir", "target": "cache_dir"})
    steps.extend(onboard_session_relay.plan_steps(local_destination=local_destination))
    if project_mode == PROJECT_MODE_MACHINE_ONLY:
        steps.append({"action": "stop-before-project-or-github", "target": mode})
    else:
        if not reuse.get("project_identity"):
            steps.append(
                {
                    "action": "project-source-choice",
                    "target": _source_choice_target(project_mode, project_inputs),
                }
            )
        if not reuse.get("project_checkout"):
            if not reuse.get("project_clone_checkout"):
                steps.append(
                    {
                        "action": _PROJECT_ACTION.get(project_mode, "project-onboard"),
                        "target": str(project_inputs.get("checkout") or ""),
                    }
                )
            steps.append(
                {
                    "action": "project-checkout-register",
                    "target": str(project_inputs.get("checkout") or ""),
                }
            )
        # Post-checkout work onboard runs once the folder exists: the clone-only
        # remote re-home/fork choreography (clone modes only), the project
        # scaffold install (every mode), and the board-art + initial BOARD.md
        # write (every mode). These name what onboard does AFTER the
        # clone/create so the review screen's "In your project folder" section
        # is not just the clone line.
        steps.extend(
            onboard_post_checkout_plan.post_checkout_steps(
                project_mode, project_inputs, reuse=reuse,
            )
        )
        if not reuse.get("project_github_auth"):
            steps.append(
                {
                    "action": "project-github-auth-choice",
                    # Single source of truth with the apply path — deriving the
                    # target inline here (missing the source-dev case) is what made
                    # the review render "skip" instead of the origin-remote line.
                    "target": onboard_project._github_auth_target(
                        project_inputs,
                        mode=project_mode,
                    ),
                }
            )
    return {
        "config_path": str(cfg_path),
        "active_env": env_name,
        "connection": {
            "transport": DEFAULT_TRANSPORT if local_destination else "https",
            "api_url": api_url,
            "credential_source": credential_source,
        },
        "token_source": source,
        "runtime_paths": {
            "temp_root": str(cfg_path.parent / "tmp"),
            "cache_dir": str(cfg_path.parent / "cache"),
        },
        "path_repair": path_repair,
        "project_mutation": project_mode != PROJECT_MODE_MACHINE_ONLY,
        "machine_github_mutation": bool(machine_github.get("writes_machine_secret"))
        and not bool(reuse.get("machine_github")),
        "github_mutation": bool(
            project_inputs.get("github_adoption") not in (None, "disabled")
        ),
        "reuse": reuse,
        "project": _public_project_inputs(project_inputs) if project_inputs else None,
        "steps": steps,
    }


def _public_project_inputs(project_inputs: dict[str, Any]) -> dict[str, Any]:
    public = dict(project_inputs)
    public["publish"] = _public_publish(public.get("publish"))
    public["clone"] = _public_clone(public.get("clone"))
    return public


def _public_publish(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "owner": str(getattr(value, "owner", "") or ""),
        "name": str(getattr(value, "name", "") or ""),
        "user_login": str(getattr(value, "user_login", "") or ""),
        "api_url": str(getattr(value, "api_url", "") or ""),
        "private": bool(getattr(value, "private", True)),
    }


def _public_clone(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "outcome": str(getattr(value, "outcome", "") or ""),
        "existing_layer_decision": str(
            getattr(value, "existing_layer_decision", "") or ""
        ),
        "keep_upstream": bool(getattr(value, "keep_upstream", True)),
        "fork_api_url": str(getattr(value, "fork_api_url", "") or ""),
        "publish": _public_publish(getattr(value, "publish", None)),
    }


def _source_choice_target(project_mode: str, project_inputs: dict[str, Any]) -> str:
    # The clone outcome refines the review line (make-it-mine / fork /
    # just-clone) without a new plan field; the friendly-line layer parses the
    # "mode:outcome" suffix. Non-clone modes (and a clone with no outcome) keep
    # the bare mode so every other review line renders exactly as before.
    clone = project_inputs.get("clone") if project_inputs else None
    outcome = getattr(clone, "outcome", None)
    if project_mode == onboard_project.PROJECT_MODE_CLONE_REMOTE and outcome:
        return f"{project_mode}:{outcome}"
    return project_mode


def source_choice_target(project_mode: str, project_inputs: dict[str, Any]) -> str:
    return _source_choice_target(project_mode, project_inputs)


def next_steps(cfg_path: Path, project_mode: str) -> list[str]:
    if project_mode == onboard_project.PROJECT_MODE_SOURCE_DEV_ADMIN:
        # Onboard apply already editable-installed packages/* and laid down the
        # source-link dev layer. The editable `yoke` takes effect in a NEW
        # process, so the only remaining step is opening a fresh shell.
        return [
            f"yoke status --config {cfg_path}",
            "Open a new terminal so `yoke` runs from this checkout",
        ]
    if project_mode != PROJECT_MODE_MACHINE_ONLY:
        return [
            f"yoke status --config {cfg_path}",
            "/yoke onboard --run-id <run-id>",
        ]
    return [
        f"yoke status --config {cfg_path}",
        "yoke project install <repo> --project-id <id>",
        "yoke onboard project <repo>",
    ]


def _credential_target(source: dict[str, Any]) -> str:
    return str(source.get("path") or "")


__all__ = ["build_plan", "next_steps", "render_human", "source_choice_target"]
