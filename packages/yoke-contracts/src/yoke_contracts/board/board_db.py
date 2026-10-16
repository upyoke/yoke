"""Read-only database interface for server-side board collectors."""

from __future__ import annotations

from typing import Any, List, Optional, Protocol, Sequence, Tuple


class BoardDBLike(Protocol):
    """The query surface board collectors use."""

    def query(
        self, sql: str, params: Optional[Sequence[Any]] = None
    ) -> List[Tuple]: ...

    def query_quiet(
        self, sql: str, params: Optional[Sequence[Any]] = None
    ) -> List[Tuple]: ...

    def scalar(self, sql: str, params: Optional[Sequence[Any]] = None) -> Any: ...
