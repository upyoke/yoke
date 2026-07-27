from __future__ import annotations

from pathlib import Path
from typing import Any

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_contracts.machine_config.capability_secrets import (
    TEST_MACHINE_CAPABILITY,
)
from yoke_core.domain.capability_machine_secrets import (
    store_machine_capability_secret,
)
from yoke_core.domain.qa_plan_attachments import (
    attach_plan_to_item,
    materialize_for_item,
)
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.domain.test_machine_capability import (
    replace_test_machine_settings,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


TEST_MACHINE_SETTINGS = {
    "resource_name": "mac-mini-lab",
    "host": "test-mac.local",
    "user": "yoke-test",
    "operating_notes": "",
}
_MACHINE_STATE_CASE_KEYS = frozenset(
    {
        "one-shot-ssh-path-after-full-onboard",
        "path-repair-writes-both-startup-files",
    }
)
_PLAN_CASES = (
    ("default-add-yoke-to-my-path", "fresh-host"),
    ("preview-then-add", "fresh-host"),
    ("skip-path-repair", "fresh-host"),
    ("already-on-path", "shell-preconfigured"),
    ("ssh-only-path-missing", "fresh-host"),
    ("re-run-after-path-fix", "fresh-host"),
    ("one-shot-ssh-command-after-path-repair", "shell-preconfigured"),
    ("one-shot-ssh-path-after-full-onboard", "shell-preconfigured"),
    ("path-repair-writes-both-startup-files", "shell-preconfigured"),
    ("full-curl-bash-in-terminal-app-wizard-left-by-quit", "fresh-host"),
    (
        "re-run-the-installer-from-a-fresh-login-shell-after-path-repair",
        "shell-preconfigured",
    ),
)


class OpenFixtureConnection:
    """Delegate to a fixture connection without letting the handler close it."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def close(self) -> None:
        pass


def configure_test_machine(
    conn: Any,
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    store_machine_capability_secret(
        "yoke",
        TEST_MACHINE_CAPABILITY,
        "ssh_private_key",
        "top-secret",
    )
    replace_test_machine_settings(
        conn,
        project="yoke",
        settings=TEST_MACHINE_SETTINGS,
        base_settings=None,
    )
    monkeypatch.setattr(
        "yoke_core.domain.db_helpers.connect",
        lambda: OpenFixtureConnection(conn),
    )


def materialize_installer_campaign(
    conn: Any,
    *,
    item_id: int,
) -> list[dict[str, Any]]:
    from yoke_core.domain.schema_init_tables import create_governed_tables

    # The composed Postgres fixture predates the shared coordination primitive.
    # Ensure that schema before exercising host-control lease acquisition.
    create_governed_tables(conn)
    plan = create_plan(
        conn,
        project="yoke",
        slug="machine-qa-test-cases",
        name="Machine QA test cases",
        description=(
            "Bounded semantic cases for permanent Machine QA execution tests."
        ),
    )
    replace_plan_cases(
        conn,
        plan_id=plan["id"],
        cases=[
            _plan_case(position, case_key, host_baseline)
            for position, (case_key, host_baseline) in enumerate(
                _PLAN_CASES,
                start=1,
            )
        ],
    )
    insert_item(
        conn,
        id=item_id,
        title="Execute one Test Mac baseline group",
        workflow_id="issue",
        status="implementing",
    )
    plan_id = int(plan["id"])
    attach_plan_to_item(
        conn,
        plan_id=plan_id,
        item_id=item_id,
        transition_id="reviewing-implementation",
    )
    materialize_for_item(
        conn,
        item_id=item_id,
        transition_id="reviewing-implementation",
    )
    return [
        dict(row)
        for row in conn.execute(
            "SELECT id,plan_case_key,host_baseline FROM qa_requirements "
            "WHERE item_id=%s AND plan_id=%s "
            "ORDER BY id",
            (item_id, plan_id),
        ).fetchall()
    ]


def _plan_case(
    position: int,
    case_key: str,
    host_baseline: str,
) -> dict[str, Any]:
    machine_state = case_key in _MACHINE_STATE_CASE_KEYS
    return {
        "case_key": case_key,
        "position": position,
        "method_id": ("machine-state-check" if machine_state else "terminal-check"),
        "instructions": "Exercise one bounded Machine QA host-control case.",
        "expected_outcome": "The registered host-control method passes.",
        "method_config": (
            {"assertions": [{"argv": ["/usr/bin/true"]}]}
            if machine_state
            else _terminal_recipe()
        ),
        "host_baselines": [host_baseline],
        "entry_surface": None if machine_state else "printf done",
        "required_completion": None if machine_state else "complete",
    }


def _terminal_recipe() -> dict[str, Any]:
    return {
        "actions": [{"step": "complete"}],
        "capture_checkpoints": ["complete"],
        "execution_mode": "ssh-command",
        "expected_return_codes": [0],
        "expected_text": ["done"],
        "max_wall_seconds": 60,
        "notes": "Exercise the permanent Machine QA execution contract.",
        "post_checks": ["secret_free"],
        "post_state_assertions": [],
        "setup_operations": [],
        "stage_files": [],
        "start_delay": 0,
        "step_delay": 0,
    }


def baseline_group_request(
    requirement_id: int,
    *,
    function: str = "test_machine.baseline_group_execute",
    payload: dict[str, Any] | None = None,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(
            actor_id="2",
            session_id="session-machine-group",
        ),
        target=TargetRef(
            kind="qa_requirement",
            qa_requirement_id=requirement_id,
        ),
        payload=payload or {},
    )
