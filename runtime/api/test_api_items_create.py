"""POST /v1/items create-endpoint tests (TestCreateItem)."""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from runtime.api.api_items_test_helpers import (
    make_client_fixture,
    make_test_db_fixture,
)


@pytest.fixture()
def test_db():
    yield from make_test_db_fixture()


@pytest.fixture()
def client(test_db):
    yield from make_client_fixture()


class TestCreateItem:
    def test_create_item_success(self, client, test_db):
        """Item creation now goes through the shared mutation layer (no subprocess)."""
        resp = client.post("/v1/items", json={
            "title": "New idea",
            "type": "issue",
            "priority": "medium",
        })

        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "New idea"
        assert data["type"] == "issue"
        assert data["status"] == "idea"
        assert data["priority"] == "medium"
        assert data["project"] == "yoke"  # default project
        assert "id" in data

    def test_create_item_with_project(self, client, test_db):
        """POST /v1/items accepts optional project field."""
        resp = client.post("/v1/items", json={
            "title": "ExternalWebapp item",
            "type": "issue",
            "project": "externalwebapp",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["project"] == "externalwebapp"

    def test_create_item_with_deployment_flow(self, client, test_db):
        """POST /v1/items accepts optional deployment_flow field."""
        resp = client.post("/v1/items", json={
            "title": "Flow item",
            "type": "issue",
            "project": "yoke",
            "deployment_flow": "test-approval-flow",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["deployment_flow"] == "test-approval-flow"

    def test_create_item_rejects_retired_epic_field(self, client, test_db):
        """POST /v1/items rejects the retired epic field."""
        resp = client.post("/v1/items", json={
            "title": "Retired parent ref",
            "type": "issue",
            "epic": 3,
        })
        assert resp.status_code == 422
        data = resp.json()
        assert "extra_forbidden" in json.dumps(data)

    def test_create_item_missing_title(self, client):
        resp = client.post("/v1/items", json={
            "title": "",
            "type": "issue",
        })
        assert resp.status_code == 422
        data = resp.json()
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "title" in data["error"]["message"].lower()

    def test_create_item_title_too_long(self, client):
        """Title limit is 100 characters (matches TITLE_MAX_LENGTH)."""
        resp = client.post("/v1/items", json={
            "title": "x" * 101,
            "type": "issue",
        })
        assert resp.status_code == 422
        data = resp.json()
        assert data["error"]["code"] == "VALIDATION_ERROR"

    def test_create_item_title_at_limit(self, client, test_db):
        """Title at exactly 100 characters should succeed."""
        resp = client.post("/v1/items", json={
            "title": "x" * 100,
            "type": "issue",
        })
        assert resp.status_code == 201

    def test_create_item_invalid_type(self, client):
        resp = client.post("/v1/items", json={
            "title": "Valid title",
            "type": "task",
        })
        assert resp.status_code == 422
        data = resp.json()
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "task" in data["error"]["message"]

    def test_create_item_invalid_priority(self, client):
        resp = client.post("/v1/items", json={
            "title": "Valid title",
            "type": "issue",
            "priority": "urgent",
        })
        assert resp.status_code == 422
        data = resp.json()
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "urgent" in data["error"]["message"]

    def test_create_item_default_priority(self, client, test_db):
        """Omitting priority defaults to 'medium' via the mutation layer."""
        resp = client.post("/v1/items", json={
            "title": "Another idea",
            "type": "issue",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["priority"] == "medium"

    def test_create_item_rejects_unregistered_deployment_flow(self, client, test_db):
        """Unregistered non-empty deployment_flow values are rejected at create."""
        resp = client.post("/v1/items", json={
            "title": "Bad flow item",
            "type": "issue",
            "project": "yoke",
            "deployment_flow": "garbage",
        })
        assert resp.status_code == 422
        data = resp.json()
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "garbage" in data["error"]["message"]
        assert "is not registered" in data["error"]["message"]
        # Registered alternatives surfaced (test fixture seeds 'test-approval-flow').
        assert "test-approval-flow" in data["error"]["message"]

    def test_create_item_rejects_literal_none_string(self, client, test_db):
        """Literal string 'none' is rejected."""
        resp = client.post("/v1/items", json={
            "title": "Literal none",
            "type": "issue",
            "project": "yoke",
            "deployment_flow": "none",
        })
        assert resp.status_code == 422
        data = resp.json()
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "'none'" in data["error"]["message"]

    def test_create_item_empty_string_deployment_flow_passes(self, client, test_db):
        """Empty-string deployment_flow is treated as unset (no rejection)."""
        resp = client.post("/v1/items", json={
            "title": "Empty flow",
            "type": "issue",
            "project": "yoke",
            "deployment_flow": "",
        })
        assert resp.status_code == 201

    def test_create_item_null_sentinel_deployment_flow_passes(self, client, test_db):
        """String null deployment_flow is treated as unset."""
        resp = client.post("/v1/items", json={
            "title": "Null flow",
            "type": "issue",
            "project": "yoke",
            "deployment_flow": "null",
        })
        assert resp.status_code == 201
        assert resp.json()["deployment_flow"] is None

    def test_create_no_subprocess_called(self, client, test_db):
        """AC: POST /v1/items no longer shells out to backlog-registry.sh.

        Git invocations for path resolution (`worktree_paths._run` shelling
        out to `git rev-parse --show-toplevel` / `--git-common-dir` when
        resolving the canonical main checkout for
        `_canonical_yoke_db`) are unrelated to the AC — the AC's
        concern is the backlog tooling shell wrapper, not all
        subprocesses. Assert no backlog-tooling shellout specifically;
        permit git lookups.
        """
        with patch("yoke_core.api.main.subprocess.run") as mock_run:
            resp = client.post("/v1/items", json={
                "title": "Direct create",
                "type": "issue",
            })
        assert resp.status_code == 201
        non_git_calls = []
        for call in mock_run.call_args_list:
            argv = call.args[0] if call.args else call.kwargs.get("args")
            if not argv:
                continue
            head = argv[0] if isinstance(argv, (list, tuple)) else str(argv).split()[0]
            if head != "git":
                non_git_calls.append(argv)
        assert not non_git_calls, (
            f"backlog tooling shellout still present: {non_git_calls}"
        )
