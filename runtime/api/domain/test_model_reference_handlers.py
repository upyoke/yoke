"""Registered model reads and writes use the published DB catalog."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import db_helpers, yoke_function_registry
from yoke_core.domain.handlers import __init_register__ as init_register
from yoke_core.domain.handlers import model_reference
from yoke_core.domain.handlers import model_reference_publication as publication
from yoke_core.domain.model_reference_store import (
    create_model_reference_table,
    seed_initial_catalog,
)


@pytest.fixture
def catalog_db(monkeypatch):
    conn = sqlite3.connect(":memory:")
    create_model_reference_table(conn)
    seed_initial_catalog(conn)
    monkeypatch.setattr(db_helpers, "connect", lambda: conn)
    yield conn
    conn.close()


def _request(function_id: str, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(session_id="s-test", actor_id="1"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def test_lookup_uses_published_revision_and_keeps_unknown_nonfatal(catalog_db):
    found = model_reference.handle_models_lookup(
        _request(model_reference.LOOKUP_FUNCTION_ID, {"model_id": "gpt-6-sol"})
    )
    assert found.primary_success is True
    assert found.result_payload["record"]["model_id"] == "gpt-6-sol"
    assert found.result_payload["revision_id"]

    unknown = model_reference.handle_models_lookup(
        _request(model_reference.LOOKUP_FUNCTION_ID, {"model_id": "unknown-model"})
    )
    assert unknown.primary_success is True
    assert unknown.result_payload["researched"] is False
    assert unknown.result_payload["record"] is None


def test_diff_and_get_read_complete_published_catalog(catalog_db):
    current = model_reference.handle_models_get(
        _request(model_reference.GET_FUNCTION_ID, {})
    )
    assert current.primary_success is True
    assert current.result_payload["count"] == 18
    assert current.result_payload["source_note"]
    assert current.result_payload["published_at"]
    diff = publication.handle_models_diff(
        _request(
            publication.DIFF_FUNCTION_ID,
            {"catalog": current.result_payload["records"]},
        )
    )
    assert diff.primary_success is True
    assert (
        diff.result_payload["base_revision_id"] == current.result_payload["revision_id"]
    )
    assert diff.result_payload["diff"]["changed"] == []


def test_record_validator_keeps_named_refusal():
    outcome = model_reference.handle_models_validate(
        _request(
            model_reference.VALIDATE_FUNCTION_ID,
            {"record": {"model_id": "x", "provider": "y", "proposed_tier": "gold"}},
        )
    )
    assert outcome.primary_success is False
    assert outcome.error.code == "tier_invalid"


def test_catalog_publication_functions_are_registered():
    init_register.register_all_handlers()
    for function_id in (
        model_reference.LOOKUP_FUNCTION_ID,
        model_reference.GET_FUNCTION_ID,
        model_reference.VALIDATE_FUNCTION_ID,
        publication.DIFF_FUNCTION_ID,
        publication.PUBLISH_FUNCTION_ID,
        publication.REVISIONS_FUNCTION_ID,
        publication.RESTORE_FUNCTION_ID,
    ):
        entry = yoke_function_registry.lookup(function_id)
        assert entry is not None
        assert entry.target_kinds == ("global",)
        assert entry.adapter_status == "live"


def test_publish_and_restore_create_auditable_revisions(catalog_db):
    current = model_reference.handle_models_get(
        _request(model_reference.GET_FUNCTION_ID, {})
    ).result_payload
    candidate = current["records"]
    next(row for row in candidate if row["model_id"] == "gpt-6-sol")["api_price"][
        "input_per_million_usd"
    ] = 3.0
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    published = publication.handle_models_publish(
        _request(
            publication.PUBLISH_FUNCTION_ID,
            {
                "catalog": candidate,
                "expected_base_revision_id": current["revision_id"],
                "source_note": "Checked official provider pricing",
                "effective_at": future,
            },
        )
    )
    assert published.primary_success is True
    latest = publication.handle_models_revisions(
        _request(publication.REVISIONS_FUNCTION_ID, {})
    )
    assert latest.result_payload["count"] == 2
    assert (
        latest.result_payload["revisions"][0]["revision_id"]
        == published.result_payload["revision_id"]
    )
    active = model_reference.handle_models_get(
        _request(model_reference.GET_FUNCTION_ID, {})
    )
    assert active.result_payload["revision_id"] == current["revision_id"]
    future_read = model_reference.handle_models_get(
        _request(model_reference.GET_FUNCTION_ID, {"at": future})
    )
    assert (
        next(
            row
            for row in future_read.result_payload["records"]
            if row["model_id"] == "gpt-6-sol"
        )["api_price"]["input_per_million_usd"]
        == 3.0
    )
    future_lookup = model_reference.handle_models_lookup(
        _request(
            model_reference.LOOKUP_FUNCTION_ID, {"model_id": "gpt-6-sol", "at": future}
        )
    )
    assert (
        future_lookup.result_payload["revision_id"]
        == published.result_payload["revision_id"]
    )
    restored = publication.handle_models_restore(
        _request(
            publication.RESTORE_FUNCTION_ID,
            {
                "source_revision_id": current["revision_id"],
                "expected_base_revision_id": published.result_payload["revision_id"],
                "source_note": "Restore previous sourced catalog",
                "effective_at": future,
            },
        )
    )
    assert restored.primary_success is True
    assert restored.result_payload["revision_id"] != current["revision_id"]
    after = model_reference.handle_models_get(
        _request(model_reference.GET_FUNCTION_ID, {"at": future})
    )
    assert after.result_payload["revision_id"] == restored.result_payload["revision_id"]
