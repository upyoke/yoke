"""Test Machine settings refuse the retired sealed browser-profile baseline path."""

import pytest

from yoke_contracts.machine_config.test_machine import (
    TestMachineCapabilityError,
    validate_test_machine_settings,
)

DECLARED = {
    "resource_name": "test-mac",
    "host": "test-mac.local",
    "user": "qa",
    "os": "macos",
    "operating_notes": "",
    "golden_baseline_path": "/Users/Shared/goldens/qa-golden",
}


def test_live_identities_replace_the_sealed_browser_profile_setting():
    validate_test_machine_settings(DECLARED)
    with pytest.raises(
        TestMachineCapabilityError, match="unknown browser_profile_baseline_path"
    ):
        validate_test_machine_settings(
            {**DECLARED, "browser_profile_baseline_path": "/Users/Shared/goldens/p"}
        )
