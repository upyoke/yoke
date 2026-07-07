"""Contracts and constants for the governed migration harness."""

from __future__ import annotations

CRITICAL_TABLES = ("items", "epic_tasks", "events", "epic_progress_notes", "qa_runs")

# Migrations audit table name
AUDIT_TABLE = "migration_audit"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class MigrationVerificationError(Exception):
    """Raised when post-flight verification detects unexpected state."""


class MigrationBackupError(Exception):
    """Raised when pre-flight backup fails."""


class AuditEmissionError(Exception):
    """Raised when ``record_audit_fingerprint`` cannot persist its row.

    Callers that reached the helper by declaring themselves on the
    documented exception pathway are required to propagate this error;
    the audit row is the only durable evidence that the exception fired,
    so a missing row cannot be swallowed.
    """
