"""One catalog, derived from dispatch, consumed by everything that needs it.

The failure this guards is quiet: a lane allowlist accepting an action the
summary cannot name, or the summary offering an action nothing dispatches.
Both come from keeping two lists, so the catalog derives its membership and
refuses to answer at all when the two halves disagree.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import routable_actions
from yoke_core.domain.project_session_routing_defaults import (
    session_routing_defaults,
)
from yoke_core.domain.routable_actions import (
    STEERING_ACTION,
    RoutableActionCatalogError,
    dispatch_supported_action_ids,
    is_routable_action,
    routable_action_catalog_payload,
    routable_action_ids,
    routable_actions as catalog,
)
from yoke_core.domain.sessions_analytics_core import lifecycle_dispatch_paths
from yoke_core.domain.work_processes import process_dispatch_paths


@pytest.fixture(autouse=True)
def _fresh_catalog():
    catalog.cache_clear()
    yield
    catalog.cache_clear()


class TestMembership:
    def test_membership_is_exactly_what_can_be_dispatched(self):
        assert set(routable_action_ids()) == dispatch_supported_action_ids()

    def test_every_lifecycle_dispatch_path_is_routable(self):
        assert lifecycle_dispatch_paths() <= set(routable_action_ids())

    def test_every_process_dispatch_path_is_routable(self):
        assert process_dispatch_paths() <= set(routable_action_ids())

    def test_steer_is_routable(self):
        assert is_routable_action(STEERING_ACTION)

    def test_a_skill_that_is_not_a_dispatch_destination_is_not_routable(self):
        # `idea` and `curate` are skills an operator runs; neither is a lane
        # a session can be routed onto, so neither belongs in an allowlist.
        assert not is_routable_action("idea")
        assert not is_routable_action("curate")

    def test_the_shipped_lane_defaults_only_name_routable_actions(self):
        for lane, actions in session_routing_defaults()["lane_paths"].items():
            unknown = [a for a in actions if not is_routable_action(a)]
            assert unknown == [], f"{lane} declares unroutable {unknown}"


class TestPresentation:
    def test_every_action_carries_a_label_and_a_description(self):
        for action in catalog():
            assert action.label.strip()
            assert action.description.strip().endswith(".")

    def test_the_payload_shape_is_id_label_description(self):
        payload = routable_action_catalog_payload()
        assert payload
        assert all(set(row) == {"id", "label", "description"} for row in payload)

    def test_order_is_stable_across_calls(self):
        assert routable_action_ids() == routable_action_ids()


class TestHalvesMustAgree:
    def test_a_dispatch_path_with_no_presentation_refuses_the_catalog(
        self, monkeypatch
    ):
        supported = frozenset({*routable_action_ids(), "teleport"})
        monkeypatch.setattr(
            routable_actions, "dispatch_supported_action_ids", lambda: supported
        )
        catalog.cache_clear()
        with pytest.raises(RoutableActionCatalogError) as caught:
            catalog()
        assert "teleport" in str(caught.value)
        assert "routable_actions" in str(caught.value)

    def test_a_described_action_nothing_dispatches_refuses_the_catalog(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            routable_actions,
            "dispatch_supported_action_ids",
            lambda: frozenset({"dash"}),
        )
        catalog.cache_clear()
        with pytest.raises(RoutableActionCatalogError) as caught:
            catalog()
        assert "not dispatchable" in str(caught.value)
