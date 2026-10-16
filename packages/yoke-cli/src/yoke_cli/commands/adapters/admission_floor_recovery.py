"""Recovery guidance for admission commands absent from an older server."""

ADMISSION_FLOOR_RECOVERY = (
    "This server predates this command. Connect with an explicit token "
    "(`yoke connect <server> --token-stdin`), or ask the server operator to upgrade."
)


def admission_floor_hint(function_id: str) -> str:
    return ADMISSION_FLOOR_RECOVERY
