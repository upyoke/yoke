"""Selector arguments decode, reach the payload and keep their order."""

from __future__ import annotations

import argparse

import pytest

from yoke_cli.commands.adapters.session_control_common import (
    SELECTOR_ARGUMENTS,
    add_selector_arguments,
    selector_payload,
    steering_scope_argument,
)


def test_a_steering_scope_must_decode_to_an_object() -> None:
    for raw in ("not json", '["project_id"]'):
        with pytest.raises(argparse.ArgumentTypeError) as raised:
            steering_scope_argument(raw)
        assert "JSON object" in str(raised.value)


def test_a_steering_scope_reaches_the_selector_payload() -> None:
    parser = argparse.ArgumentParser(prog="yoke say")
    add_selector_arguments(parser)
    parser.add_argument("--stdin", action="store_true")

    parsed = parser.parse_args(["--steering-scope", '{"project_id": 3}'])

    assert selector_payload(parsed)["steering_scope"] == {"project_id": 3}


def test_the_item_anchor_is_offered_before_the_session_one() -> None:
    """A reader takes the first workable flag."""
    order = [flag for _dest, flag in SELECTOR_ARGUMENTS]
    assert order.index("--item") < order.index("--session")
    assert order[0] == "--item"
