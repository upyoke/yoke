"""Close-out effects open the connection db_helpers serves at call time."""

from __future__ import annotations

from yoke_core.domain import db_helpers
from yoke_core.domain import delivery_member_close_effects as close_effects


class _Recorder:
    def __init__(self) -> None:
        self.steps: list[str] = []

    def commit(self) -> None:
        self.steps.append("commit")

    def close(self) -> None:
        self.steps.append("close")


def test_effect_steps_follow_the_current_connect(monkeypatch) -> None:
    # A binding taken at import would keep whichever connect was current then,
    # e.g. a fixture substitute whose database a finished test already closed.
    for _ in range(2):
        conn = _Recorder()
        monkeypatch.setattr(db_helpers, "connect", lambda conn=conn: conn)
        close_effects._in_short_transaction(lambda c: c.steps.append("step"))
        assert conn.steps == ["step", "commit", "close"]
