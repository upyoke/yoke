"""Board data replay + value codec — client-tier half of the record/replay seam.

The board renders from one query plan executed at the BoardDB seam
(``query`` / ``query_quiet`` / ``scalar``). This module is the client/render
half that ships everywhere:

- :class:`ReplayBoardDB` serves a render from a recorded payload with no DB
  connection at all. A query the payload does not carry raises
  :class:`BoardDataMissError` loudly: record and replay run the SAME assembly
  code with the SAME query-shaping inputs (scope, board config values, zen
  vision count, repo-root token), so a miss is a parity bug, never a fallback.
- The value codec round-trips Postgres ``Decimal`` / ``date`` / ``datetime``
  results through JSON intact, shared by both record and replay sides.

The recording half (:class:`RecordingBoardDB`, :func:`collect_board_data`) wraps
a live ``yoke_core.board.db.BoardDB`` and stays in ``yoke_core.board.data``,
which re-exports the names below for its existing importers.
"""

from __future__ import annotations

import json
from difflib import SequenceMatcher
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

BOARD_DATA_VERSION = 1


class BoardDataError(RuntimeError):
    """Board data payload could not be produced or consumed."""


class BoardDataMissError(BoardDataError):
    """Replay was asked for a query the recorded payload does not carry."""


# ---------------------------------------------------------------------------
# Value codec — JSON-safe round-trip for DB result values
# ---------------------------------------------------------------------------


def _encode_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return {"__t": "decimal", "v": str(value)}
    if isinstance(value, datetime):
        return {"__t": "datetime", "v": value.isoformat()}
    if isinstance(value, date):
        return {"__t": "date", "v": value.isoformat()}
    raise BoardDataError(
        f"board data cannot encode a {type(value).__name__} value; "
        "extend the codec in yoke_contracts.board.data"
    )


def _decode_value(value: Any) -> Any:
    if isinstance(value, dict) and "__t" in value:
        tag = value.get("__t")
        raw = value.get("v")
        if tag == "decimal":
            return Decimal(str(raw))
        if tag == "datetime":
            return datetime.fromisoformat(str(raw))
        if tag == "date":
            return date.fromisoformat(str(raw))
        raise BoardDataError(f"board data carries unknown value tag {tag!r}")
    return value


def _encode_params(params: Optional[Sequence[Any]]) -> Optional[List[Any]]:
    if params is None:
        return None
    return [_encode_value(p) for p in params]


def entry_key(
    kind: str, sql: str, params: Optional[Sequence[Any]]
) -> Tuple[str, str, str]:
    """Canonical lookup key for one recorded query.

    Params are normalized through the value codec and JSON so the key
    computed from live Python values (record side) matches the key
    computed from JSON-round-tripped values (replay side).
    """
    encoded = _encode_params(params)
    return (kind, sql, json.dumps(encoded, sort_keys=True))


# ---------------------------------------------------------------------------
# Replay handle — the client half
# ---------------------------------------------------------------------------


class ReplayBoardDB:
    """Serve the board render plan from a recorded data payload."""

    record_mode = False

    def __init__(self, lookup: Dict[Tuple[str, str, str], Any]) -> None:
        self._lookup = lookup

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "ReplayBoardDB":
        version = payload.get("version")
        if version != BOARD_DATA_VERSION:
            raise BoardDataError(
                f"board data payload version {version!r} does not match "
                f"this renderer's version {BOARD_DATA_VERSION}; "
                "client and server must run the same board data contract"
            )
        entries = payload.get("entries")
        if not isinstance(entries, list):
            raise BoardDataError("board data payload carries no entries list")
        lookup: Dict[Tuple[str, str, str], Any] = {}
        for entry in entries:
            kind = str(entry.get("kind"))
            sql = str(entry.get("sql"))
            params = entry.get("params")
            key = (kind, sql, json.dumps(params, sort_keys=True))
            if kind == "scalar":
                lookup[key] = _decode_value(entry.get("value"))
            else:
                lookup[key] = [
                    tuple(_decode_value(v) for v in row)
                    for row in (entry.get("rows") or [])
                ]
        return cls(lookup)

    def _serve(self, kind: str, sql: str, params) -> Any:
        key = entry_key(kind, sql, params)
        if key not in self._lookup:
            excerpt = " ".join(sql.split())[:160]
            difference = self._describe_miss(kind, sql, params)
            raise BoardDataMissError(
                f"board data payload has no recorded {kind} result for: "
                f"{excerpt!r} params={params!r} — {difference}; the record "
                "and replay sides ran divergent query plans (parity bug)"
            )
        return self._lookup[key]

    def _describe_miss(self, kind: str, sql: str, params: Any) -> str:
        """Name the query-key component that differs from recorded data."""
        requested_params = json.dumps(params, sort_keys=True)
        candidates = [
            (recorded_sql, recorded_params)
            for recorded_kind, recorded_sql, recorded_params in self._lookup
            if recorded_kind == kind
        ]
        same_sql = [
            value for candidate_sql, value in candidates if candidate_sql == sql
        ]
        if same_sql:
            recorded = [json.loads(value) for value in same_sql]
            return (
                "SQL matched but parameters differed: "
                f"recorded={recorded!r}, replay={params!r}"
            )
        same_params = [
            candidate_sql
            for candidate_sql, value in candidates
            if value == requested_params
        ]
        if same_params:
            closest = max(
                same_params,
                key=lambda candidate: SequenceMatcher(None, candidate, sql).ratio(),
            )
            return self._sql_difference(closest, sql, params_match=True)
        if not candidates:
            return "no recorded query of this kind exists"
        closest_sql, closest_params = max(
            candidates,
            key=lambda candidate: SequenceMatcher(None, candidate[0], sql).ratio(),
        )
        return (
            self._sql_difference(closest_sql, sql, params_match=False)
            + f"; recorded params={json.loads(closest_params)!r}"
        )

    @staticmethod
    def _sql_difference(
        recorded_sql: str, replay_sql: str, *, params_match: bool
    ) -> str:
        limit = min(len(recorded_sql), len(replay_sql))
        offset = next(
            (
                index
                for index in range(limit)
                if recorded_sql[index] != replay_sql[index]
            ),
            limit,
        )
        qualifier = "parameters matched but " if params_match else ""
        return (
            f"{qualifier}SQL differed at character {offset}: "
            f"recorded={recorded_sql[offset : offset + 80]!r}, "
            f"replay={replay_sql[offset : offset + 80]!r}"
        )

    def query(self, sql: str, params: Optional[Sequence[Any]] = None) -> List[Tuple]:
        return list(self._serve("query", sql, params))

    def has_query(self, sql: str, params: Optional[Sequence[Any]] = None) -> bool:
        """Return whether a payload can serve a query without guessing."""
        return entry_key("query", sql, params) in self._lookup

    def query_quiet(
        self, sql: str, params: Optional[Sequence[Any]] = None
    ) -> List[Tuple]:
        return list(self._serve("query_quiet", sql, params))

    def has_query_quiet(self, sql: str, params: Optional[Sequence[Any]] = None) -> bool:
        """Return whether a payload can serve a quiet query."""
        return entry_key("query_quiet", sql, params) in self._lookup

    def scalar(self, sql: str, params: Optional[Sequence[Any]] = None) -> Any:
        return self._serve("scalar", sql, params)

    def close(self) -> None:
        return None

    def __enter__(self) -> "ReplayBoardDB":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        return None
