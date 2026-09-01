"""The rows of the wizard's one "where should this Yoke live?" question.

Every row is a full first-class deployment of the same engine; the hint names
what makes each home different. The two hosted rows are one destination
reached through two platforms — the row carries the environment, so picking a
home is one decision rather than a destination screen followed by a second
screen asking which hosted environment to use.

Separated from the flow that routes these choices so the picker's vocabulary
— labels, hints, environments, rail labels — reads in one place.
"""

from __future__ import annotations

from yoke_cli.config.onboard_destinations import (
    DEFAULT_DESTINATION,
    DESTINATION_HOSTED,
    DESTINATION_LOCAL,
    DESTINATION_SERVER,
    ENV_PRODUCTION,
    ENV_STAGE,
)
from yoke_cli.config.onboard_wizard_widgets import STEP_CONNECT_LABEL, SelectionRow

#: The hosted staging row. It selects the same hosted destination as the
#: production row and differs only in which platform the browser connect leg
#: opens, so it is a picker value rather than a fourth destination.
HOSTED_STAGE_ROW = "hosted-stage"

#: Picker-only route. The completed connection is the existing durable
#: team-server destination; this value never enters reports or machine config.
SELF_HOST_SERVER_ROW = "self-host-server"

#: Platform each hosted picker row connects to.
HOSTED_ROW_ENVS = {
    DESTINATION_HOSTED: ENV_PRODUCTION,
    HOSTED_STAGE_ROW: ENV_STAGE,
}

DESTINATION_ROWS = [
    SelectionRow(DESTINATION_LOCAL, "This machine", "free · no account · stays here"),
    SelectionRow(
        DESTINATION_SERVER,
        "A team server",
        "the URL of your team's self-hosted Yoke server",
    ),
    SelectionRow(
        SELF_HOST_SERVER_ROW,
        "Set this machine up as a self-hosting server",
        "Docker Compose · guided first boot",
        hint_on_new_line=True,
    ),
    SelectionRow(DESTINATION_HOSTED, "upyoke.com", "hosted by Yoke · private beta"),
    SelectionRow(
        HOSTED_STAGE_ROW,
        "stage.upyoke.com",
        "staging environment · for testing",
    ),
]

DEFAULT_DESTINATION_INDEX = next(
    index
    for index, row in enumerate(DESTINATION_ROWS)
    if row.value == DEFAULT_DESTINATION
)

#: Rail label per destination: the sign-in destinations keep the Account
#: label; a local run's Account step is universe setup, not sign-in.
ACCOUNT_STEP_LABELS = {
    DESTINATION_LOCAL: "Universe",
    DESTINATION_SERVER: STEP_CONNECT_LABEL,
    SELF_HOST_SERVER_ROW: STEP_CONNECT_LABEL,
    DESTINATION_HOSTED: STEP_CONNECT_LABEL,
    HOSTED_STAGE_ROW: STEP_CONNECT_LABEL,
}

__all__ = [
    "ACCOUNT_STEP_LABELS",
    "DEFAULT_DESTINATION_INDEX",
    "DESTINATION_ROWS",
    "HOSTED_ROW_ENVS",
    "HOSTED_STAGE_ROW",
    "SELF_HOST_SERVER_ROW",
]
