"""QA settlement follow-up table declaration."""

#: Part of the QA schema, which initializes on its own before ``items``
#: exists, so ``item_id`` carries no foreign key, like ``qa_requirements``.
QA_SETTLEMENT_FOLLOWUPS_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS qa_settlement_followups (
  item_id INTEGER PRIMARY KEY,
  requested_at TIMESTAMPTZ NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  attempted_at TIMESTAMPTZ,
  last_error TEXT NOT NULL DEFAULT ''
);
"""
