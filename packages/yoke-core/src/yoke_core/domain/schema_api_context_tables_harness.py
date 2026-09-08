"""``machines`` and ``harness_machine_reports`` packet teaching.

Two rows, two questions. ``machines`` answers *which host is this, who owns
it, and who may spend its capacity*; ``harness_machine_reports`` answers
*which harnesses are installed and approved for one project on one
machine*.
Wrong guesses these exist to catch: ``project_installs`` and
``harness_installs``, which do not exist; and reading ``machines`` as the
per-project harness inventory, which is the reports table.
"""

from __future__ import annotations

from yoke_contracts.machine_config.machine_access import OFFERS_ENFORCEMENT_NOTE


HARNESS_TABLES: dict[str, dict] = {
    "machines": {
        "columns": [
            ("machine_id", "TEXT"),
            ("name", "TEXT"),
            ("owner_actor_id", "INTEGER"),
            ("access", "TEXT"),
            ("registered_at", "TEXT"),
            ("last_seen_at", "TEXT"),
            ("retired_at", "TEXT"),
            ("retired_by_actor_id", "INTEGER"),
        ],
        "notes": (
            "PK machine_id, the same canonical UUID that harness_sessions, "
            "session_relays, session_launches, session_termination_reaps and "
            "session_surface_policies carry — one registered machine, not a "
            "per-harness or per-project row. A machine is identified by its "
            "registered id and name. Its active bearer is stored only as a "
            "hash in api_tokens, bound by api_tokens.machine_id, and returned "
            "raw only by machine.register. Re-registering rotates that bearer. "
            "access is the JSON access document "
            "(use.mode owner_only|actors|project_role|universe, plus a "
            "reserved offers block). The use half is enforced by "
            "session_control.launch.preview and .create, and it also decides "
            "whether a machine with no project checkout appears in "
            "session_control.relay.list — a checkout is a launch prerequisite, "
            "not a condition of being seen. "
            f"{OFFERS_ENFORCEMENT_NOTE} Read via machine.list / machine.show / "
            "machine.detail / machine.settings.get; write via machine.register, "
            "machine.retire, and machine.settings.set — never raw SQL. Retirement "
            "revokes only machine-bound tokens and preserves machine, session, "
            "and launch history; a retired id never reconnects."
        ),
    },
    "harness_machine_reports": {
        "columns": [
            ("project_id", "INTEGER"),
            ("machine_id", "TEXT"),
            ("harness_id", "TEXT"),
            ("glue_written", "INTEGER"),
            ("glue_present", "INTEGER"),
            ("glue_malformed", "INTEGER"),
            ("config_present", "INTEGER"),
            ("project_entry_present", "INTEGER"),
            ("approval_state", "TEXT"),
            ("unattended_posture", "TEXT"),
            ("reported_at", "TEXT"),
        ],
        "notes": (
            "Keyed (project_id, machine_id, harness_id) by unique index "
            "ux_harness_machine_reports_key, so two machines report the same "
            "harness independently and neither answers for the other; a row "
            "written before the machine column carries machine_id='' and "
            "matches no machine. No project_installs or "
            "harness_installs table; machine identity, ownership and "
            "access live on the machines row above. approval_state is "
            "approved|unapproved|not_applicable|unknown; unapproved makes "
            "Overview hook health red (every normalized .codex/hooks.json "
            "handler must match trusted_hash under the literal hooks-file "
            "path). Write "
            "via harness.machine_report.upsert. unattended_posture is "
            "unattended|prompts|absent and answers whether a session the "
            "operator opens in that harness runs yoke without an approval "
            "prompt; 'absent' means the harness is not installed on the "
            "reporting machine, never that it is configured."
        ),
    },
}


__all__ = ["HARNESS_TABLES"]
