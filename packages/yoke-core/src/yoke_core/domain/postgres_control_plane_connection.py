"""Opening a control-plane PostgreSQL connection that cannot strand its locks.

A client that hibernates, loses its network, or is killed between two
statements leaves its backend ``idle in transaction``, still holding every lock
that transaction took. Nothing on the client can release them, because the
client is what went away. The bound therefore has to be declared where the
connection is opened and enforced by the server that owns the locks.

Two guards, answering two different failures:

* ``idle_in_transaction_session_timeout`` is the server's own bound, declared
  as a libpq startup option so it is in force before the first statement and no
  ``ROLLBACK`` can revert it. It is set per connection rather than only
  persisted as the role default, because a role default is scoped to one
  ``(role, database)`` pair: the boot converge writes it for the role the
  serving build connects as, and a client connecting as any other role
  silently inherits that role's value instead. Measured on the production
  control plane, the serving role carried ``2min`` while the admin role a
  production deploy driver connects as carried ``1d`` -- which is how an
  abandoned transaction held a run row for eleven minutes under a guard that
  looked, from the server's side, like it was already in place. Declaring it
  on the connection makes the bound a property of every Yoke client, whatever
  role it authenticates as.
* TCP keepalives let libpq notice a half-dead forward -- a laptop asleep at the
  far end of an SSH tunnel -- instead of waiting on a socket that will never
  answer, so the client stops pinning its own side too.

Explicitly declared values win: a caller that names its own ``keepalives_idle``
or its own ``idle_in_transaction_session_timeout`` keeps it.
"""

from __future__ import annotations

from typing import Any


IDLE_IN_TRANSACTION_SETTING = "idle_in_transaction_session_timeout"

# The relay's bounded poll is shorter than this guard. Two minutes preserves
# headroom for normal request cleanup while terminating a stranded transaction
# soon enough to bound lock blocking and vacuum horizon retention.
IDLE_IN_TRANSACTION_SESSION_TIMEOUT = "2min"

# Roughly a minute to declare a silent peer dead: three probes ten seconds
# apart after thirty seconds of quiet. Short enough that an abandoned forward
# is noticed well inside the idle-in-transaction bound above, long enough that
# a briefly congested link is not torn down under load.
KEEPALIVE_PARAMS: dict[str, str] = {
    "keepalives": "1",
    "keepalives_idle": "30",
    "keepalives_interval": "10",
    "keepalives_count": "3",
}


def _idle_guard_option() -> str:
    return f"-c {IDLE_IN_TRANSACTION_SETTING}={IDLE_IN_TRANSACTION_SESSION_TIMEOUT}"


def guarded_conninfo(dsn: str) -> str:
    """Return *dsn* with the control-plane transaction and keepalive guards.

    Idempotent, so a DSN already guarded -- or one an operator wrote the
    settings into by hand -- passes through rather than accumulating
    duplicates.
    """
    from psycopg import conninfo

    declared = conninfo.conninfo_to_dict(dsn)
    overrides = {
        key: value for key, value in KEEPALIVE_PARAMS.items() if key not in declared
    }
    options = str(declared.get("options") or "")
    if IDLE_IN_TRANSACTION_SETTING not in options:
        overrides["options"] = f"{options} {_idle_guard_option()}".strip()
    if not overrides:
        return dsn
    return conninfo.make_conninfo(dsn, **overrides)


def open_guarded_postgres(dsn: str, **connect_kwargs: Any):
    """Open one psycopg connection to *dsn* under the control-plane guards.

    The single place a control-plane Postgres socket is created, so a guard
    added here reaches every mode -- local, self-hosted, hosted -- every
    environment, and every role, including the admin roles no boot converge
    writes a default for.
    """
    import psycopg

    return psycopg.connect(guarded_conninfo(dsn), **connect_kwargs)


__all__ = [
    "IDLE_IN_TRANSACTION_SESSION_TIMEOUT",
    "IDLE_IN_TRANSACTION_SETTING",
    "KEEPALIVE_PARAMS",
    "guarded_conninfo",
    "open_guarded_postgres",
]
