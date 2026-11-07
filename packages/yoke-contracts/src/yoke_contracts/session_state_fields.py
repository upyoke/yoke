"""Public session state selectors shared by command help and read validation."""

SESSION_STATE_CHOICES = {"status": ("working", "waiting", "ended")}


def session_state_columns(row):
    """Expose the canonical model without deriving another state classifier."""
    state = row.get("session_state") or {}
    return {
        **{
            key: state.get(key, row.get(key))
            for key in ("status", "active_at", "reason")
        },
        "presence": state.get("presence", row.get("presence")),
        "activity": state.get("activity", row.get("activity")),
        "intent": state.get("intent", row.get("intent")),
        "next_actor": state.get("next_actor", row.get("next_actor")),
        "holds": (state.get("custody", row.get("custody")) or {}).get(
            "holds", row.get("holds")
        ),
        "custody": state.get("custody", row.get("custody")),
    }
