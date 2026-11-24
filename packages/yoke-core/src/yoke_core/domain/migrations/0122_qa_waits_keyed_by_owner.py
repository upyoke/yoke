"""Retire the session-keyed wait index after additive boot creates the owner key.

Earlier servers recreate the retired index at boot and cannot serve multiple
live execution waits on one host for the same session.
"""

MINIMUM_SERVING_VERSION = "next-release"


def apply(conn):
    """Drop the obsolete index and preserve all queue rows."""
    conn.execute("DROP INDEX IF EXISTS idx_qa_test_machine_waits_live_session")
