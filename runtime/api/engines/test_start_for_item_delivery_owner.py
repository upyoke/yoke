"""start-for-item returns the run already owning an item's delivery.

A held member, or another project's in-flight release that carries the item,
is the answer, so repeating the command while delivery is active creates
nothing. A release that ships this project's source without the item blocks a
competing run and never claims inclusion.
"""

from __future__ import annotations

from unittest import mock

from runtime.api.engines.runs_start_for_item_test_support import _patches
from yoke_core.domain.deployment_item_delivery_owner import (
    CARRIER_IN_FLIGHT,
    DeliveryOwner,
)
from yoke_core.engines import runs_start_for_item as composer
from yoke_core.engines.runs_start_for_item import start_for_item


def test_a_run_already_owning_the_delivery_is_returned_not_duplicated():
    owner = DeliveryOwner("run-7", "executing", "yoke", True, "rides run-7")
    helpers, resolve, _tested, create = _patches()
    bind = mock.Mock()
    with (
        helpers,
        resolve,
        create as create_m,
        mock.patch.object(composer, "delivery_owner", return_value=owner),
        mock.patch.object(composer, "bind_tested_release_source", bind),
    ):
        result = start_for_item(42)

    assert (result.ok, result.reused, result.run_id) == (True, True, "run-7")
    assert result.validation_message == "rides run-7"
    bind.assert_not_called()
    create_m.assert_not_called()


def test_a_bound_release_without_the_item_blocks_a_competing_run():
    owner = DeliveryOwner(
        "run-8", "created", "yoke", False, "does not carry", CARRIER_IN_FLIGHT
    )
    helpers, resolve, _tested, create = _patches()
    with (
        helpers,
        resolve,
        create as create_m,
        mock.patch.object(composer, "delivery_owner", return_value=owner),
    ):
        result = start_for_item(42)

    assert result.ok is False
    assert result.reused is False
    assert result.error_code == CARRIER_IN_FLIGHT
    assert result.run_id == "run-8"
    assert result.error == "does not carry"
    create_m.assert_not_called()
