"""Board data recording layer — server half of the record/replay seam.

The render plan executes at the BoardDB seam (``query`` / ``query_quiet`` /
``scalar``). :class:`RecordingBoardDB` wraps a live
:class:`yoke_core.board.db.BoardDB` and records every
``(kind, sql, params) -> result`` the render plan issues;
:func:`collect_board_data` runs the full board assembly against it (discarding
the markdown) and returns a JSON-safe payload — the server half of
``board.data.get``.

The client/render half — :class:`ReplayBoardDB`, the value codec, the payload
version, and the error types — lives in the shipped
:mod:`yoke_contracts.board.data` so the render ships core-free; it is
re-exported here for this module's existing importers.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from yoke_contracts.board.data import (  # noqa: F401
    BOARD_DATA_VERSION,
    BoardDataError,
    BoardDataMissError,
    ReplayBoardDB,
    _decode_value,
    _encode_params,
    _encode_value,
    entry_key,
)


# ---------------------------------------------------------------------------
# Recording wrapper — the server half
# ---------------------------------------------------------------------------


class RecordingBoardDB:
    """BoardDB proxy that records every seam read it serves.

    ``record_mode`` marks the handle for render components that must
    over-collect instead of consulting machine-local caches (the
    activity day-counts cache reads it): every query a client render
    could need has to land in the recorded payload.
    """

    record_mode = True

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._entries: List[Dict[str, Any]] = []
        self._recorded: set = set()

    def query(self, sql: str, params: Optional[Sequence[Any]] = None) -> List[Tuple]:
        return self._record("query", sql, params, self._inner.query)

    def query_quiet(
        self, sql: str, params: Optional[Sequence[Any]] = None
    ) -> List[Tuple]:
        return self._record("query_quiet", sql, params, self._inner.query_quiet)

    def scalar(self, sql: str, params: Optional[Sequence[Any]] = None) -> Any:
        key = entry_key("scalar", sql, params)
        value = self._inner.scalar(sql, params)
        if key not in self._recorded:
            self._recorded.add(key)
            self._entries.append({
                "kind": "scalar",
                "sql": sql,
                "params": _encode_params(params),
                "value": _encode_value(value),
            })
        return value

    def _record(self, kind: str, sql: str, params, run) -> List[Tuple]:
        key = entry_key(kind, sql, params)
        rows = run(sql, params)
        if key not in self._recorded:
            self._recorded.add(key)
            self._entries.append({
                "kind": kind,
                "sql": sql,
                "params": _encode_params(params),
                "rows": [[_encode_value(v) for v in row] for row in rows],
            })
        return rows

    def encoded_entries(self) -> List[Dict[str, Any]]:
        return list(self._entries)


# ---------------------------------------------------------------------------
# Collection — run the render plan against a live DB, keep only the data
# ---------------------------------------------------------------------------


def collect_board_data(
    db: Any,
    *,
    scope: str,
    config: Any,
    repo_root: Optional[str] = None,
    vision_entries: Iterable[Tuple[str, str]] = (),
    visible_project_ids: Optional[Iterable[int]] = None,
) -> Dict[str, Any]:
    """Execute the board's full query plan and return the recorded payload.

    Runs the same ``_assemble`` the client render runs — markdown is
    discarded; only the recorded seam reads matter. ``config``,
    ``repo_root`` and ``vision_entries`` must be the CLIENT's values
    (shipped in the ``board.data.get`` payload) because they shape which
    queries run and with which parameters. Art config and seed shape
    only the discarded text, so collection always uses an empty art
    config and no seed.
    """
    from yoke_contracts.board.art import ArtConfig
    from yoke_contracts.board.project_scope import scoped_project_visibility
    from yoke_contracts.board.renderer import _assemble

    recorder = RecordingBoardDB(db)
    normalized_visible = (
        None if visible_project_ids is None
        else tuple(sorted({int(project_id) for project_id in visible_project_ids}))
    )
    with scoped_project_visibility(normalized_visible):
        _assemble(
            recorder,
            config,
            ArtConfig(),
            scope,
            None,
            repo_root,
            list(vision_entries),
        )
    payload = {
        "version": BOARD_DATA_VERSION,
        "scope": scope,
        "entries": recorder.encoded_entries(),
        "entry_count": len(recorder.encoded_entries()),
    }
    if normalized_visible is not None:
        payload["visible_project_ids"] = list(normalized_visible)
    return payload


__all__ = [
    "BOARD_DATA_VERSION",
    "BoardDataError",
    "BoardDataMissError",
    "RecordingBoardDB",
    "ReplayBoardDB",
    "collect_board_data",
    "entry_key",
]
