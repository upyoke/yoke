"""Docker/Colima-backed local Yoke core launcher."""

from __future__ import annotations

import platform
from pathlib import Path
from typing import Any

from yoke_cli.local_core import docker_plan as dp
from yoke_cli.local_core import launcher_support as support
from yoke_cli.local_core import runtime as lc_runtime
from yoke_cli.local_core import state
from yoke_cli.local_core.runner import CommandRunner, SubprocessRunner

DEFAULT_API_PORT = dp.DEFAULT_API_PORT
DEFAULT_POSTGRES_PORT = dp.DEFAULT_POSTGRES_PORT
Issue = dp.Issue


class LocalCoreLauncher:
    def __init__(
        self,
        *,
        runner: CommandRunner | None = None,
        machine_home: str | None = None,
        system: str | None = None,
    ) -> None:
        self.runner = runner or SubprocessRunner()
        self.machine_home = machine_home
        self.system = system or platform.system().lower()

    def build(
        self,
        *,
        checkout_path: str,
        image: str | None = None,
        api_port: int = DEFAULT_API_PORT,
        postgres_port: int = DEFAULT_POSTGRES_PORT,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        selected_image = image or dp.local_image_for_checkout(checkout_path)
        selected = dp.settings({}, selected_image, api_port, postgres_port)
        plan = dp.build_plan(checkout_path, selected_image)
        base = self._base("build", selected)
        issues, runtime = lc_runtime.preflight(
            self.runner,
            system=self.system,
            check_ports=(),
        )
        issues = [*support.checkout_issues(checkout_path), *issues]
        base["runtime"] = runtime
        if dry_run or issues:
            return dp.planned_payload(base, plan, dry_run, issues)
        ran = lc_runtime.run_plan(self.runner, plan, timeout=1800)
        issues = lc_runtime.issues_from_results(ran)
        if issues:
            return dp.planned_payload(base, plan, False, issues, ran)
        saved = self._save_state(
            **selected,
            source_checkout=str(Path(checkout_path).expanduser().resolve()),
            installed=True,
            last_action="build",
        )
        base.update({
            "ok": True,
            "installed": True,
            "state_path": str(saved),
            "source_checkout": str(Path(checkout_path).expanduser().resolve()),
        })
        return base

    def start(
        self,
        *,
        image: str | None = None,
        api_port: int | None = None,
        postgres_port: int | None = None,
        config_path: str | None = None,
        from_checkout: str | None = None,
        build: bool = False,
        start_colima: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        current = state.load_state(self.machine_home)
        image, image_issues = support.select_image(
            current,
            image=image,
            from_checkout=from_checkout,
            build=build,
            action="start",
        )
        selected = dp.settings(current, image, api_port, postgres_port)
        env_file = str(state.env_path(self.machine_home))
        plan: list[list[str]] = []
        if build and from_checkout and image:
            plan.extend(dp.build_plan(from_checkout, image))
        if selected["image"]:
            plan.extend(dp.start_plan(
                selected["image"],
                env_file=env_file,
                api_port=selected["api_port"],
                postgres_port=selected["postgres_port"],
            ))
        base = self._base("start", selected)
        issues, runtime = lc_runtime.preflight(
            self.runner,
            system=self.system,
            check_ports=(selected["api_port"], selected["postgres_port"]),
            start_colima=start_colima,
        )
        issues = [*image_issues, *issues]
        base["runtime"] = runtime
        if dry_run or issues:
            return dp.planned_payload(base, plan, dry_run, issues)
        env_path = support.write_env(self.machine_home, str(selected["image"]))
        ran = lc_runtime.run_plan(
            self.runner, plan, timeout=1800, allow_missing=True,
        )
        issues = lc_runtime.issues_from_results(ran, allow_missing=True)
        token = support.mint_token(
            self.runner,
            self.machine_home,
            str(selected["image"]),
        )
        if token.returncode != 0:
            issues.append(dp.issue(
                "token_bootstrap_failed",
                "local-core API token bootstrap failed inside the core container",
                "Inspect `yoke core logs`; rebuild with "
                "`yoke core build --checkout PATH` if the local image is stale.",
            ))
        if issues:
            self._save_state(**selected, env_file=str(env_path),
                             installed=True, last_action="start_failed")
            return dp.planned_payload(base, plan, False, issues, [*ran, token])
        config_issue = support.configure_env(
            self.machine_home, selected["api_url"], token.stdout, config_path,
        )
        if config_issue is not None:
            self._save_state(**selected, env_file=str(env_path),
                             installed=True, last_action="start_failed")
            return dp.planned_payload(
                base, plan, False, [config_issue], [*ran, token],
            )
        saved = self._save_state(**selected, env_file=str(env_path),
                                 installed=True, last_action="start")
        status = self.status()
        status.update({"state_path": str(saved), "action": "start"})
        return status

    def status(self) -> dict[str, Any]:
        current = state.load_state(self.machine_home)
        selected = dp.settings(current, None, None, None)
        payload = self._base("status", selected)
        payload["installed"] = bool(current.get("installed"))
        payload["state_path"] = str(state.state_path(self.machine_home))
        issues, runtime = lc_runtime.preflight(
            self.runner, system=self.system, check_ports=(),
        )
        payload["runtime"] = runtime
        if current.get("state_unreadable"):
            issues.append(dp.issue(
                "state_unreadable",
                "local-core state exists but is not readable JSON",
                "Move the state file aside, then rerun "
                "`yoke core build --checkout PATH`.",
            ))
        if not current:
            issues.append(dp.issue(
                "local_core_not_installed",
                "no local-core launcher state exists",
                "Run `yoke core build --checkout PATH --dry-run` "
                "to preview setup.",
            ))
        containers = lc_runtime.container_statuses(self.runner)
        payload["containers"] = containers
        payload["running"] = all(c.get("running") for c in containers.values())
        payload["healthy"] = all(
            c.get("health") in {"healthy", "unknown"} and c.get("running")
            for c in containers.values()
        )
        if payload["installed"] and not payload["running"] and not issues:
            issues.append(dp.issue(
                "containers_not_running",
                "local-core containers are not both running",
                "Run `yoke core start`; use `yoke core logs` for details.",
            ))
        payload["issues"] = [issue.as_dict() for issue in issues]
        payload["ok"] = bool(payload["installed"] and payload["running"]
                             and payload["healthy"] and not issues)
        return payload

    def stop(self, *, dry_run: bool = False) -> dict[str, Any]:
        plan = [["docker", "rm", "-f", dp.API_CONTAINER, dp.DB_CONTAINER]]
        selected = dp.settings(state.load_state(self.machine_home), None, None, None)
        base = self._base("stop", selected)
        issues, runtime = lc_runtime.preflight(
            self.runner, system=self.system, check_ports=(),
        )
        base["runtime"] = runtime
        if dry_run or issues:
            return dp.planned_payload(base, plan, dry_run, issues)
        ran = lc_runtime.run_plan(
            self.runner, plan, timeout=60, allow_missing=True,
        )
        issues = lc_runtime.issues_from_results(ran, allow_missing=True)
        self._mark_last_action("stop" if not issues else "stop_failed")
        return dp.planned_payload(base, plan, False, issues, ran, ok=not issues)

    def logs(self, *, tail: int = 120) -> dict[str, Any]:
        selected = dp.settings(state.load_state(self.machine_home), None, None, None)
        base = self._base("logs", selected)
        issues, runtime = lc_runtime.preflight(
            self.runner, system=self.system, check_ports=(),
        )
        base["runtime"] = runtime
        if issues:
            return dp.planned_payload(base, [], False, issues)
        logs: dict[str, str] = {}
        log_issues: list[Issue] = []
        for label, name in {"api": dp.API_CONTAINER, "postgres": dp.DB_CONTAINER}.items():
            result = self.runner.run(
                ["docker", "logs", "--tail", str(tail), name], timeout=30,
            )
            logs[label] = (result.stdout + result.stderr).strip()
            if result.returncode != 0:
                log_issues.append(dp.issue(
                    "logs_unavailable",
                    f"{name} logs are unavailable",
                    logs[label] or "Start local-core before reading logs.",
                ))
        base.update({"ok": not log_issues, "logs": logs,
                     "issues": [i.as_dict() for i in log_issues]})
        return base

    def upgrade(
        self,
        *,
        image: str | None = None,
        from_checkout: str | None = None,
        build: bool = False,
        config_path: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        current = state.load_state(self.machine_home)
        image, image_issues = support.select_image(
            current,
            image=image,
            from_checkout=from_checkout,
            build=build,
            action="upgrade",
        )
        selected = dp.settings(current, image, None, None)
        env_file = str(state.env_path(self.machine_home))
        base = self._base("upgrade", selected)
        plan: list[list[str]] = []
        if build and from_checkout and image:
            plan.extend(dp.build_plan(from_checkout, image))
        if selected["image"]:
            plan.extend([
                ["docker", "rm", "-f", dp.API_CONTAINER],
                *dp.bootstrap_plan(str(selected["image"]), env_file),
                *dp.api_plan(str(selected["image"]), env_file, selected["api_port"]),
            ])
        issues, runtime = lc_runtime.preflight(
            self.runner, system=self.system, check_ports=(),
        )
        issues = [*image_issues, *issues]
        base["runtime"] = runtime
        if current.get("migration_status") == "running":
            issues.append(dp.issue(
                "migration_in_progress",
                "local-core migration is already marked running",
                "Wait for it to finish, or inspect state before retrying.",
            ))
        if not current.get("installed"):
            issues.append(dp.issue(
                "local_core_not_installed",
                "local-core is not installed yet",
                "Run `yoke core build --checkout PATH` and "
                "`yoke core start` before upgrade.",
            ))
        if dry_run or issues:
            return dp.planned_payload(base, plan, dry_run, issues)
        support.write_env(self.machine_home, str(selected["image"]))
        ran = lc_runtime.run_plan(
            self.runner, plan, timeout=1800, allow_missing=True,
        )
        issues = lc_runtime.issues_from_results(ran, allow_missing=True)
        token = support.mint_token(
            self.runner,
            self.machine_home,
            str(selected["image"]),
        )
        if token.returncode != 0:
            issues.append(dp.issue(
                "token_bootstrap_failed",
                "local-core API token refresh failed inside the core container",
                "Rollback by restarting with the previous image from state.",
            ))
        config_issue = None if issues else support.configure_env(
            self.machine_home, selected["api_url"], token.stdout, config_path,
        )
        if config_issue is not None:
            issues.append(config_issue)
        self._save_state(**selected, installed=True,
                         last_action="upgrade_failed" if issues else "upgrade")
        return dp.planned_payload(
            base, plan, False, issues, [*ran, token], ok=not issues,
        )

    def _base(self, action: str, selected: dict[str, Any]) -> dict[str, Any]:
        return dp.base_payload(
            action,
            image=selected["image"],
            api_port=selected["api_port"],
            postgres_port=selected["postgres_port"],
            system=self.system,
            machine_home=self.machine_home,
        )

    def _save_state(self, **values: Any) -> Any:
        return state.save_state({
            **state.load_state(self.machine_home),
            **values,
            "containers": {"api": dp.API_CONTAINER, "postgres": dp.DB_CONTAINER},
            "network": dp.NETWORK,
            "volumes": {"postgres": dp.DB_VOLUME},
        }, machine_home=self.machine_home)

    def _mark_last_action(self, action: str) -> None:
        current = state.load_state(self.machine_home)
        if current:
            self._save_state(**current, last_action=action)
__all__ = ["DEFAULT_API_PORT", "DEFAULT_POSTGRES_PORT", "Issue", "LocalCoreLauncher"]
