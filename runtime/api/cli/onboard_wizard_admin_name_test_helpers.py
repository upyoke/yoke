"""Pilot step for the first-admin name prompt a new universe opens."""

from __future__ import annotations

from runtime.api.cli.onboard_wizard_test_helpers import type_text


async def enter_admin_name(pilot, name: str = "Ada Lovelace") -> None:
    """Type the installer's name and submit it."""
    await type_text(pilot, name)
    await pilot.press("enter")
