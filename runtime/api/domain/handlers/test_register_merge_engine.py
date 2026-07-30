"""Registration wiring for the internal merge-engine finalize touches.

The wiring contract: importing ``_register_merge_engine`` in the domain
import block AND listing it in ``_DOMAIN_REGISTRARS`` must both happen for
``register_all_handlers()`` to register the two merge-engine function ids.
The prune verdict is a side-effect-free read; the post-rebase requirement
resolution materializes QA requirements. Both are internal (no CLI
adapter). ``project.snapshot.ensure_at`` is verified alongside as the
snapshot-family write the finalize path relays.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import yoke_function_registry
from yoke_core.domain.handlers import __init_register__ as init_register

_MERGE_ENGINE_FUNCTION_IDS = (
    "merge.prune.authority_verdict",
    "merge.tests.post_rebase_requirement",
)


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    yoke_function_registry.reset_registry_for_tests()
    yield
    yoke_function_registry.reset_registry_for_tests()


def test_all_merge_engine_functions_registered() -> None:
    init_register.register_all_handlers()
    ids = {entry.function_id for entry in yoke_function_registry.list_entries()}
    for function_id in _MERGE_ENGINE_FUNCTION_IDS:
        assert function_id in ids
    assert "project.snapshot.ensure_at" in ids


def test_prune_verdict_is_internal_read() -> None:
    init_register.register_all_handlers()
    entry = yoke_function_registry.lookup("merge.prune.authority_verdict")
    assert entry is not None
    assert entry.adapter_status == "internal"
    assert entry.target_kinds == ("global",)
    assert entry.side_effects == ()
    assert entry.claim_required_kind is None
    assert entry.owner_module == (
        "yoke_core.domain.handlers.merge_engine_internal_ops"
    )


def test_post_rebase_requirement_is_internal_qa_write() -> None:
    init_register.register_all_handlers()
    entry = yoke_function_registry.lookup("merge.tests.post_rebase_requirement")
    assert entry is not None
    assert entry.adapter_status == "internal"
    assert entry.target_kinds == ("item",)
    assert entry.side_effects == ("qa_requirements_insert",)
    assert entry.claim_required_kind is None


def test_snapshot_ensure_at_is_internal_snapshot_write() -> None:
    init_register.register_all_handlers()
    entry = yoke_function_registry.lookup("project.snapshot.ensure_at")
    assert entry is not None
    assert entry.adapter_status == "internal"
    assert entry.target_kinds == ("global",)
    assert "path_snapshot_write" in entry.side_effects
    assert entry.owner_module == (
        "yoke_core.domain.handlers.project_snapshot_ensure_at"
    )
