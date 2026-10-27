"""Bind controller and host walker command templates to the review connection."""

from yoke_core.domain.qa_plan_execution_result_state import QaPlanExecutionError


def _qualify(walker, key, command, prefix):
    qualified = command.replace("yoke ", f"{prefix} ", 1)
    walker[key] = qualified
    walker["prompt"] = str(walker.get("prompt") or "").replace(command, qualified)


def qualify_walkers(walkers, prefix):
    for walker in walkers:
        if not isinstance(walker, dict):
            raise QaPlanExecutionError("QA mission walker is not an object")
        required = ["browser_setup_command", "browser_step_command", "artifact_add_command"]
        if walker.get("location") != "controller":
            required.append("host_command")
        for key in required:
            command = walker.get(key)
            if not isinstance(command, str) or not command.startswith("yoke "):
                raise QaPlanExecutionError(f"QA mission walker lacks a typed {key.replace('_', '-')}")
            _qualify(walker, key, command, prefix)
        for key in ("walk_start_command", "walk_end_command", "host_copy_command"):
            command = walker.get(key)
            if isinstance(command, str) and command.startswith("yoke "):
                _qualify(walker, key, command, prefix)
        commands = walker.get("browser_verify_commands") or []
        for command in commands:
            if not isinstance(command, str) or not command.startswith("yoke "):
                raise QaPlanExecutionError("QA mission walker has an invalid browser verify command")
            walker["prompt"] = str(walker.get("prompt") or "").replace(command, command.replace("yoke ", f"{prefix} ", 1))
        walker["browser_verify_commands"] = [command.replace("yoke ", f"{prefix} ", 1) for command in commands]
