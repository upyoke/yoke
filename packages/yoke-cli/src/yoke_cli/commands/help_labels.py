"""Product-boundary labels for CLI help output."""

from __future__ import annotations

from functools import lru_cache


_HELP_LABELS = {
    "client-local helper": "client-local",
    "hook-local subset": "hook-local",
    "source-dev/admin": "source-dev/admin",
    "operator-debug permanent": "operator-debug",
    "legacy/delete": "legacy/delete",
}


def label_for_cli_form(cli_form: str) -> str:
    """Return the help label for ``cli_form``, or ``""`` for product-normal."""
    return _help_label_map().get(cli_form, "")


def labeled_cli_form(cli_form: str) -> str:
    label = label_for_cli_form(cli_form)
    return f"{cli_form} [{label}]" if label else cli_form


@lru_cache(maxsize=1)
def _help_label_map() -> dict[str, str]:
    try:
        from yoke_cli import product_boundary_inventory as inventory

        rows = inventory.generate_inventory()
    except Exception:
        return {}
    return {
        row.command_helper: label
        for row in rows
        if (label := _HELP_LABELS.get(row.disposition))
    }


__all__ = ["label_for_cli_form", "labeled_cli_form"]
