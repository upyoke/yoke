"""Bookkeeping uses only validated exact identity and never repeats deployment."""

from argparse import Namespace
import json

import pytest

from runtime.api.fixtures.hosted_promotion import envelope, payload
from runtime.api.tools import record_hosted_promotion as tool
from yoke_core.domain.hosted_promotion_receipt import PromotionReceiptRefused


def arguments(**changes):
    return Namespace(
        deployment_run_id="owned-run",
        promotion_run_id="123",
        environment="stage",
        product_sha="a" * 40,
        consumer_sha="c" * 40,
        version=f"0.1.1+launch.{461}",
        project="platform",
        **changes,
    )


@pytest.mark.parametrize("pushed", [True, False])
def test_writer_uses_exact_commit_and_retains_receipt_for_retry(
    tmp_path, monkeypatch, pushed
):
    proof = envelope(payload(pin_pushed=pushed))
    monkeypatch.setattr(tool, "read_receipt", lambda *a: proof)
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return Namespace(returncode=0, stdout="recorded", stderr="")

    monkeypatch.setattr(tool.subprocess, "run", run)
    assert tool.record(arguments()) == (0, "recorded")
    assert tool.record(arguments()) == (0, "recorded")
    assert calls[0] == calls[1]
    assert calls[0][calls[0].index("--commit") + 1] == "b" * 40
    path = calls[0][calls[0].index("--promotion-receipt-file") + 1]
    assert json.loads(open(path).read()) == proof
    assert all("trigger" not in command for command in calls)


def test_wrong_environment_or_version_never_writes(monkeypatch):
    monkeypatch.setattr(
        tool, "read_receipt", lambda *a: envelope(payload(target_environment="prod"))
    )
    monkeypatch.setattr(
        tool.subprocess, "run", lambda *a, **k: pytest.fail("unproven identity wrote")
    )
    with pytest.raises(
        PromotionReceiptRefused, match="promotion_receipt_identity_mismatch"
    ):
        tool.record(arguments())


def test_old_server_reader_gets_bounded_readiness_without_dispatch(monkeypatch):
    monkeypatch.setattr(tool, "bind_consumer_authority", lambda: "")
    responses = iter(
        [
            (
                1,
                json.dumps(
                    {
                        "success": True,
                        "result": {
                            "state": "failed",
                            "message": "workflow_receipt_reader_unavailable",
                        },
                    }
                ),
                "",
            ),
            (
                0,
                json.dumps(
                    {
                        "success": True,
                        "result": {"state": "success", "receipt": envelope()},
                    }
                ),
                "",
            ),
        ]
    )
    calls = []
    monkeypatch.setattr(
        tool, "_yoke", lambda args, **k: (calls.append(args), next(responses))[1]
    )
    monkeypatch.setattr(tool.time, "sleep", lambda *a: None)
    assert tool.read_receipt("123") == envelope()
    assert len(calls) == 2
    assert all(args[:2] == ["github-actions", "wait-run"] for args in calls)


def test_absent_receipt_refuses_and_never_redelivers(monkeypatch):
    monkeypatch.setattr(tool, "bind_consumer_authority", lambda: "")
    monkeypatch.setattr(
        tool,
        "_yoke",
        lambda *a, **k: (
            1,
            json.dumps(
                {
                    "success": True,
                    "result": {
                        "state": "failed",
                        "message": "workflow_receipt_missing",
                    },
                }
            ),
            "",
        ),
    )
    with pytest.raises(PromotionReceiptRefused, match="promotion_receipt_unavailable"):
        tool.read_receipt("123")
