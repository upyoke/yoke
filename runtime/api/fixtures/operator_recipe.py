"""Assertions for operator recipes shared across shell environments."""


def assert_shell_neutral(*recipes: str) -> None:
    for recipe in recipes:
        for token in ('$(', '"$', '&&', '2>/dev/null'):
            assert token not in recipe, f"Shell-specific token {token!r} in {recipe!r}"
