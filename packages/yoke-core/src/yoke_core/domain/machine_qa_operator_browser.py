"""The identity browser a Machine QA browser approval runs in.

A test machine keeps one login store: its identity profiles. A recipe whose
browser-approval gate needs the operator's sign-in names the project's
``default_identity`` (its operator identity) here. The recipe exports the
standard ``BROWSER`` variable as ``yoke browser open`` for that identity, so
the installer's approval link opens signed in, and the approval driver's
expired-login refusal names the exact re-authorize command. A POSIX host gets
a shell ``export``; native Windows gets the PowerShell ``$env:`` form.
"""

from __future__ import annotations

import json
import shlex
from typing import Any, Mapping

from yoke_contracts.browser_identity import (
    BrowserIdentityError,
    declared_default_identity,
)
from yoke_core.domain.db_helpers import query_scalar
from yoke_core.domain.machine_qa_operator_gate_contract import (
    gate_needs_desktop_browser,
)
from yoke_core.domain.qa_plan_execution_store import marker

OPERATOR_BROWSER = "operator_browser"


def _browser_settings(conn: Any, project_id: int) -> Mapping[str, Any]:
    if conn is None:
        return {}
    raw = query_scalar(
        conn,
        f"SELECT settings FROM project_capabilities WHERE project_id={marker(conn)} "
        f"AND type={marker(conn)}",
        (int(project_id), "browser-control"),
    )
    settings = json.loads(raw) if isinstance(raw, str) else raw
    return settings if isinstance(settings, Mapping) else {}


def with_operator_browser(
    config: Mapping[str, Any],
    *,
    conn: Any,
    project_id: int,
    project: str,
    test_machine: str,
    os_name: str,
) -> dict[str, Any]:
    """Name the operator identity on a config whose gate approves in a browser."""
    if not any(
        gate_needs_desktop_browser(a) for a in config.get("actions") or ()
    ):
        return dict(config)
    identity = declared_default_identity(_browser_settings(conn, project_id))
    if identity is None:
        raise BrowserIdentityError(
            "machine_operator_identity_undeclared: a browser approval runs in the "
            "test machine's operator identity browser, and project "
            f"{project} names none. Set it with `yoke projects capability-settings "
            f"merge --project {project} --cap-type browser-control --set "
            "default_identity=NAME`, sign it in with `yoke browser authorize "
            f"--project {project} --identity NAME --test-machine {test_machine}`, "
            "then rerun."
        )
    return {
        **config,
        OPERATOR_BROWSER: {
            "project": project,
            "identity": identity,
            "test_machine": test_machine,
            "os": os_name,
        },
    }


def browser_export(config: Mapping[str, Any]) -> str:
    """The entry prefix that routes every link the entry opens to the launcher.

    ``{yoke_bin}`` is the host's resolved Yoke, substituted by each host
    control. The launcher must not see a fixture's ``YOKE_MACHINE_HOME``, so it
    reads the test user's own identity store, the one a reset keeps.
    """
    operator = config.get(OPERATOR_BROWSER)
    if not operator:
        return ""
    if operator.get("os") == "windows":
        return _powershell_browser_export(operator)
    opener = " ".join(
        [
            "env -u YOKE_MACHINE_HOME {yoke_bin} browser open",
            "--project",
            shlex.quote(operator["project"]),
            "--identity",
            shlex.quote(operator["identity"]),
            "%s",
        ]
    )
    return f'export BROWSER="{opener}"; '


def _powershell_browser_export(operator: Mapping[str, Any]) -> str:
    """The native Windows form: PowerShell, with no backslash in ``BROWSER``.

    Yoke splits ``BROWSER`` with POSIX ``shlex``, which drops backslashes, so
    the opener names ``yoke.cmd`` and the prefix puts the resolved Yoke's
    directory first on ``PATH``. PowerShell has no ``env -u``; the entry
    clears ``YOKE_MACHINE_HOME`` before it runs, so the launcher inherits none.
    """
    opener = shlex.join(
        [
            "yoke.cmd",
            "browser",
            "open",
            "--project",
            operator["project"],
            "--identity",
            operator["identity"],
        ]
    )
    literal = "'" + (opener + " %s").replace("'", "''") + "'"
    return (
        "$env:Path=(Split-Path -Parent {yoke_bin})+';'+$env:Path; "
        f"$env:BROWSER={literal}; "
        "Remove-Item Env:YOKE_MACHINE_HOME -ErrorAction SilentlyContinue; "
    )


def reauthorize_command(config: Mapping[str, Any]) -> str:
    operator = config.get(OPERATOR_BROWSER) or {}
    return (
        f"yoke browser authorize --project {operator.get('project', 'PROJECT')} "
        f"--identity {operator.get('identity', 'NAME')} "
        f"--test-machine {operator.get('test_machine', 'TEST_MACHINE')}"
    )


__all__ = [
    "OPERATOR_BROWSER",
    "browser_export",
    "reauthorize_command",
    "with_operator_browser",
]
