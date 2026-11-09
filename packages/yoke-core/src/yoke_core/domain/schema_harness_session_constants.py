"""Shared harness-session column declarations for creation and convergence."""

TURN_POSTURES = frozenset({"running", "waiting", "unknown"})

TURN_POSTURE_COLUMN_DDL = (
    "TEXT NOT NULL DEFAULT 'unknown' "
    "CHECK(turn_posture IN ('running','waiting','unknown'))"
)

TURN_POSTURE_AT_COLUMN_DDL = "TEXT DEFAULT NULL"

TURN_POSTURE_INSTANT_COLUMN_DDL = "TIMESTAMPTZ DEFAULT NULL"

NATIVE_PROCESS_GONE_AT_COLUMN = "native_process_gone_at"

NATIVE_PROCESS_GONE_EVIDENCE_COLUMN = "native_process_gone_evidence"

NATIVE_PROCESS_EVIDENCE_COLUMN_DDL = "TEXT DEFAULT NULL"

NATIVE_PROCESS_INSTANT_COLUMN_DDL = "TIMESTAMPTZ DEFAULT NULL"

# Additive columns shared by fresh creation and convergence.
SESSION_RECOVERY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("first_user_prompt_at", "TIMESTAMPTZ DEFAULT NULL"),
    ("first_completed_work_at", "TIMESTAMPTZ DEFAULT NULL"),
    ("last_completed_work_at", "TIMESTAMPTZ DEFAULT NULL"),
    ("native_turn_end_recorded_at", "TIMESTAMPTZ DEFAULT NULL"),
    ("native_turn_end_observation", "TEXT DEFAULT NULL"),
    ("vendor_resume_episode_key", "TEXT DEFAULT NULL"),
    ("vendor_resume_attempts", "INTEGER NOT NULL DEFAULT 0"),
)

# Durable session-and-item hold ledger read by the Stop gate.
PROMISED_WORK_HOLDS_TABLE = "session_promised_work_holds"

READ_FINGERPRINTS_COLUMN = "steering_report_read_fingerprints"

READ_FINGERPRINTS_DDL = "TEXT DEFAULT NULL"
