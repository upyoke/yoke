"""Board query-plan changes preserve replay across rolling releases."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Sequence

import pytest

from yoke_contracts.board.art import ArtConfig
from yoke_contracts.board.config import BoardConfig
from yoke_contracts.board.data import (
    BOARD_DATA_VERSION,
    BoardDataMissError,
    ReplayBoardDB,
)
from yoke_contracts.board.query_key import canonicalize_sql
from yoke_contracts.board.sql import days_ago_expr, days_ago_text_expr
from yoke_core.board.data import RecordingBoardDB, entry_key
from yoke_core.board.db import BoardDB
from yoke_core.board.renderer import _assemble
from runtime.api.board.tests.helpers import insert_item, insert_task
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


QueryIdentity = tuple[str, str, str]

# This is the frozen version-1 query plan, excluding reads that already carry
# a payload-coverage probe. Do not refresh it for an ordinary query change:
# add a has_query/has_query_quiet fallback instead. A data-version bump is the
# boundary that may deliberately replace this baseline.
_UNGUARDED_V1_FINGERPRINTS = frozenset(
    """
0fa286506e2c42a3fa9e391401af38e616135903aa1eab25b4cce61474f5a228
24f55081286881f2007f337d28690652586bf2e8c0e46251e813a4bc11a7fa8d
2ba76271b3db5226a7817cef8d1f15526feb91c3cb2cadd543aafcd1880b4d8b
2c351d32bedd16469d22bc4611c7924e48091fa5fc2063972fe61a8f50f815ba
2dbded61d361220c19dfefc4627b76db1dfc2734596634e1018d1a485c7227ce
32aae4acb5bf243dd1f0dbf1820f8fb44c206b9ee0e7d6e9b977c281de7963ec
34a2afca3a54b502cbb9322627f65b4b92a98e2429711b9a20cbd50f89a119c2
3a8d140ffd82aa9613fd8acf7a9961991726d08a77030edb4bc33748e845cdcb
4588ce7c54e1fba7d80522fc64a255c6e691293db0f31f6ee31a8efde2d936ab
47fe30fae3bf52b028b13e2e5b5c5baace81c5b156e377ede2b9738ab49c1b7a
4916df7985d6f86036b891dbb82bf94ae143bb8c40ea240e2066336264887dfb
53ac0a6f6b84e48bd2b230f8cc3d259646e803b4f12e045f04bb1d0a81b505f9
677e8066368957ca9b7aa94783c388f26251d30d5efacd23cba6ed503ba10608
68657c2f13474585932cec1897d1dc14bb812edd23980dda459b1f03062c5311
6b54b2e489e57f6cc7e7b735fa2aa0c475c5145c3f3865a4fa71040a398dea84
71804ce12c6ca0bde46586ebd1b8e397e5d4a0f843114f441de4c6582551e2df
73d31ee36f2ba32b9017d64cc7dbc13015316bf56ac20a376f31312352f05260
7b32b026adf888267daa3dfa1bfec59a73568ff6d4b31165e9c8e085ba3067b7
8e21fbb51b5e1b46db09f8dcd734c696c8dbb9a9e1e30eea4479e3079bb8b35c
96da71e5db747a45323b66c96c2ec6aaae291efe00eef06ac75706eefbd78334
a1d844952f3952ef7750861612dc77efd1d2f01a9e611efaf2d01967d30874ed
a290bbaa0c634437fe063b7de2eb6ae3923b301d3d7acf31bc0fa41c0cd969b6
a5b8e2e6c28a0b131487edcc25089d935edb15b787993414e43f1b81367a8f6f
bc5e196a6811af1eb718cfa0980475f2c1e38dc5e286b3daed6e6b4c193f8007
bfcc6c0acbbe3c45cc6edbe9c402118f148ccacd77fbed147bdf0870263e8d66
c7501216013d2ab7f3c27ce59ff5151a951cfb88f1c0e54aae07b98bbdc450f1
da8bb3d8677b6e513e56094ab9010d8a1468a68b71779a5662832f7a5fcad962
""".split()
)
_REPO_ROOT_TOKEN = "/Users/testy/code/yoke"
_VISION_ENTRIES = [("1mo", "autonomous"), ("6mo", "fleet")]


class _CoverageRecordingBoardDB(RecordingBoardDB):
    """Record coverage probes while exercising the real recording seam."""

    def __init__(
        self,
        inner: Any,
        *,
        unavailable: Iterable[QueryIdentity] = (),
    ) -> None:
        super().__init__(inner)
        self.coverage_probes: set[QueryIdentity] = set()
        self._unavailable = set(unavailable)

    def has_query(
        self,
        sql: str,
        params: Sequence[Any] | None = None,
    ) -> bool:
        return self._probe("query", sql, params)

    def has_query_quiet(
        self,
        sql: str,
        params: Sequence[Any] | None = None,
    ) -> bool:
        return self._probe("query_quiet", sql, params)

    def _probe(
        self,
        kind: str,
        sql: str,
        params: Sequence[Any] | None,
    ) -> bool:
        identity = entry_key(kind, sql, params)
        self.coverage_probes.add(identity)
        return identity not in self._unavailable


@pytest.fixture
def representative_board_db(tmp_path):
    """Full schema with rows that open the render plan's conditional paths."""

    with init_test_db(tmp_path) as db_path:
        with BoardDB(db_path) as db:
            insert_item(db, 8101, status="implementing")
            insert_item(db, 8102, workflow_id="epic", status="implementing")
            insert_task(db, 8102, 1, "Implementation", status="done")

        conn = connect_test_db(db_path)
        try:
            conn.execute(
                "INSERT INTO project_structure "
                "(id, project_id, family, attachment_value, attachment_kind, "
                "created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    8101,
                    1,
                    "architecture_model",
                    "AGENTS.md",
                    "file",
                    "2026-08-18T12:00:00Z",
                    "2026-08-18T12:00:00Z",
                ),
            )
            conn.execute(
                "INSERT INTO harness_sessions "
                "(session_id, executor, provider, model, workspace, project_id, "
                "mode, offered_at, last_heartbeat, current_item_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    "coverage-session",
                    "codex",
                    "openai",
                    "contract-test",
                    _REPO_ROOT_TOKEN,
                    1,
                    "dash",
                    "2026-08-18T12:00:00Z",
                    "2026-08-18T12:01:00Z",
                    "8101",
                ),
            )
            conn.execute(
                "INSERT INTO work_claims "
                "(id, session_id, target_kind, item_id, claimed_at, last_heartbeat) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    8101,
                    "coverage-session",
                    "item",
                    8101,
                    "2026-08-18T12:00:00Z",
                    "2026-08-18T12:01:00Z",
                ),
            )
            conn.commit()
        finally:
            conn.close()
        yield db_path


def _config() -> BoardConfig:
    return BoardConfig(
        dashboard_velocity_meter=True,
        dashboard_sessions_scope="all",
        timeline_widget="always",
        timeline_scope="all",
        art_override="frontier",
    )


def _record_plan(
    db_path: str,
    *,
    unavailable: Iterable[QueryIdentity] = (),
) -> _CoverageRecordingBoardDB:
    with BoardDB(db_path) as live:
        recorder = _CoverageRecordingBoardDB(live, unavailable=unavailable)
        rendered = _assemble(
            recorder,
            _config(),
            ArtConfig(),
            "all",
            7,
            _REPO_ROOT_TOKEN,
            list(_VISION_ENTRIES),
        )
    assert rendered
    return recorder


def _entry_identity(entry: dict[str, Any]) -> QueryIdentity:
    return (
        str(entry["kind"]),
        canonicalize_sql(str(entry["sql"])),
        json.dumps(entry.get("params"), sort_keys=True),
    )


def _query_fingerprint(identity: QueryIdentity) -> str:
    encoded = json.dumps(identity, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _describe(identities: Iterable[QueryIdentity]) -> str:
    lines = []
    for kind, sql, params in sorted(identities):
        lines.append(f"{kind}: {' '.join(sql.split())} params={params}")
    return "\n".join(lines)


def _payload(recorder: _CoverageRecordingBoardDB) -> dict[str, Any]:
    return json.loads(
        json.dumps(
            {
                "version": BOARD_DATA_VERSION,
                "engine_version": "contract-test",
                "entries": recorder.encoded_entries(),
            }
        )
    )


def test_board_query_changes_require_a_replay_fallback(
    representative_board_db,
) -> None:
    primary = _record_plan(representative_board_db)
    issued = {_entry_identity(entry) for entry in primary.encoded_entries()}
    unguarded = issued - primary.coverage_probes
    uncovered = {
        identity
        for identity in unguarded
        if _query_fingerprint(identity) not in _UNGUARDED_V1_FINGERPRINTS
    }

    assert not uncovered, (
        "The board render plan issued a new or changed read without a payload-"
        "coverage probe. Guard it with has_query/has_query_quiet and serve a "
        "recorded fallback; do not refresh the version-1 baseline. After merge, "
        "run `yoke board rebuild --force --json` and check `result.status`.\n\n"
        + _describe(uncovered)
        + "\n\nCurrent unguarded fingerprints:\n"
        + repr(sorted(_query_fingerprint(identity) for identity in unguarded))
    )

    for identity in sorted(primary.coverage_probes):
        fallback = _record_plan(
            representative_board_db,
            unavailable={identity},
        )
        fallback_issued = {
            _entry_identity(entry) for entry in fallback.encoded_entries()
        }
        assert identity not in fallback_issued, (
            "A coverage probe reported the read unavailable, but the fallback "
            f"still issued it:\n{_describe([identity])}"
        )

        replay = ReplayBoardDB.from_payload(_payload(fallback))
        try:
            _assemble(
                replay,
                _config(),
                ArtConfig(),
                "all",
                7,
                _REPO_ROOT_TOKEN,
                list(_VISION_ENTRIES),
            )
        except BoardDataMissError as exc:
            pytest.fail(
                "The coverage probe does not lead to a replay-safe fallback for "
                f"{_describe([identity])}: {exc}"
            )


_BOARD_WINDOWS = (120, 365)
_BOUNDED_OVERVIEW_WINDOWS = (30, 90, 120, 300, 365)
_DAYS_AGO_CALL = re.compile(r"days_ago_(?:text_)?expr\(([^)]+)\)")
_BOARD_ROOT = Path("packages/yoke-contracts/src/yoke_contracts/board")
_MOMENTUM_SIGNALS = Path(
    "packages/yoke-core/src/yoke_core/domain/board_momentum_signals.py"
)


@pytest.mark.parametrize("days", _BOUNDED_OVERVIEW_WINDOWS)
def test_bounded_windows_bake_a_stable_interval(days: int) -> None:
    sql = days_ago_text_expr(days)
    assert f"make_interval(days => {days})" in sql


def test_days_ago_refuses_a_non_positive_window() -> None:
    with pytest.raises(ValueError, match="positive"):
        days_ago_expr(0)
    with pytest.raises(ValueError, match="positive"):
        days_ago_text_expr(-1)


def test_days_ago_callers_do_not_pass_project_age() -> None:
    paths = list(_BOARD_ROOT.glob("*.py")) + [_MOMENTUM_SIGNALS]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for match in _DAYS_AGO_CALL.finditer(text):
            argument = match.group(1).lower()
            assert "project" not in argument, path
            assert "age" not in argument, path


def test_recorded_board_plan_covers_each_board_window(
    representative_board_db,
) -> None:
    recorder = _record_plan(representative_board_db)
    sql_text = "\n".join(str(entry["sql"]) for entry in recorder.encoded_entries())
    for days in _BOARD_WINDOWS:
        assert f"make_interval(days => {days})" in sql_text, days


def test_board_fingerprints_do_not_roll_with_the_calendar(
    representative_board_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from yoke_contracts.board import widgets_activity

    def fingerprints(day: date) -> set[str]:
        monkeypatch.setattr(widgets_activity, "_utc_today", lambda: day)
        recorder = _record_plan(representative_board_db)
        issued = {_entry_identity(entry) for entry in recorder.encoded_entries()}
        return {_query_fingerprint(identity) for identity in issued}

    january = fingerprints(date(2026, 1, 1))
    december = fingerprints(date(2026, 12, 31))
    assert january == december
    assert january
