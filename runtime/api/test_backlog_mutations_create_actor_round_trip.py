"""End-to-end ``execute_create`` coverage for the actor-id write path.

Slice 5b split these cases out of
``test_backlog_mutations_create.py`` once that module crossed the
file-line budget. The test responsibilities are deliberately narrow:
verify that the full ``execute_create`` pipeline (mutation validation
+ INSERT + post-write reads) writes ``items.source`` and
``items.owner`` as stringified ``actors.id`` values and rejects
operator-supplied mechanism labels at the API surface.

Helper imports stay aligned with the parent test module so the
fixture/mocking shape remains canonical — only the test methods move.
"""

from __future__ import annotations

import io
import os
from unittest import mock

from runtime.api.backlog_mutations_test_helpers import (
    _item_field,
    _patch_externals,
    tmp_db,  # noqa: F401 — re-exported fixture
)
from yoke_core.domain import backlog
from yoke_core.domain.ticket_intake_provenance import IDEA_INTAKE_ENV


class TestExecuteCreateActorRoundTrip:
    def test_create_writes_actor_id_for_source_and_owner(self, tmp_db):
        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db, IDEA_INTAKE_ENV: "1"}):
            result = backlog.execute_create(
                title="Actor-id round trip",
                item_type="issue",
                out=out,
            )
        assert result["success"] is True
        source = _item_field(tmp_db, result["item_id"], "source")
        owner = _item_field(tmp_db, result["item_id"], "owner")
        # Resolver pulled the seeded local human; both columns hold the
        # same stringified actor id (owner defaults to source).
        assert source.isdigit(), f"source={source!r} must be a numeric actor id"
        assert owner == source

    def test_create_rejects_mechanism_label_source(self, tmp_db):
        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db, IDEA_INTAKE_ENV: "1"}):
            result = backlog.execute_create(
                title="Mechanism label",
                item_type="issue",
                source="user",
                out=out,
            )
        assert result["success"] is False
        assert "must be a numeric actor id" in result["error"]
