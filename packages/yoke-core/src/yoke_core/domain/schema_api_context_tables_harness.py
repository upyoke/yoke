"""``machines`` and ``harness_machine_reports`` packet teaching.

Two rows, two questions. ``machines`` answers *which host is this, who owns
it, and who may spend its capacity*; ``harness_machine_reports`` answers
*which harnesses are installed and approved for one project on a machine*.
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
        ],
        "notes": (
            "PK machine_id, the same canonical UUID that harness_sessions, "
            "session_relays, session_launches, session_termination_reaps and "
            "session_surface_policies carry — one registered machine, not a "
            "per-harness or per-project row. A machine is identified by its "
            "registered id and name; there is no key and no signed proof. "
            "access is the JSON access document "
            "(use.mode owner_only|actors|project_role|universe, plus a "
            "reserved offers block). The use half is enforced by "
            "session_control.launch.preview and .create. "
            f"{OFFERS_ENFORCEMENT_NOTE} Read via machine.list / machine.show / "
            "machine.settings.get; write via machine.register and "
            "machine.settings.set — never raw SQL."
        ),
    },
    "harness_machine_reports": {
        "columns": [
            ("project_id", "INTEGER"),
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
            "PK (project_id, harness_id). No project_installs or "
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
