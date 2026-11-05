# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from typing import Any, Iterator

import pytest

from runtime.api.fixtures import pg_testdb

from yoke_core.domain.actor_invites import (
    INVITE_STATUS_ACCEPTED,
    INVITE_STATUS_PENDING,
    create_invite,
    get_invite,
)

from yoke_core.domain.actor_permissions import (
    PERM_ORG_ADMIN,
    ROLE_ADMIN,
    grant_actor_org_role,
    require_org_permission,
    role_id_by_name,
    seed_roles_and_permissions,
)

from yoke_core.domain.actors import actor_name, seed_human_actor

from yoke_core.domain.auth_schema import create_auth_tables

from yoke_core.domain.external_identities import (
    default_org_id,
    link_external_identity,
    resolve_external_identity,
    set_organization_domain,
)

from yoke_core.domain.external_identity_schema import (
    create_external_identity_tables,
)

from yoke_core.domain.org_schema import seed_default_org

from yoke_core.domain.organization_settings import merge_organization_settings

from yoke_core.domain.project_seed_test_helpers import seed_project_identities

from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_actor_path_claim_tables,
)

from yoke_core.domain.schema_init_path_tables import create_path_registry_tables

from yoke_core.domain.schema_init_tables import create_core_tables

from yoke_core.domain.sign_in_resolution import (
    OUTCOME_AUTO_JOINED,
    OUTCOME_INVITE_ACCEPTED,
    OUTCOME_LINKED_IDENTITY,
    OUTCOME_REFUSED,
    REFUSAL_EMAIL_UNVERIFIED,
    REFUSAL_INVITE_ROLE_REFUSED,
    REFUSAL_MISSING_EMAIL_CLAIM,
    REFUSAL_MISSING_REQUIRED_CLAIMS,
    REFUSAL_NO_ADMISSION_MATCH,
    resolve_sign_in,
)


@pytest.fixture
def conn() -> Iterator[Any]:
    name = pg_testdb.create_test_database()
    c = pg_testdb.connect_test_database(name)
    try:
        create_core_tables(c)
        seed_project_identities(c)
        create_path_registry_tables(c)
        create_actor_path_claim_tables(c)
        create_auth_tables(c)
        create_external_identity_tables(c)
        seed_roles_and_permissions(c)
        seed_default_org(c)
        c.commit()
        yield c
    finally:
        c.close()
        pg_testdb.drop_test_database(name)
