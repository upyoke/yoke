"""Validation and errors shared by db-admin setup components."""


class DbAdminSetupError(RuntimeError):
    """The db-admin profile setup plan cannot be applied."""


def _safe_label(value: str, *, what: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise DbAdminSetupError(f"{what} must be non-empty")
    if any(char.isspace() for char in text):
        raise DbAdminSetupError(f"{what} must not contain whitespace")
    return text
