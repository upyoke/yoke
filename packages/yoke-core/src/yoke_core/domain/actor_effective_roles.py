"""Shared human-role ranks for project and organization audiences."""

HUMAN_ROLES = ("owner", "admin", "operator", "viewer")
HUMAN_ROLE_RANKS = {"owner": 3, "admin": 3, "operator": 2, "viewer": 1}


def role_rank_sql(expression: str) -> str:
    """Rank only human roles; machine roles never satisfy a human audience."""
    cases = " ".join(
        f"WHEN '{role}' THEN {rank}" for role, rank in HUMAN_ROLE_RANKS.items()
    )
    return f"(CASE {expression} {cases} ELSE 0 END)"


def role_matches_sql(held: str, required: str) -> str:
    return (
        f"({required} IS NULL OR ({role_rank_sql(required)} > 0 "
        f"AND {role_rank_sql(held)} >= {role_rank_sql(required)}))"
    )
