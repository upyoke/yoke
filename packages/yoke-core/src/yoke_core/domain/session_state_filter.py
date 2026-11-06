"""Filter complete session projections before applying the requested page."""

from yoke_contracts.session_state_fields import SESSION_STATE_CHOICES


def validate_state_filters(filters):
    for key, value in filters.items():
        if value is not None and value not in SESSION_STATE_CHOICES[key]:
            raise ValueError(
                f"{key} must be one of {', '.join(SESSION_STATE_CHOICES[key])}; "
                f"got {value!r}. Choose a value from yoke sessions list --help."
            )


def state_page(rows, filters, offset, limit):
    def matches(row):
        state = row["session_state"]
        return all(
            value is None
            or (state[key].get("state") if key == "intent" else state[key]) == value
            for key, value in filters.items()
        )

    selected = [row for row in rows if matches(row)]
    return selected[offset : None if limit is None else offset + limit]
