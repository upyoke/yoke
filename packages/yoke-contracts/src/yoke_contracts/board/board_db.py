"""Structural DB interface the board render depends on.

The render is payload-driven: on the client it runs against ``ReplayBoardDB``
(no DB); during server-side data collection it runs against ``RecordingBoardDB``
(live, in ``yoke_core``). Both satisfy this Protocol, so render modules type
their ``db`` parameter against it and never import the psycopg-backed
``BoardDB`` — keeping this tier core-free.
"""

from __future__ import annotations

from typing import Any, List, Optional, Protocol, Sequence, Tuple


class BoardDBLike(Protocol):
    """The query surface the board render uses (read-only subset of BoardDB)."""

    def query(
        self, sql: str, params: Optional[Sequence[Any]] = None
    ) -> List[Tuple]: ...

    def query_quiet(
        self, sql: str, params: Optional[Sequence[Any]] = None
    ) -> List[Tuple]: ...

    def scalar(self, sql: str, params: Optional[Sequence[Any]] = None) -> Any: ...
