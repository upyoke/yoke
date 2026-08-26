"""Filesystem rollback coverage for failed Machine QA submissions."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pytest

from runtime.api.domain.machine_qa_baseline_group_test_support import (
    baseline_group_request,
    configure_test_machine,
    materialize_installer_campaign,
)
from runtime.api.domain.machine_qa_test_support import FakeHostControl
from yoke_core.domain.handlers.machine_qa_case import (
    handle_case_begin,
    handle_case_submit,
)
from yoke_core.domain.host_control_runner import (
    clear_host_control_factory,
    register_host_control_factory,
)
from yoke_core.domain.machine_qa_local_execution import (
    execute_machine_case_contract,
)


class _SubmissionFailureConnection:
    """Keep the fixture open while injecting one persistence boundary failure."""

    def __init__(
        self,
        inner: Any,
        *,
        fail_second_artifact: bool = False,
        fail_commit: bool = False,
    ) -> None:
        self._inner = inner
        self._fail_second_artifact = fail_second_artifact
        self._fail_commit = fail_commit
        self._artifact_inserts = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def execute(self, sql: str, params: Any = None) -> Any:
        if "INSERT INTO qa_artifacts" in sql:
            self._artifact_inserts += 1
            if self._fail_second_artifact and self._artifact_inserts == 2:
                raise ValueError("artifact persistence unavailable")
        if params is None:
            return self._inner.execute(sql)
        return self._inner.execute(sql, params)

    def commit(self) -> None:
        if self._fail_commit:
            raise ValueError("submission commit unavailable")
        self._inner.commit()

    def close(self) -> None:
        pass


def _prepared_submission(
    test_db: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    item_id: int,
) -> tuple[int, Any]:
    materialize_installer_campaign(test_db, item_id=item_id)
    configure_test_machine(test_db, tmp_path, monkeypatch)
    requirement_id = int(
        test_db.execute(
            "SELECT id FROM qa_requirements "
            "WHERE item_id=%s AND method_id='machine-state-check' "
            "ORDER BY id LIMIT 1",
            (item_id,),
        ).fetchone()[0]
    )
    register_host_control_factory(lambda _material: FakeHostControl())
    try:
        begun = handle_case_begin(
            baseline_group_request(
                requirement_id,
                function="test_machine.case.begin",
            )
        )
        submission = execute_machine_case_contract(
            begun.result_payload["execution"],
        )
    finally:
        clear_host_control_factory()
    result = submission.payload["results"][0]
    result["evidence"]["rollback_capture"] = {
        "key": "rollback-capture",
        "artifact_token": "rollback-capture-token",
    }
    result["artifacts"].append(
        {
            "token": "rollback-capture-token",
            "filename": "rollback-capture.png",
            "content_type": "image/png",
            "content_base64": base64.b64encode(b"captured").decode("ascii"),
        }
    )
    return requirement_id, submission


def _scratch_files(tmp_path: Path) -> set[Path]:
    root = tmp_path / "scratch"
    return (
        {path for path in root.rglob("*") if path.is_file()} if root.exists() else set()
    )


def _assert_submission_rolled_back(
    test_db: Any,
    tmp_path: Path,
    requirement_id: int,
    before_files: set[Path],
) -> None:
    assert _scratch_files(tmp_path) == before_files
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM qa_runs WHERE qa_requirement_id=%s",
            (requirement_id,),
        ).fetchone()[0]
        == 0
    )
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM work_claims WHERE released_at IS NULL "
            "AND target_kind = 'qa_admission'"
        ).fetchone()[0]
        == 1
    )


@pytest.mark.parametrize(
    "failure_mode",
    ["artifact_persistence", "lease_release", "database_commit"],
)
def test_failed_submission_removes_every_new_canonical_artifact(
    test_db: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
) -> None:
    requirement_id, submission = _prepared_submission(
        test_db,
        tmp_path,
        monkeypatch,
        item_id={
            "artifact_persistence": 4320,
            "lease_release": 4321,
            "database_commit": 4322,
        }[failure_mode],
    )
    before_files = _scratch_files(tmp_path)
    if failure_mode == "artifact_persistence":
        connection = _SubmissionFailureConnection(
            test_db,
            fail_second_artifact=True,
        )
        monkeypatch.setattr(
            "yoke_core.domain.db_helpers.connect",
            lambda: connection,
        )
    elif failure_mode == "database_commit":
        connection = _SubmissionFailureConnection(
            test_db,
            fail_commit=True,
        )
        monkeypatch.setattr(
            "yoke_core.domain.db_helpers.connect",
            lambda: connection,
        )
    else:
        monkeypatch.setattr(
            "yoke_core.domain.machine_qa_execution_protocol.release",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                ValueError("lease release unavailable")
            ),
        )

    outcome = handle_case_submit(
        baseline_group_request(
            requirement_id,
            function="test_machine.case.submit",
            payload=submission.payload,
        )
    )

    assert not outcome.primary_success
    _assert_submission_rolled_back(
        test_db,
        tmp_path,
        requirement_id,
        before_files,
    )
