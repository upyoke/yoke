"""Malformed work-claim release selector coverage."""

from runtime.api.cli.test_yoke_operations_cli_claims import (
    _CAPTURED,
    _run,
    _run_db,
    claims_conn as claims_conn,
)


class TestReleaseSelectorValidation:
    def test_epic_id_without_task_num_rejects(self) -> None:
        rc, _o, err = _run(
            "claims",
            "work",
            "release",
            "--epic",
            "YOK-1872",
            "--reason",
            "partial",
        )
        assert rc == 2
        assert "--epic and --task-num must be provided together" in err
        assert _CAPTURED == []

    def test_task_num_without_epic_id_rejects(self) -> None:
        rc, _o, err = _run(
            "claims",
            "work",
            "release",
            "--task-num",
            "20",
            "--reason",
            "partial",
        )
        assert rc == 2
        assert "--epic and --task-num must be provided together" in err
        assert _CAPTURED == []

    def test_mixed_claim_id_and_epic_task_rejects(self) -> None:
        rc, _o, err = _run(
            "claims",
            "work",
            "release",
            "--claim-id",
            "1",
            "--epic",
            "YOK-1872",
            "--task-num",
            "20",
            "--reason",
            "mixed",
        )
        assert rc == 2
        assert "exactly one" in err
        assert _CAPTURED == []

    def test_mixed_item_and_epic_task_rejects(self) -> None:
        rc, _o, err = _run(
            "claims",
            "work",
            "release",
            "--item",
            "YOK-1872",
            "--epic",
            "YOK-1872",
            "--task-num",
            "20",
            "--reason",
            "mixed",
        )
        assert rc == 2
        assert "exactly one" in err
        assert _CAPTURED == []

    def test_no_selector_rejects(self) -> None:
        rc, _o, err = _run(
            "claims",
            "work",
            "release",
            "--reason",
            "lonely",
        )
        assert rc == 2
        assert "exactly one" in err

    def test_invalid_epic_ref_rejects(self, claims_conn) -> None:
        rc, _o, err = _run_db(
            claims_conn,
            "claims",
            "work",
            "release",
            "--epic",
            "abc",
            "--task-num",
            "20",
            "--reason",
            "bad",
        )
        assert rc == 1
        assert "public_item_ref_required" in err
        assert _CAPTURED == []

    def test_non_integer_task_num_rejects(self, claims_conn) -> None:
        rc, _o, err = _run_db(
            claims_conn,
            "claims",
            "work",
            "release",
            "--epic",
            "YOK-1872",
            "--task-num",
            "x",
            "--reason",
            "bad",
        )
        assert rc == 2
        assert "--task-num must be an integer" in err
        assert _CAPTURED == []

    def test_all_mine_plus_epic_task_rejects(self) -> None:
        rc, _o, err = _run(
            "claims",
            "work",
            "release",
            "--all-mine",
            "--epic",
            "YOK-1872",
            "--task-num",
            "20",
        )
        assert rc == 2
        assert "exactly one" in err
        assert _CAPTURED == []
