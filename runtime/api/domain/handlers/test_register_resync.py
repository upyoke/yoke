"""Registration + authorization wiring for the internal resync functions.

The wiring contract: importing ``_register_resync`` in the domain import
block AND listing it in ``_DOMAIN_REGISTRARS`` must both happen for
``register_all_handlers()`` to register the ``resync.*`` function ids. The
six reads are internal, claim-free, side-effect-free (so authorization
falls through to the machine-local read allowance); the one write is
internal, claim-free, session-optional, declares its side effect, and is
gated by the ``PROJECT`` + ``PERM_ITEMS_WRITE`` product scope.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import yoke_function_registry
from yoke_core.domain.actor_permissions import PERM_ITEMS_WRITE
from yoke_core.domain.function_authz_scope import (
    CLIENT_LOCAL,
    PROJECT,
    classify,
    permission_key_for,
)
from yoke_core.domain.handlers import __init_register__ as init_register

_RESYNC_READS = (
    "resync.linkage_roster",
    "resync.linkage_rows",
    "resync.compare_prefetch",
    "resync.item_lookup",
    "resync.epic_task_repair_read",
    "resync.epic_task_body",
)
_RESYNC_WRITE = "resync.epic_task_github_issue_set"


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    yoke_function_registry.reset_registry_for_tests()
    yield
    yoke_function_registry.reset_registry_for_tests()


def test_all_resync_functions_registered() -> None:
    init_register.register_all_handlers()
    ids = {entry.function_id for entry in yoke_function_registry.list_entries()}
    for function_id in (*_RESYNC_READS, _RESYNC_WRITE):
        assert function_id in ids


@pytest.mark.parametrize("function_id", sorted(_RESYNC_READS))
def test_read_is_internal_claim_free_machine_local(function_id) -> None:
    init_register.register_all_handlers()
    entry = yoke_function_registry.lookup(function_id)
    assert entry is not None
    assert entry.adapter_status == "internal"
    assert entry.claim_required_kind is None
    assert entry.side_effects == ()
    assert entry.target_kinds == ("global",)
    # A side-effect-free read with no explicit scope falls through to the
    # machine-local read allowance (no session/actor required).
    spec = classify(function_id, side_effects=False, project_permission=None)
    assert spec.scope == CLIENT_LOCAL


def test_write_is_internal_session_optional_project_scoped() -> None:
    init_register.register_all_handlers()
    entry = yoke_function_registry.lookup(_RESYNC_WRITE)
    assert entry is not None
    assert entry.adapter_status == "internal"
    assert entry.target_kinds == ("item",)
    assert entry.side_effects == ("epic_task_github_issue_write",)
    # Claim-free by design (the done ceremony's claim-free posture); a
    # missing session must not block it, so ambient_session_required is False.
    assert entry.claim_required_kind is None
    assert entry.ambient_session_required is False
    # The PROJECT + items-write scope gates the intentional claim bypass.
    spec = classify(
        _RESYNC_WRITE,
        side_effects=True,
        project_permission=permission_key_for(entry),
    )
    assert spec.scope == PROJECT
    assert spec.permission_key == PERM_ITEMS_WRITE
