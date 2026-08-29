"""The done transition addresses its discovery scan by public item ref.

A Python ``int`` is ``items.id``; a digit *string* is a project-local
public sequence resolved with ``allow_bare_internal=False``. Handing the
internal id to the scan made it refuse every item whose id was not also a
live sequence — and the closeout recorded step 9 complete anyway, so a
scan that never ran looked exactly like one that found nothing.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from yoke_core.engines import done_transition_discovery
from yoke_core.engines import done_transition_finalize
from yoke_core.engines.done_transition_result import TransitionResult


ITEM_REF = "YOK-2465"
INTERNAL_ID = 2527


@pytest.fixture
def result() -> TransitionResult:
    return TransitionResult(item=ITEM_REF)


class TestApplyDiscoveryScan:
    def test_passes_the_public_ref_through_unchanged(self, result):
        with mock.patch.object(
            done_transition_discovery, "_load_discovery_metadata"
        ), mock.patch(
            "yoke_core.domain.discovery_scan.run_scan", return_value=0
        ) as scan:
            done_transition_discovery._apply_discovery_scan(ITEM_REF, result)

        assert scan.call_args.args[0] == ITEM_REF
        assert "9" in result.steps_completed

    def test_refusal_is_named_not_recorded_as_a_clean_step(self, result, capsys):
        def refuse(public_ref, *, stdout, stderr):
            stderr.write(f"Error: item ref {public_ref!r} not found\n")
            return 2

        with mock.patch(
            "yoke_core.domain.discovery_scan.run_scan", side_effect=refuse
        ):
            outcome = done_transition_discovery._apply_discovery_scan(
                ITEM_REF, result
            )

        assert outcome.is_degraded
        assert outcome.returncode == 2
        assert "9-degraded" in result.steps_completed
        assert "9" not in result.steps_completed
        codes = [w["code"] for w in result.warnings]
        assert codes == ["discovery_scan_degraded"]
        message = result.warnings[0]["message"]
        assert ITEM_REF in message
        assert "/yoke curate" in message
        assert "not found" in message
        assert "discovery scan returned 2" in capsys.readouterr().err


class TestCloseoutRefShape:
    def test_closeout_hands_the_scan_the_public_ref(self, result, tmp_path):
        """The regression: the closeout knows both identities and must pass
        the public one, never ``items.id``."""
        recorded: list[object] = []

        def record(public_ref, res):
            recorded.append(public_ref)
            res.add_step("9")

        fake_engine = SimpleNamespace(
            _apply_discovery_scan=record,
            _rebuild_board_direct=lambda: None,
            _run_git=lambda *a, **k: SimpleNamespace(returncode=0, stdout=""),
            _get_base_branch=lambda *a, **k: "main",
        )
        workflow = SimpleNamespace(stage_ids=["implementing", "done"])

        with mock.patch.object(
            done_transition_finalize.done_transition_github_sync, "apply_step_8"
        ):
            done_transition_finalize._run_closeout(
                fake_engine,
                result,
                item_id=INTERNAL_ID,
                title="done_transition ref shape",
                old_status="reviewing-implementation",
                workflow=workflow,
                repo_root=tmp_path,
                merge_ran=False,
                ref=ITEM_REF,
                prune_lane=None,
            )

        assert recorded == [ITEM_REF]
        assert str(INTERNAL_ID) not in recorded

    def test_step_eight_addresses_the_item_by_internal_id(self, result, tmp_path):
        """Its sibling boundary takes the opposite shape: ``sync_done_item``
        is handed the Python int, which every resolver reads as ``items.id``."""
        fake_engine = SimpleNamespace(
            _apply_discovery_scan=lambda ref, res: res.add_step("9"),
            _rebuild_board_direct=lambda: None,
            _run_git=lambda *a, **k: SimpleNamespace(returncode=0, stdout=""),
            _get_base_branch=lambda *a, **k: "main",
        )
        workflow = SimpleNamespace(stage_ids=["implementing", "done"])

        with mock.patch.object(
            done_transition_finalize.done_transition_github_sync, "apply_step_8"
        ) as step_8:
            done_transition_finalize._run_closeout(
                fake_engine,
                result,
                item_id=INTERNAL_ID,
                title="done_transition ref shape",
                old_status="reviewing-implementation",
                workflow=workflow,
                repo_root=tmp_path,
                merge_ran=False,
                ref=ITEM_REF,
                prune_lane=None,
            )

        assert step_8.call_args.args[0] == INTERNAL_ID
        assert step_8.call_args.kwargs["public_ref"] == ITEM_REF
