"""Write-path item-id parser (_parse_item_id_arg), on real Postgres.

The mutation commands (backlog close / update / batch-update) resolve their
item argument through ``_parse_item_id_arg``. It must resolve ``PREFIX-N``
per-project (not strip a hardcoded ``YOK-`` and treat the remainder as the
global id) so project-local prefixes work and a ``PREFIX-N`` ref maps to its
project sequence. Proven against a disposable real-Postgres database with
``project_sequence`` deliberately decoupled from ``items.id``.
"""

from __future__ import annotations

import pytest

from yoke_core.api.service_client_shared_session_resolver import _parse_item_id_arg
from yoke_core.domain.project_seed_test_helpers import seed_project_identities

YOKE_ITEM_ID = 100
BUZZ_ITEM_ID = 200
SEQ = 5


@pytest.fixture()
def seeded(test_db):
    conn = test_db
    seed_project_identities(conn)
    conn.execute("UPDATE projects SET public_item_prefix = 'BUZ' WHERE slug = 'buzz'")
    conn.execute("UPDATE projects SET public_item_prefix = 'YOK' WHERE slug = 'yoke'")
    for item_id, project_id in ((YOKE_ITEM_ID, 1), (BUZZ_ITEM_ID, 2)):
        conn.execute(
            "INSERT INTO items (id, title, created_at, updated_at, project_id, "
            "project_sequence) VALUES (%s, 't', '2026-01-01T00:00:00Z', "
            "'2026-01-01T00:00:00Z', %s, %s)",
            (item_id, project_id, SEQ),
        )
    conn.commit()
    return conn


def test_prefix_ref_resolves_to_project_sequence(seeded):
    # YOK-5 is sequence 5 in yoke (internal id 100), NOT the global id 5.
    assert _parse_item_id_arg("YOK-5") == YOKE_ITEM_ID


def test_project_prefix_resolves(seeded):
    # BUZ-5 must resolve through the project prefix registry.
    assert _parse_item_id_arg("BUZ-5") == BUZZ_ITEM_ID


def test_bare_internal_id_passthrough(seeded):
    assert _parse_item_id_arg(str(BUZZ_ITEM_ID)) == BUZZ_ITEM_ID
