# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import json

import subprocess

from pathlib import Path

from types import SimpleNamespace

from unittest.mock import Mock

import pytest

from yoke_contracts.browser_identity import (
    BrowserIdentityError,
    parse_identity_declarations,
)

from yoke_contracts.machine_config.capability_secrets import (
    is_machine_local_capability_secret,
)

from yoke_contracts.machine_config.capability_secret_store import (
    list_machine_capability_secret_keys,
    store_machine_capability_secret,
)

from yoke_harness import browser_automatic_sign_in as automatic


def declaration():
    return {
        "site": "shop",
        "origin": "https://shop.example",
        "probe": {"url": "https://shop.example/me", "signed_in_status": 200},
        "sign_in": {
            "mode": "automatic",
            "url": "https://shop.example/login",
            "steps": [{"fill": "#password", "secret": "password"}, {"click": "button"}],
        },
    }


def identity(site=None):
    return parse_identity_declarations(
        {"identities": {"buyer": {"sites": [site or declaration()]}}}
    )["buyer"]
