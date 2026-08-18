"""Board query-plan changes preserve replay across rolling releases."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Sequence

import pytest

from yoke_contracts.board.art import ArtConfig
from yoke_contracts.board.config import BoardConfig
from yoke_contracts.board.data import (
    BOARD_DATA_VERSION,
    BoardDataMissError,
    ReplayBoardDB,
)
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
06b206651845046691bdbfd6e2ca6999a93775311773e36631bf5321ad4af295
0f23178da19e78d3bacd1bf0e4fa2e87fb119a5152c398211636ed24335b5a81
1fb80d55a756f13e572f4f43d4f38c434b316c83dad7eb9d2d54b26c79a9d053
2667c6f6e5421a9ee3e8d5edf42945612d21e7032516174eed4014a7db71a2de
2ba76271b3db5226a7817cef8d1f15526feb91c3cb2cadd543aafcd1880b4d8b
2c351d32bedd16469d22bc4611c7924e48091fa5fc2063972fe61a8f50f815ba
2dbded61d361220c19dfefc4627b76db1dfc2734596634e1018d1a485c7227ce
32aae4acb5bf243dd1f0dbf1820f8fb44c206b9ee0e7d6e9b977c281de7963ec
342d7fc73c3f08eb5fd8b75a76101510c07850bdfa9a1efe434103fb767d8407
388df0346c04709fd5cd092e47abfc32d9e0794bb25add30702414c223aad086
4916df7985d6f86036b891dbb82bf94ae143bb8c40ea240e2066336264887dfb
53ac0a6f6b84e48bd2b230f8cc3d259646e803b4f12e045f04bb1d0a81b505f9
5df7492669238a2ba6c42e5bd59f7a7da334fbe0b08dd45acaa0fa9076bdd506
677e8066368957ca9b7aa94783c388f26251d30d5efacd23cba6ed503ba10608
6a71beb5ab1ab8bb2de278dc0dff2ddc2e4bb205e35a00b8f0c7617c3d77ac62
8872890a110711e19ce395f0d2a10c8629f0f97c8385333480a66d5b807efaeb
8cca5c55b5b82705f80675cb8f0524a4dc16f7a999a6b93f4da62c75b1d9e02c
9645ea0adec9c48259c0fa9c75530381ed5908bd80dc020d4e84d69818b23ad9
9da9565ebb02052d1e53b61645df040f9cfdc10fdfcbf244a610c46b1388b999
a5b8e2e6c28a0b131487edcc25089d935edb15b787993414e43f1b81367a8f6f
b083377775bfd9bf165eed9e94e42b95cfb7162d59939f68948ba2d682128dde
bfcc6c0acbbe3c45cc6edbe9c402118f148ccacd77fbed147bdf0870263e8d66
caf885a9550262f4169ba5aa4dfcdb43ac0f1ae51b541dddd56735c47ce9c16c
d3cc5713c35f0a9ce4cb197a3a57b18259e67767937378791ed45f55b87147cb
dbd204b1e2bbed21a37cfbcf5371817643208892f56f118952e5f3198f1afa05
e9c376d50d69e371d5257c822b3f691c55a7995f6045fe308024fcf7999ef1fd
ee311ac4b1ac0fa2802b8895c890dda4f07c22276352298703b7badf35cd9148
eed375f6b94c7f4fe5e90e4f8df756179d46a25a4e6fcbd44c15c489ff7d619b
ff9b9689e8887c799d6b246f206b02677604d504734870397266c62e69e0ba83
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
        str(entry["sql"]),
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
