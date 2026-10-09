"""Public epic dispatch receipts."""

from yoke_contracts.api.function_call import FunctionCallRequest, FunctionCallResponse
from runtime.api.cli.test_yoke_operations_cli_epic_review import (
    _CAPTURED_REQUESTS,
    _stub_ok,
    _run,
    _run_capture,
    _reset_captured as _reset_captured,
)


class TestSimulationUpsert:
    def test_dispatches_epic_level_target(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-task",
            "simulation-upsert",
            "--epic",
            "YOK-501",
            "--phase",
            "plan",
            "--body",
            "SIMULATION: CLEAN",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "workflow_item.epic_task.simulation_upsert"
        assert req.target.kind == "epic_task"
        assert req.target.public_ref == "YOK-501"
        assert req.target.task_num is None
        assert req.payload == {"phase": "plan", "body": "SIMULATION: CLEAN"}

    def test_missing_body_source_returns_two(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-task",
            "simulation-upsert",
            "--epic",
            "YOK-501",
            "--phase",
            "plan",
        )
        assert rc == 2

    def test_verified_receipt_output_and_json(self) -> None:
        ref = f"TST-{109}"
        run_id = 81
        message = f"{ref} simulation plan CLEAN; run {run_id} verified"

        def stub(request):
            return FunctionCallResponse(
                success=True,
                function=request.function,
                version=request.version,
                request_id=request.request_id,
                result={
                    "public_ref": ref,
                    "phase": "plan",
                    "requirement_id": 31,
                    "run_id": run_id,
                    "verdict": "CLEAN",
                    "verified": True,
                    "message": message,
                },
            )

        args = (
            "workflow-item",
            "epic-task",
            "simulation-upsert",
            "--epic",
            ref,
            "--phase",
            "plan",
            "--body",
            f"SIMULATION: CLEAN\nEPIC: {ref}",
        )
        rc, out, _ = _run_capture(stub, *args)
        assert rc == 0 and out == message + "\n"
        rc, out, _ = _run_capture(stub, *args, "--json")
        import json

        assert rc == 0
        result = json.loads(out)["result"]
        assert result["run_id"] == run_id and result["verified"] is True
        assert "body" not in result


class TestSubmissionReceiptGet:
    def test_dispatches_with_watermark(self) -> None:
        rc = _run(
            _stub_ok,
            "workflow-item",
            "epic-task",
            "submission-receipt-get",
            "--epic",
            "YOK-501",
            "--task-num",
            "3",
            "--after-note-count",
            "2",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "workflow_item.epic_task.submission_receipt_get"
        assert req.payload == {"after_note_count": 2}

    def test_prints_receipt_line(self) -> None:
        def stub(request: FunctionCallRequest) -> FunctionCallResponse:
            _CAPTURED_REQUESTS.append(request)
            return FunctionCallResponse(
                success=True,
                function=request.function,
                version=request.version,
                request_id=request.request_id,
                result={
                    "epic_public_ref": "YOK-501",
                    "task_num": 3,
                    "receipt": "PASS|YOK-501|3|4|abc123|2026-01-01|test_plan=PASS",
                },
            )

        rc, out, _err = _run_capture(
            stub,
            "workflow-item",
            "epic-task",
            "submission-receipt-get",
            "--epic",
            "YOK-501",
            "--task-num",
            "3",
        )
        assert rc == 0
        assert out == "PASS|YOK-501|3|4|abc123|2026-01-01|test_plan=PASS\n"


class TestProductionProof:
    def test_fixture_claim_receipts_and_cleanup(self, monkeypatch):
        self._check_proof(monkeypatch, valid=True)

    def test_bad_receipt_is_not_retried_and_fixture_is_cancelled(self, monkeypatch):
        self._check_proof(monkeypatch, valid=False)

    def _check_proof(self, monkeypatch, *, valid):
        import json
        from types import SimpleNamespace
        from runtime.api.tools import check_simulation_receipt as proof

        member = f"TST-{50}"
        fixture = f"TST-{51}"
        calls = []
        monkeypatch.setenv("DEPLOYMENT_MEMBER_REF", member)
        monkeypatch.setattr("sys.argv", ["proof", "--project", "test-project"])

        def execute(args, **kwargs):
            args = args[1:]
            calls.append(args)
            result = {}
            if args[:2] == ["sessions", "identity"]:
                result = {"mode": "dash"}
            elif args[:2] == ["items", "create"] and "--dry-run" not in args:
                result = {"public_ref": fixture}
            elif "simulation-upsert" in args:
                assert kwargs["input"].startswith(f"SIMULATION: CLEAN\nEPIC: {fixture}")
                if "--json" not in args:
                    return SimpleNamespace(
                        returncode=0,
                        stdout=f"{fixture} simulation plan CLEAN; run 7 verified\n",
                        stderr="",
                    )
                result = {
                    "public_ref": fixture,
                    "phase": "plan",
                    "requirement_id": 3,
                    "run_id": 8,
                    "verdict": "CLEAN",
                    "verified": valid,
                }
            elif "simulation-get" in args:
                result = {"body": f"8|{fixture}|plan|CLEAN|body|timestamp|"}
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"success": True, "result": result}),
                stderr="",
            )

        monkeypatch.setattr(proof.subprocess, "run", execute)
        assert proof.main() == (0 if valid else 1)
        creates = [c for c in calls if c[:2] == ["items", "create"]]
        assert len(creates) == 2 and "--dry-run" in creates[0]
        assert "--strategy-doc" in creates[1] and "CURRENT-PLAN" in creates[1]
        claim = next(
            i for i, c in enumerate(calls) if c[:3] == ["claims", "work", "acquire"]
        )
        upserts = [i for i, c in enumerate(calls) if "simulation-upsert" in c]
        assert len(upserts) == 2 and claim < upserts[0]
        cancellations = [c for c in calls if c[:2] == ["items", "cancel"]]
        assert len(cancellations) == 1
        assert cancellations[0][2] == fixture and cancellations[0][-3:-1] == [
            "--ref",
            member,
        ]
