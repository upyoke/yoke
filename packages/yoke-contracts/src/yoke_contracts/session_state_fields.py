"""Public session state selectors shared by command help and read validation."""

SESSION_STATE_CHOICES = {
    "presence": ("present", "gone", "ended"),
    "activity": ("working", "between_turns", "silent"),
    "intent": ("none", "parked", "awaiting"),
}


def session_state_columns(row):
    """Expose the canonical model without deriving another state classifier."""
    state = row.get("session_state") or {}
    return {
        "presence": state.get("presence"),
        "activity": state.get("activity"),
        "intent": state.get("intent"),
        "next_actor": state.get("next_actor"),
        "holds": (state.get("custody") or {}).get("holds"),
        "custody": state.get("custody"),
    }
