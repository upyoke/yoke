# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import pytest

from concurrent.futures import ThreadPoolExecutor

from threading import Barrier

from yoke_contracts.self_host_bootstrap_output import TOKEN_PREFIX

from runtime.api.domain.decision_request_test_support import decision_request_connection

from runtime.api.domain.machine_registry_test_support import (
    MACHINE_ID,
    OTHER_MACHINE_ID,
)

from yoke_core.domain import machine_authorization_codes as codes

from yoke_core.domain import machine_authorization_decisions as decisions

from yoke_core.domain.auth_schema import create_auth_tables

from yoke_core.domain.external_identity_schema import create_external_identity_tables

from yoke_core.domain.machine_authorization_schema import (
    create_machine_authorization_table,
)

from yoke_core.domain.machine_registry_schema import ensure_machine_registry_schema

ORIGIN = "https://team.example"


@pytest.fixture()
def conn():
    with decision_request_connection() as value:
        create_auth_tables(value)
        create_external_identity_tables(value)
        ensure_machine_registry_schema(value)
        create_machine_authorization_table(value)
        value.execute("INSERT INTO actor_org_roles VALUES (1, 1, 4, 'now')")
        value.commit()
        yield value


def pending(conn, client_key="client"):
    return codes.start(
        conn,
        origin=ORIGIN,
        machine_id=MACHINE_ID,
        machine_name="Pat's laptop",
        platform="macOS",
        client_key=client_key,
    )
