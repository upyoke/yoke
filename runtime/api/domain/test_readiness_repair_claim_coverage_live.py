"""Live-universe coverage for claim-coverage repair connection opening."""

from __future__ import annotations

from yoke_core.domain import db_backend
from yoke_core.domain import idea_readiness_repair_claim_coverage as repair


def test_open_conn_reaches_live_postgres_authority() -> None:
    if not db_backend.is_postgres():
        return
    opened = repair._open_conn()
    try:
        row = opened.execute("SELECT 1 AS n").fetchone()
        assert row is not None
    finally:
        opened.close()
