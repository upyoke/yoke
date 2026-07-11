"""Dispatcher application-state table entries for schema packets."""

from __future__ import annotations


DISPATCH_TABLES: dict[str, dict] = {
    "function_call_ledger": {
        "columns": [
            ("request_id", "TEXT"),
            ("function_id", "TEXT"),
            ("actor_id", "TEXT"),
            ("authorization_scope", "TEXT"),
            ("payload_checksum", "TEXT"),
            ("result", "TEXT"),
            ("created_at", "TEXT"),
        ],
        "notes": (
            "Bounded successful-call replay state. request_id is globally "
            "unique, but replay is permitted only when function_id, authenticated "
            "actor_id, authorization_scope, and canonical payload_checksum all "
            "match. Empty legacy scope fields are unverifiable and collide "
            "fail-closed. This table, not events, owns replay decisions."
        ),
    },
    "github_workflow_dispatch_intents": {
        "columns": [
            ("request_id", "TEXT"),
            ("attempt", "INTEGER"),
            ("actor_id", "TEXT"),
            ("authorization_scope", "TEXT"),
            ("payload_checksum", "TEXT"),
            ("correlation_id", "TEXT"),
            ("state", "TEXT"),
            ("workflow_run_id", "TEXT"),
            ("created_at", "TEXT"),
            ("updated_at", "TEXT"),
        ],
        "notes": (
            "Application state for GitHub workflow dispatch. A pending row is "
            "written before POST; correlation_id is exposed in the target "
            "workflow run-name and recovers a lost accepted response. Completed "
            "attempts keep the exact workflow_run_id; a conclusively failed run "
            "advances attempt instead of replaying it. Never infer this state "
            "from events or a branch/head-SHA search."
        ),
    },
}


__all__ = ["DISPATCH_TABLES"]
