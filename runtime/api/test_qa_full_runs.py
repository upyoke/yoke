"""run-add/complete/list/get — QA run lifecycle.

Covers ``cmd_run_add`` (including runner guards for browser and
screenshot kinds and the epic-task review env-var gate),
``cmd_run_complete`` finalisation, listing with optional requirement
filters, and single-run retrieval.
"""

from __future__ import annotations

import json
import os

import pytest

from yoke_core.domain import qa, qa_artifacts
from yoke_core.domain import qa_cli
from runtime.api.qa_full_test_helpers import conn_with_rows, make_qa_db_file
from runtime.api.qa_transition_test_support import add_bound_requirement


@pytest.fixture()
def db_path(tmp_path):
    with make_qa_db_file(tmp_path) as path:
        yield path


def _conn(db_path: str):
    return conn_with_rows(db_path)


class TestRunAdd:
    """cmd_run_add: insert QA runs."""

    def test_add_run(self, db_path, capsys):
        req_id = add_bound_requirement(
            db_path=db_path,
            item_id=100,
            qa_kind="smoke",
            qa_phase="verification",
        )
        capsys.readouterr()
        run_id = qa.cmd_run_add(
            db_path=db_path,
            requirement_id=req_id,
            performed_by="pytest",
            qa_kind="smoke",
            verdict="pass",
        )
        assert run_id >= 1

    def test_cli_run_add_reads_raw_result_file(
        self,
        db_path,
        tmp_path,
        monkeypatch,
        capsys,
    ):
        req_id = add_bound_requirement(
            db_path=db_path,
            item_id=100,
            qa_kind="smoke",
            qa_phase="verification",
        )
        capsys.readouterr()
        raw_file = tmp_path.joinpath("raw.txt")
        raw_file.write_text("multi\nline\nresult", encoding="utf-8")
        monkeypatch.setenv("YOKE_DB", db_path)
        qa_cli.main(
            [
                "run-add",
                "--requirement-id",
                str(req_id),
                "--performed-by",
                "pytest",
                "--qa-kind",
                "smoke",
                "--verdict",
                "pass",
                "--raw-result-file",
                str(raw_file),
                "--head-sha",
                "a" * 40,
            ]
        )
        run_id = int(capsys.readouterr().out.strip())
        conn = _conn(db_path)
        row = conn.execute(
            "SELECT raw_result FROM qa_runs WHERE id=%s",
            (run_id,),
        ).fetchone()
        conn.close()
        payload = json.loads(row["raw_result"])
        assert payload["evidence"] == "multi\nline\nresult"
        assert payload["verification_tree"]["head_sha"] == "a" * 40

    def test_cli_run_add_raw_result_forms_are_exclusive(self) -> None:
        parser = qa_cli.build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(
                [
                    "run-add",
                    "--requirement-id",
                    "1",
                    "--performed-by",
                    "pytest",
                    "--raw-result",
                    "inline",
                    "--raw-result-file",
                    "raw.txt",
                ]
            )

    def test_add_run_without_verdict(self, db_path, capsys):
        """Inserting without verdict (in-progress run)."""
        req_id = add_bound_requirement(
            db_path=db_path,
            item_id=100,
            qa_kind="smoke",
            qa_phase="verification",
        )
        capsys.readouterr()
        run_id = qa.cmd_run_add(
            db_path=db_path,
            requirement_id=req_id,
            performed_by="pytest",
            qa_kind="smoke",
        )
        conn = _conn(db_path)
        row = conn.execute(
            "SELECT verdict, completed_at FROM qa_runs WHERE id=%s", (run_id,)
        ).fetchone()
        conn.close()
        assert row["verdict"] is None
        assert row["completed_at"] is None

    def test_add_run_with_score(self, db_path, capsys):
        req_id = add_bound_requirement(
            db_path=db_path,
            item_id=100,
            qa_kind="smoke",
            qa_phase="verification",
        )
        capsys.readouterr()
        run_id = qa.cmd_run_add(
            db_path=db_path,
            requirement_id=req_id,
            performed_by="pytest",
            qa_kind="smoke",
            verdict="pass",
            score=0.98,
            confidence=0.95,
        )
        conn = _conn(db_path)
        row = conn.execute(
            "SELECT score, confidence FROM qa_runs WHERE id=%s", (run_id,)
        ).fetchone()
        conn.close()
        assert abs(row["score"] - 0.98) < 0.01
        assert abs(row["confidence"] - 0.95) < 0.01

    def test_agent_runner_rejected_for_browser_method(self, db_path, capsys):
        """Agent runner is not allowed for Browser method cases."""
        req_id = add_bound_requirement(
            db_path=db_path,
            item_id=100,
            qa_kind="plan_case",
            qa_phase="verification",
            success_policy=json.dumps(
                {"steps": [{"action": "navigate", "route": "/"}]}
            ),
        )
        conn = _conn(db_path)
        conn.execute(
            "UPDATE qa_requirements SET method_id = %s WHERE id = %s",
            ("browser-check", req_id),
        )
        conn.commit()
        conn.close()
        capsys.readouterr()
        with pytest.raises(SystemExit):
            qa.cmd_run_add(
                db_path=db_path,
                requirement_id=req_id,
                performed_by="agent",
                qa_kind="plan_case",
            )

    def test_agent_runner_rejected_for_screenshot_evidence(self, db_path, capsys):
        """agent runner not allowed for ac_verification with screenshot evidence."""
        req_id = add_bound_requirement(
            db_path=db_path,
            item_id=100,
            qa_kind="ac_verification",
            qa_phase="verification",
            success_policy=json.dumps({"requires_screenshot_evidence": True}),
        )
        capsys.readouterr()
        with pytest.raises(SystemExit):
            qa.cmd_run_add(
                db_path=db_path,
                requirement_id=req_id,
                performed_by="agent",
                qa_kind="ac_verification",
            )

    def test_epic_task_review_guard(self, db_path, capsys):
        """epic-task review runs need YOKE_INTERNAL_EPIC_REVIEW_WRITE."""
        req_id = add_bound_requirement(
            db_path=db_path,
            item_id=None,
            epic_id=50,
            task_num=1,
            qa_kind="implementation_review",
            qa_phase="verification",
        )
        capsys.readouterr()
        # Without env var, should exit
        old_val = os.environ.pop("YOKE_INTERNAL_EPIC_REVIEW_WRITE", None)
        try:
            with pytest.raises(SystemExit):
                qa.cmd_run_add(
                    db_path=db_path,
                    requirement_id=req_id,
                    performed_by="agent",
                    qa_kind="implementation_review",
                )
        finally:
            if old_val is not None:
                os.environ["YOKE_INTERNAL_EPIC_REVIEW_WRITE"] = old_val

    def test_epic_task_review_with_env_var(self, db_path, capsys):
        """With YOKE_INTERNAL_EPIC_REVIEW_WRITE=1, review runs succeed."""
        req_id = add_bound_requirement(
            db_path=db_path,
            item_id=None,
            epic_id=50,
            task_num=1,
            qa_kind="implementation_review",
            qa_phase="verification",
        )
        capsys.readouterr()
        old_val = os.environ.get("YOKE_INTERNAL_EPIC_REVIEW_WRITE")
        os.environ["YOKE_INTERNAL_EPIC_REVIEW_WRITE"] = "1"
        try:
            run_id = qa.cmd_run_add(
                db_path=db_path,
                requirement_id=req_id,
                performed_by="agent",
                qa_kind="implementation_review",
                verdict="pass",
                head_sha="a" * 40,
            )
            assert run_id >= 1
        finally:
            if old_val is None:
                os.environ.pop("YOKE_INTERNAL_EPIC_REVIEW_WRITE", None)
            else:
                os.environ["YOKE_INTERNAL_EPIC_REVIEW_WRITE"] = old_val

    def test_artifact_path_copies_item_artifact_to_canonical_storage(
        self, db_path, capsys, tmp_path, monkeypatch
    ):
        """one-step artifact helper writes item screenshots into canonical storage."""
        req_id = add_bound_requirement(
            db_path=db_path,
            item_id=100,
            qa_kind="plan_case",
            qa_phase="verification",
            success_policy=json.dumps(
                {"steps": [{"action": "screenshot", "capture": True}]}
            ),
        )
        conn = _conn(db_path)
        conn.execute(
            "UPDATE qa_requirements SET method_id = %s WHERE id = %s",
            ("browser-check", req_id),
        )
        conn.commit()
        conn.close()
        capsys.readouterr()

        screenshot = tmp_path / "manual-shot.png"
        screenshot.write_bytes(b"\x89PNG")
        monkeypatch.setattr(
            "yoke_core.api.repo_root.find_repo_root", lambda start=None: tmp_path
        )
        monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))

        run_id = qa.cmd_run_add(
            db_path=db_path,
            requirement_id=req_id,
            performed_by="browser_substrate",
            qa_kind="plan_case",
            verdict="pass",
            artifact_path=str(screenshot),
        )

        conn = _conn(db_path)
        art = conn.execute(
            "SELECT content_type, artifact_handle FROM qa_artifacts WHERE qa_run_id = %s",
            (run_id,),
        ).fetchone()
        conn.close()

        assert art["content_type"] == "image/png"
        persisted = qa_artifacts.artifact_file_path(
            "yoke", 100, run_id, "manual-shot.png"
        )
        handle = json.loads(art["artifact_handle"])
        assert handle["backend"] == "local"
        assert handle["path"] == str(persisted)
        assert persisted.read_bytes() == b"\x89PNG"
