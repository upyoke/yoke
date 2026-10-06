"""Persistent admission budgets for unauthenticated machine sign-in traffic."""

import hashlib
import time

from yoke_core.domain import db_backend

RATE_WINDOW_SECONDS = 60
START_REQUESTS = 6
POLL_REQUESTS = 120
CLIENT_PENDING_CODES = 8
SERVER_PENDING_CODES = 128


def admit_client(conn, *, client: str, operation: str, now=None) -> tuple[str, int]:
    """Count even refused requests; workers and restarts share one client budget.

    Use the transport peer, after the server's trusted proxy handling. Headers
    and the caller's machine UUID never select the admission identity.
    """
    limit = {"start": START_REQUESTS, "poll": POLL_REQUESTS}[operation]
    now = int(time.time() if now is None else now)
    window = now - now % RATE_WINDOW_SECONDS
    key = hashlib.sha256(client.encode()).hexdigest()
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    count = conn.execute(
        "INSERT INTO machine_authorization_rate_limits "
        "(client_key,operation,window_start,request_count) "
        f"VALUES ({p},{p},{p},1) ON CONFLICT(client_key,operation) DO UPDATE SET "
        "window_start=excluded.window_start, request_count=CASE "
        "WHEN machine_authorization_rate_limits.window_start=excluded.window_start "
        "THEN machine_authorization_rate_limits.request_count+1 ELSE 1 END "
        "RETURNING request_count",
        (key, operation, window),
    ).fetchone()[0]
    conn.execute(
        f"DELETE FROM machine_authorization_rate_limits WHERE window_start < {p}",
        (window - RATE_WINDOW_SECONDS,),
    )
    conn.commit()
    return key, RATE_WINDOW_SECONDS - (now - window) if count > limit else 0
