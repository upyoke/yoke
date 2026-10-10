"""Record board query coverage against one live render snapshot."""

from typing import Any, Iterable, Sequence
from yoke_core.board.data import RecordingBoardDB, entry_key

QueryIdentity = tuple[str, str, str]


class CoverageRecordingBoardDB(RecordingBoardDB):
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

    def has_scalar(self, sql: str, params: Sequence[Any] | None = None) -> bool:
        return self._probe("scalar", sql, params)

    def _probe(
        self,
        kind: str,
        sql: str,
        params: Sequence[Any] | None,
    ) -> bool:
        identity = entry_key(kind, sql, params)
        self.coverage_probes.add(identity)
        return identity not in self._unavailable
