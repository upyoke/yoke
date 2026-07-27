"""Code-owned source scenarios for the installer QA campaign."""

from __future__ import annotations

from dataclasses import dataclass

from yoke_core.domain.installer_campaign_rows_delivery import (
    ROWS as DELIVERY_ROWS,
)
from yoke_core.domain.installer_campaign_rows_foundation import (
    ROWS as FOUNDATION_ROWS,
)
from yoke_core.domain.installer_campaign_rows_github import ROWS as GITHUB_ROWS
from yoke_core.domain.installer_campaign_rows_project import ROWS as PROJECT_ROWS


@dataclass(frozen=True)
class InstallerCampaignScenario:
    """One campaign row preserved as executable-plan input."""

    source_id: str
    wave: str
    host_profile: str
    flow: str
    expected_outcome: str

    @property
    def case_key(self) -> str:
        return self.source_id.lower()

    @property
    def wave_number(self) -> int:
        return int(self.wave.split(":", 1)[0].removeprefix("Wave "))


_ROWS = FOUNDATION_ROWS + GITHUB_ROWS + PROJECT_ROWS + DELIVERY_ROWS
_SCENARIOS = tuple(InstallerCampaignScenario(*row) for row in _ROWS)
INSTALLER_CAMPAIGN_SCENARIOS = tuple(
    scenario
    for _source_position, scenario in sorted(
        enumerate(_SCENARIOS),
        key=lambda entry: (
            entry[1].wave_number,
            entry[0],
        ),
    )
)


__all__ = [
    "INSTALLER_CAMPAIGN_SCENARIOS",
    "InstallerCampaignScenario",
]
