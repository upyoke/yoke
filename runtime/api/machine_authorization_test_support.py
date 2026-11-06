# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import json

from importlib.resources import files

import pytest

from jsonschema import Draft202012Validator

from runtime.api import web_sign_in_door_test_support as door

from runtime.api.self_host_workbench_test_support import _call

from yoke_contracts.machine_authorization import (
    START_PATH,
    POLL_PATH,
    APPROVAL_RETURN_COOKIE,
    POLL_OUTCOMES,
)

from yoke_core.domain.handlers.__init_register__ import register_all_handlers

MACHINE_ID = "762fb8a5-7a6f-43e0-ae85-9665af3fe871"

IDENTITY = {"machine_id": MACHINE_ID, "machine_name": "Second engineer's laptop"}


def _validate_wire(response, model):
    schema = json.loads(
        files("yoke_contracts")
        .joinpath("machine_authorization.schema.v2.json")
        .read_text()
    )
    Draft202012Validator({**schema, "$ref": f"#/$defs/{model}"}).validate(
        response.json()
    )
