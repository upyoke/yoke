"""Native session history clocks and transient remount file boundaries."""

import json
from datetime import timedelta, timezone

import pytest

from yoke_contracts import cursor_remount_expect as remount
from yoke_contracts import session_holdings as holdings
from yoke_contracts.timestamps import InvalidInstant, format_instant, parse_instant
from yoke_contracts.board import sections_sessions_holdings as board
from yoke_core.domain import sessions_holdings_projection as projection

MOMENT = parse_instant("2026-10-09T10:11:12.345678Z")
SHIFTED = MOMENT.astimezone(timezone(timedelta(hours=5, minutes=45)))


def _previous(stamp):
    return {
        "target_key": "work:item:7",
        "holding_kind": "work_claim",
        "target_kind": "item",
        "released_at": stamp,
    }


def test_hold_window_key_uses_instant_identity_across_offset_representations():
    assert holdings.steering_hold_window_key(
        1, MOMENT, SHIFTED
    ) == holdings.steering_hold_window_key(
        "1", SHIFTED.isoformat(), format_instant(MOMENT)
    )
    assert holdings.steering_hold_window_key(1, MOMENT, None)[2] is None


def test_repeated_releases_keep_latest_native_microsecond_and_opaque_fields():
    later = MOMENT + timedelta(microseconds=1)
    result = holdings.group_session_holdings(
        [
            {**_previous(SHIFTED.isoformat()), "evidence": "not a clock"},
            _previous(later),
            _previous(MOMENT),
        ],
        previous_limit=None,
    )
    row = result["previous"][0]
    assert row["released_at"] == later
    assert row["occurrence_count"] == 3 and row["evidence"] == "not a clock"


def test_overlap_pairing_compares_native_microsecond_endpoints():
    candidate = {
        "claim_key": "seat",
        "strategy_doc_slug": "VISION",
        "claim_claimed_at": MOMENT - timedelta(minutes=1),
        "claim_released_at": SHIFTED.isoformat(),
        "doc_registered_at": MOMENT,
        "doc_released_at": MOMENT + timedelta(minutes=1),
    }
    assert holdings.pair_steering_document_slugs([candidate]) == {"seat": ["VISION"]}
    candidate["doc_registered_at"] = MOMENT + timedelta(microseconds=1)
    assert holdings.pair_steering_document_slugs([candidate]) == {}


@pytest.mark.parametrize(
    "value",
    [
        "",
        "released",
        "2026-10-09T10:11:12",
        "2026-02-30T10:11:12Z",
        0,
        MOMENT.replace(tzinfo=None),
    ],
)
def test_invalid_release_clock_refuses_for_first_or_duplicate_observation(value):
    for rows in [[_previous(value)], [_previous(MOMENT), _previous(value)]]:
        with pytest.raises(InvalidInstant):
            holdings.group_session_holdings(rows, previous_limit=None)
    with pytest.raises(InvalidInstant):
        holdings.steering_hold_window_key(1, MOMENT, value)


def test_historical_unknown_release_is_nullable_and_never_becomes_current():
    row = {
        "target_key": "path:session",
        "holding_kind": "path_claim",
        "released_at": None,
        "currently_held": False,
    }
    result = holdings.group_session_holdings([row], previous_limit=None)
    assert result["current"] == [] and result["previous"][0]["released_at"] is None
    assert "currently_held" not in result["previous"][0]
    with pytest.raises(ValueError, match="conflicts"):
        holdings.group_session_holdings(
            [{**row, "currently_held": True, "released_at": MOMENT}],
            previous_limit=None,
        )


def test_board_and_server_path_observations_preserve_unknown_history(monkeypatch):
    monkeypatch.setattr(board, "path_claims_for_items", lambda *_args: [])
    monkeypatch.setattr(
        board,
        "path_claims_for_session",
        lambda *_args: [(1, None, 10, None, None, None, None, 2)],
    )
    monkeypatch.setattr(board, "_process_anchor", lambda *_args: "feed")
    row = board._path_observations(
        object(),
        "session-test",
        {
            holdings.work_holding_key("process", process_key="feed"): {
                "current": False,
                "released_at": None,
            }
        },
        [],
    )[0]
    assert row["currently_held"] is False and row["released_at"] is None
    monkeypatch.setattr(
        projection,
        "_path_rows",
        lambda *_args: [
            {"id": 1, "owner_kind": "item", "owner_item_id": 7, "declared_count": 2}
        ],
    )
    observations = projection._path_observations(
        object(), [], {7: {}}, {7: {"session-test"}}, {7: set()}, {}
    )
    result = holdings.group_session_holdings(
        observations["session-test"], previous_limit=None
    )
    assert result["current"] == [] and result["previous"][0]["released_at"] is None


def test_remount_new_file_clocks_are_canonical_and_reads_native_without_rewrite(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(remount, "utc_now", lambda: SHIFTED)
    assert remount.write_remount_expect(tmp_path, "holder", "conversation")
    path = tmp_path / remount.REMOUNT_EXPECT_DIR_NAME / "holder.json"
    before = path.read_bytes()
    wire = json.loads(before)
    assert wire["written_at"] == wire["holder_activity_at"] == format_instant(MOMENT)
    assert wire["expires_at"] == format_instant(
        MOMENT + timedelta(seconds=remount.REMOUNT_EXPECT_TTL_S)
    )
    assert remount._read_live(path)["expires_at"] == MOMENT + timedelta(
        seconds=remount.REMOUNT_EXPECT_TTL_S
    )
    assert path.read_bytes() == before
    decision = remount.observe_remount_candidate(tmp_path, "holder", "arrival")
    assert decision.outcome == remount.REMOUNT_OBSERVING
    assert json.loads(path.read_bytes())["candidate_seen_at"] == format_instant(MOMENT)


@pytest.mark.parametrize("delta,live", [(-1, False), (0, True), (1, True)])
def test_remount_expiry_preserves_exact_native_cutoff(
    tmp_path, monkeypatch, delta, live
):
    monkeypatch.setattr(remount, "utc_now", lambda: MOMENT)
    path = tmp_path / remount.REMOUNT_EXPECT_DIR_NAME / "holder.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps(
            {
                "expires_at": (MOMENT + timedelta(microseconds=delta))
                .astimezone(SHIFTED.tzinfo)
                .isoformat()
            }
        )
    )
    assert remount.remount_expect_is_live(tmp_path, "holder") is live


@pytest.mark.parametrize(
    "value", [None, "", "2026-10-09T10:11:12", "2026-02-30T10:11:12Z", 0]
)
def test_invalid_remount_clock_refuses_aliasing_and_preserves_receipt(
    tmp_path, monkeypatch, value
):
    monkeypatch.setattr(remount, "utc_now", lambda: MOMENT)
    path = tmp_path / remount.REMOUNT_EXPECT_DIR_NAME / "holder.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"expires_at": value, "evidence": "opaque"}))
    before = path.read_bytes()
    assert not remount.remount_expect_is_live(tmp_path, "holder")
    assert not remount.write_remount_expect(tmp_path, "holder")
    assert not remount.consume_remount_expect(tmp_path, "holder")
    assert (
        remount.observe_remount_candidate(tmp_path, "holder", "arrival").outcome
        == remount.REMOUNT_REFUSED
    )
    assert path.read_bytes() == before
