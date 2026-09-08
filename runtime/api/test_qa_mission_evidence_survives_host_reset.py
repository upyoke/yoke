"""Mission evidence must outlive the QA test host it was captured on.

A QA test host's home is restored to its baseline between missions. An
artifact row naming one of its paths therefore outlives its own bytes: the
row survives the restore and the file does not. ``qa.artifact.add`` refuses
every client-local reference and names the byte-carrying recipe, then stores
submitted bytes in S3 or permanent server-local application data.
"""

from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import patch

from runtime.api.fixtures.backlog_inserts import insert_item, insert_qa_requirement
from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.qa_artifact_read_test_support import artifact_read_request
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import machine_config, project_scratch_dir
from yoke_core.domain.handlers.qa_artifact_add import handle_qa_artifact_add
from yoke_core.domain.handlers.qa_artifact_read import handle_qa_artifact_read
from yoke_core.domain.handlers.qa_browser_writes import handle_qa_run_add
from yoke_core.domain.qa_artifact_handle import parse_handle

TEST_HOST_CAPTURE = "/Users/testy/qa-evidence/onboard-skill-run.log"


def _request(payload) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="qa.artifact.add",
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="qa_requirement", qa_requirement_id=10),
        payload=payload,
    )


def _seed_run(conn, *, performed_by: str) -> int:
    insert_item(conn, id=42, title="T", status="reviewing-implementation")
    insert_qa_requirement(
        conn,
        id=10,
        item_id=42,
        qa_kind="plan_case",
        qa_phase="verification",
        blocking_mode="blocking",
        success_policy="{}",
        method_id="agent-mission",
    )
    with patch("yoke_core.domain.qa_events.emit_qa_run_event"):
        outcome = handle_qa_run_add(
            FunctionCallRequest(
                function="qa.run.add",
                actor=ActorContext(actor_id="op", session_id="s-1"),
                target=TargetRef(kind="qa_requirement", qa_requirement_id=10),
                payload={"performed_by": performed_by},
            ),
        )
    assert outcome.primary_success, outcome.error
    return int(outcome.result_payload["qa_run_id"])


def test_mission_handle_naming_the_test_host_is_refused_with_its_recipe() -> None:
    with test_database() as conn:
        run_id = _seed_run(conn, performed_by="agent_mission")
        outcome = handle_qa_artifact_add(
            _request(
                {
                    "run_id": run_id,
                    "artifact_type": "log",
                    "content_type": "text/plain",
                    "artifact_handle": {
                        "backend": "local",
                        "path": TEST_HOST_CAPTURE,
                    },
                }
            ),
        )
        stored = conn.execute(
            "SELECT COUNT(*) FROM qa_artifacts WHERE qa_run_id = %s",
            (run_id,),
        ).fetchone()[0]
    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"
    assert TEST_HOST_CAPTURE in outcome.error.message
    assert "--content-file PATH" in outcome.error.message
    assert int(stored) == 0


def test_mission_s3_handle_is_still_accepted() -> None:
    with test_database() as conn:
        run_id = _seed_run(conn, performed_by="agent_mission")
        with patch(
            "yoke_core.domain.handlers.qa_artifact_presign.resolve_artifacts_bucket",
            return_value=("prod", "yoke-prod-artifacts", None),
        ):
            outcome = handle_qa_artifact_add(
                _request(
                    {
                        "run_id": run_id,
                        "artifact_type": "log",
                        "artifact_handle": {
                            "backend": "s3",
                            "bucket": "yoke-prod-artifacts",
                            "key": "qa-artifacts/yoke/42/1/onboard.log",
                        },
                    }
                ),
            )
    assert outcome.primary_success, outcome.error


def test_mission_s3_handle_outside_tenant_prefix_is_refused() -> None:
    with test_database() as conn:
        run_id = _seed_run(conn, performed_by="agent_mission")
        with patch(
            "yoke_core.domain.handlers.qa_artifact_presign.resolve_artifacts_bucket",
            return_value=("prod", "yoke-prod-artifacts", "tenants/7"),
        ):
            outcome = handle_qa_artifact_add(
                _request(
                    {
                        "run_id": run_id,
                        "artifact_type": "log",
                        "artifact_handle": {
                            "backend": "s3",
                            "bucket": "yoke-prod-artifacts",
                            "key": (
                                f"tenants/8/qa-artifacts/yoke/42/{run_id}/"
                                "onboard.log"
                            ),
                        },
                    }
                ),
            )
        stored = conn.execute(
            "SELECT COUNT(*) FROM qa_artifacts WHERE qa_run_id = %s",
            (run_id,),
        ).fetchone()[0]
    assert not outcome.primary_success
    assert outcome.error.code == "artifact_store_mismatch"
    assert int(stored) == 0


def test_a_non_mission_client_local_handle_is_also_refused() -> None:
    with test_database() as conn:
        run_id = _seed_run(conn, performed_by="worktree_run")
        outcome = handle_qa_artifact_add(
            _request(
                {
                    "run_id": run_id,
                    "artifact_type": "command_output",
                    "artifact_handle": {
                        "backend": "local",
                        "path": "/Users/operator/scratch/command-output.txt",
                    },
                }
            ),
        )
    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"
    assert "--content-file PATH" in outcome.error.message


def test_mission_bytes_stay_readable_after_the_host_source_is_removed(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv(project_scratch_dir.ENV_KEY, str(tmp_path / "scratch"))
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path / "machine-home"))
    monkeypatch.setenv("YOKE_SESSION_ID", "mission-session")
    monkeypatch.setenv("YOKE_RUN_ID", "mission-run")
    host_capture = tmp_path / "host-home" / "qa-evidence" / "onboard.log"
    host_capture.parent.mkdir(parents=True)
    content = b"onboarding apply report\nstage=schema\n"
    host_capture.write_bytes(content)

    with test_database() as conn:
        run_id = _seed_run(conn, performed_by="agent_mission")
        add_outcome = handle_qa_artifact_add(
            _request(
                {
                    "run_id": run_id,
                    "artifact_type": "log",
                    "content_type": "text/plain",
                    "content_base64": base64.b64encode(
                        host_capture.read_bytes()
                    ).decode("ascii"),
                    "filename": "onboard.log",
                }
            ),
        )
        assert add_outcome.primary_success, add_outcome.error
        artifact_id = int(add_outcome.result_payload["qa_artifact_id"])
        row = conn.execute(
            "SELECT artifact_handle FROM qa_artifacts WHERE id = %s",
            (artifact_id,),
        ).fetchone()
        stored_path = Path(parse_handle(row[0])["path"])

        # The host is restored to its baseline; its capture is gone.
        host_capture.unlink()

        read_outcome = handle_qa_artifact_read(
            artifact_read_request(10, artifact_id),
        )

    assert stored_path != host_capture
    assert stored_path.is_relative_to(tmp_path / "machine-home" / "artifacts")
    assert not host_capture.exists()
    assert read_outcome.primary_success, read_outcome.error
    assert read_outcome.result_payload["disposition"] == "ready"
    assert base64.b64decode(read_outcome.result_payload["content_base64"]) == content


def test_a_mission_handle_in_server_artifact_storage_is_accepted(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv(project_scratch_dir.ENV_KEY, str(tmp_path / "scratch"))
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path / "machine-home"))
    monkeypatch.setenv("YOKE_SESSION_ID", "mission-session")
    monkeypatch.setenv("YOKE_RUN_ID", "mission-run")
    from yoke_core.domain.qa_artifacts import artifact_file_path

    with test_database() as conn:
        run_id = _seed_run(conn, performed_by="agent_mission")
        project = conn.execute(
            "SELECT slug FROM projects WHERE id = ("
            "SELECT project_id FROM items WHERE id = 42)",
        ).fetchone()[0]
        server_owned = artifact_file_path(str(project), 42, run_id, "onboard.log")
        server_owned.write_bytes(b"server-owned evidence")
        outcome = handle_qa_artifact_add(
            _request(
                {
                    "run_id": run_id,
                    "artifact_type": "log",
                    "artifact_handle": {
                        "backend": "local",
                        "path": str(server_owned.resolve()),
                    },
                }
            ),
        )
    assert outcome.primary_success, outcome.error


def test_a_mission_handle_with_no_bytes_at_the_allowed_location_is_refused(
    tmp_path,
    monkeypatch,
) -> None:
    """Location is not presence: an empty canonical path carries no evidence."""
    monkeypatch.setenv(project_scratch_dir.ENV_KEY, str(tmp_path / "scratch"))
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path / "machine-home"))
    monkeypatch.setenv("YOKE_SESSION_ID", "mission-session")
    monkeypatch.setenv("YOKE_RUN_ID", "mission-run")
    from yoke_core.domain.qa_artifacts import artifact_file_path

    with test_database() as conn:
        run_id = _seed_run(conn, performed_by="agent_mission")
        project = conn.execute(
            "SELECT slug FROM projects WHERE id = ("
            "SELECT project_id FROM items WHERE id = 42)",
        ).fetchone()[0]
        never_written = artifact_file_path(str(project), 42, run_id, "ghost.log")
        outcome = handle_qa_artifact_add(
            _request(
                {
                    "run_id": run_id,
                    "artifact_type": "log",
                    "artifact_handle": {
                        "backend": "local",
                        "path": str(never_written),
                    },
                }
            ),
        )
        stored = conn.execute(
            "SELECT COUNT(*) FROM qa_artifacts WHERE qa_run_id = %s",
            (run_id,),
        ).fetchone()[0]
    assert not never_written.exists()
    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"
    assert str(never_written) in outcome.error.message
    assert int(stored) == 0
