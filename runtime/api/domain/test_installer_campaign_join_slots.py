"""The exported second-machine join holds two distinct hosts of one OS."""

from runtime.api.domain.qa_release_channel_target_test_support import _target
from yoke_core.domain.installer_campaign_execution_target import (
    installer_campaign_cases_for_target,
)
from yoke_core.domain.machine_qa_case_hosts import case_slots, driver_slot_os
from yoke_core.domain.qa_host_slot_turns import pick_slot_hosts


def _join() -> dict:
    cases = installer_campaign_cases_for_target(_target("prod"), os="macos")
    return next(row for row in cases if row["case_key"] == "second-machine-join")


def test_join_exports_two_macos_slots_with_one_driver() -> None:
    join = _join()
    assert "os" not in join["method_config"]
    assert [slot["os"] for slot in case_slots(join)] == ["macos", "macos"]
    assert driver_slot_os(join) == "macos"


def test_join_slots_are_admitted_on_two_distinct_hosts() -> None:
    hosts = ("mac-a", "mac-b")
    eligibility = tuple((slot["os"], hosts) for slot in case_slots(_join()))
    assert pick_slot_hosts(eligibility, hosts) == ("mac-a", "mac-b")
    assert pick_slot_hosts(eligibility, ("mac-a",)) is None
