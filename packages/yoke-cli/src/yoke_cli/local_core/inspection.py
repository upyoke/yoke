"""Status, logs, and shutdown operations for the local-core launcher."""

from typing import Any
from yoke_cli.local_core import docker_plan as dp, runtime as lc_runtime, state

Issue = dp.Issue


class LocalCoreInspection:
    def status(self) -> dict[str, Any]:
        current = state.load_state(self.machine_home)
        selected = dp.settings(current, None, None, None)
        payload = self._base("status", selected)
        payload["installed"] = bool(current.get("installed"))
        payload["state_path"] = str(state.state_path(self.machine_home))
        issues, runtime = lc_runtime.preflight(
            self.runner,
            system=self.system,
            check_ports=(),
        )
        payload["runtime"] = runtime
        if current.get("state_unreadable"):
            issues.append(
                dp.issue(
                    "state_unreadable",
                    "local-core state exists but is not readable JSON",
                    "Move the state file aside, then rerun "
                    "`yoke core build --checkout PATH`.",
                )
            )
        if not current:
            issues.append(
                dp.issue(
                    "local_core_not_installed",
                    "no local-core launcher state exists",
                    "Run `yoke core build --checkout PATH --dry-run` to preview setup.",
                )
            )
        containers = lc_runtime.container_statuses(self.runner)
        payload["containers"] = containers
        payload["running"] = all(c.get("running") for c in containers.values())
        payload["healthy"] = all(
            c.get("health") in {"healthy", "unknown"} and c.get("running")
            for c in containers.values()
        )
        if payload["installed"] and not payload["running"] and not issues:
            issues.append(
                dp.issue(
                    "containers_not_running",
                    "local-core containers are not both running",
                    "Run `yoke core start`; use `yoke core logs` for details.",
                )
            )
        payload["issues"] = [issue.as_dict() for issue in issues]
        payload["ok"] = bool(
            payload["installed"]
            and payload["running"]
            and payload["healthy"]
            and not issues
        )
        return payload

    def stop(self, *, dry_run: bool = False) -> dict[str, Any]:
        plan = [["docker", "rm", "-f", dp.API_CONTAINER, dp.DB_CONTAINER]]
        selected = dp.settings(state.load_state(self.machine_home), None, None, None)
        base = self._base("stop", selected)
        issues, runtime = lc_runtime.preflight(
            self.runner,
            system=self.system,
            check_ports=(),
        )
        base["runtime"] = runtime
        if dry_run or issues:
            return dp.planned_payload(base, plan, dry_run, issues)
        ran = lc_runtime.run_plan(
            self.runner,
            plan,
            timeout=60,
            allow_missing=True,
        )
        issues = lc_runtime.issues_from_results(ran, allow_missing=True)
        self._mark_last_action("stop" if not issues else "stop_failed")
        return dp.planned_payload(base, plan, False, issues, ran, ok=not issues)

    def logs(self, *, tail: int = 120) -> dict[str, Any]:
        selected = dp.settings(state.load_state(self.machine_home), None, None, None)
        base = self._base("logs", selected)
        issues, runtime = lc_runtime.preflight(
            self.runner,
            system=self.system,
            check_ports=(),
        )
        base["runtime"] = runtime
        if issues:
            return dp.planned_payload(base, [], False, issues)
        logs: dict[str, str] = {}
        log_issues: list[Issue] = []
        for label, name in {
            "api": dp.API_CONTAINER,
            "postgres": dp.DB_CONTAINER,
        }.items():
            result = self.runner.run(
                ["docker", "logs", "--tail", str(tail), name],
                timeout=30,
            )
            logs[label] = (result.stdout + result.stderr).strip()
            if result.returncode != 0:
                log_issues.append(
                    dp.issue(
                        "logs_unavailable",
                        f"{name} logs are unavailable",
                        logs[label] or "Start local-core before reading logs.",
                    )
                )
        base.update(
            {
                "ok": not log_issues,
                "logs": logs,
                "issues": [i.as_dict() for i in log_issues],
            }
        )
        return base
