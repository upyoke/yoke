"""Family-specific tests for ``yoke_core.domain.project_structure``.

``command_definitions`` concretization, ``context_routing`` concretization,
write/read round-trip, and atomicity.

Constitution invariants and envelope validation live in
``test_project_structure.py``; seed recipe and CLI tests live in
``test_project_structure_seed_cli.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterator

import pytest

from yoke_core.domain import project_structure as ps
from runtime.api.fixtures.file_test_db import init_test_db
from runtime.api.project_structure_test_helpers import seed_project


def _apply_project_structure_schema() -> None:
    """``init_test_db`` strategy: ``ps.cmd_init`` owns the only DDL and resolves
    its own backend connection; plain ``CREATE TABLE IF NOT EXISTS`` so the
    Postgres facade builds it directly (no introspection shims)."""
    ps.cmd_init()


@pytest.fixture
def initialized_db(tmp_path: Path) -> Iterator[str]:
    """Per-test DB with the ``project_structure`` schema. On Postgres
    ``init_test_db`` gives each test a disposable database; the legacy
    ``ps.cmd_init(db_path=...)`` shared one DB module-wide and leaked rows."""
    with init_test_db(tmp_path, apply_schema=_apply_project_structure_schema) as path:
        seed_project(path, 100, "test")
        yield path


def _put(family, attachment, payload, *, entry_key="", attachment_kind=""):
    op = {"op": "put", "family": family, "attachment": attachment, "payload": payload}
    if entry_key:
        op["entry_key"] = entry_key
    if attachment_kind:
        op["attachment_kind"] = attachment_kind
    return op


def _remove(family, attachment, *, entry_key=""):
    op = {"op": "remove", "family": family, "attachment": attachment}
    if entry_key:
        op["entry_key"] = entry_key
    return op


class TestContextRoutingFamily:
    @pytest.mark.parametrize("entry_key", ["always", "backend"])
    def test_put_entry_accepted(self, initialized_db: str, entry_key: str):
        """Both the reserved ``always`` key and arbitrary topic names accept
        a non-empty ``docs`` list payload."""
        result = ps.apply_patch(
            "test",
            ops=[_put("context_routing", "project",
                      {"docs": ["AGENTS.md", "docs/OVERVIEW.md"]},
                      entry_key=entry_key)],
            db_path=initialized_db,
        )
        slice_ = ps.read_structure("test", family="context_routing", db_path=initialized_db)
        assert slice_["entries"][0]["entry_key"] == entry_key
        assert slice_["entries"][0]["payload"]["docs"] == [
            "AGENTS.md", "docs/OVERVIEW.md",
        ]

    @pytest.mark.parametrize("payload,match", [
        ({}, "'docs' list"),
        ({"docs": []}, "'docs' list"),
        ({"docs": ["AGENTS.md", 42]}, "must be a non-empty string"),
    ])
    def test_payload_validation_rejects(self, initialized_db, payload, match):
        with pytest.raises(ps.ValidationError, match=match):
            ps.apply_patch(
                "test", ops=[_put("context_routing", "project", payload, entry_key="always")],
                db_path=initialized_db,
            )

    def test_keyed_set_rejects_missing_entry_key(self, initialized_db: str):
        with pytest.raises(ps.ValidationError, match="entry_key is required"):
            ps.apply_patch(
                "test", ops=[_put("context_routing", "project", {"docs": ["AGENTS.md"]})],
                db_path=initialized_db,
            )


class TestCommandDefinitionsFamily:
    def test_put_accepts_valid_scope(self, initialized_db: str):
        result = ps.apply_patch(
            "test",
            ops=[_put("command_definitions", "project",
                      {"command": "pytest tests/"}, entry_key="quick")],
            db_path=initialized_db,
        )
        structure = ps.read_structure("test", family="command_definitions",
                                      db_path=initialized_db)
        assert len(structure["entries"]) == 1
        assert structure["entries"][0]["entry_key"] == "quick"
        assert structure["entries"][0]["payload"] == {"command": "pytest tests/"}

    @pytest.mark.parametrize("scope", list(ps.COMMAND_DEFINITIONS_SCOPES))
    def test_every_canonical_scope_is_accepted(self, initialized_db: str, scope: str):
        result = ps.apply_patch(
            "test",
            ops=[_put("command_definitions", "project",
                      {"command": f"cmd-for-{scope}"}, entry_key=scope)],
            db_path=initialized_db,
        )

    def test_unknown_scope_rejected(self, initialized_db: str):
        with pytest.raises(ps.ValidationError, match="entry_key must be one of"):
            ps.apply_patch(
                "test",
                ops=[_put("command_definitions", "project",
                          {"command": "cmd"}, entry_key="integration")],
                db_path=initialized_db,
            )

    def test_payload_must_contain_command_string(self, initialized_db: str):
        with pytest.raises(ps.ValidationError, match="'command' string"):
            ps.apply_patch(
                "test",
                ops=[_put("command_definitions", "project",
                          {}, entry_key="quick")],
                db_path=initialized_db,
            )

    def test_payload_rejects_non_string_command(self, initialized_db: str):
        with pytest.raises(ps.ValidationError, match="'command' string"):
            ps.apply_patch(
                "test",
                ops=[_put("command_definitions", "project",
                          {"command": 42}, entry_key="full")],
                db_path=initialized_db,
            )


class TestWriteReadRoundTrip:
    def test_first_put(self, initialized_db: str):
        result = ps.apply_patch(
            "test",
            ops=[_put("areas", "project", {"description": "core area"}, entry_key="core")],
            db_path=initialized_db,
        )
        structure = ps.read_structure("test", db_path=initialized_db)
        areas = structure["families"]["areas"]
        assert len(areas) == 1
        assert areas[0]["entry_key"] == "core"
        assert areas[0]["payload"] == {"description": "core area"}

    def test_put_creates_then_updates_same_identity(self, initialized_db: str):
        ps.apply_patch(
            "test",
            ops=[_put("areas", "project", {"description": "v1"}, entry_key="core")],
            db_path=initialized_db,
        )
        ps.apply_patch(
            "test",
            ops=[_put("areas", "project", {"description": "v2"}, entry_key="core")],
            db_path=initialized_db,
        )
        structure = ps.read_structure("test", db_path=initialized_db)
        entries = structure["families"]["areas"]
        assert len(entries) == 1  # update, not a second entry
        assert entries[0]["payload"] == {"description": "v2"}

    def test_remove_deletes_entry(self, initialized_db: str):
        ps.apply_patch(
            "test",
            ops=[_put("areas", "project", {"description": "x"}, entry_key="k")],
            db_path=initialized_db,
        )
        result = ps.apply_patch(
            "test",
            ops=[_remove("areas", "project", entry_key="k")],
            db_path=initialized_db,
        )
        structure = ps.read_structure("test", db_path=initialized_db)
        assert structure["families"]["areas"] == []

    def test_remove_nonexistent_entry_errors(self, initialized_db: str):
        with pytest.raises(ps.ValidationError, match="Cannot remove nonexistent"):
            ps.apply_patch(
                "test",
                ops=[_remove("areas", "project", entry_key="missing")],
                db_path=initialized_db,
            )

    def test_family_slice_matches_whole_structure(self, initialized_db: str):
        ps.apply_patch(
            "test",
            ops=[_put("areas", "project", {"description": "a"}, entry_key="a")],
            db_path=initialized_db,
        )
        whole = ps.read_structure("test", db_path=initialized_db)
        slice_ = ps.read_structure("test", family="areas", db_path=initialized_db)
        assert whole["families"]["areas"] == slice_["entries"]


class TestAtomicity:
    def test_all_ops_fail_if_any_op_fails(self, initialized_db: str):
        """If the second op has an invalid envelope, the first must not land."""
        with pytest.raises(ps.ValidationError):
            ps.apply_patch(
                "test",
                ops=[
                    _put("areas", "project", {"description": "ok"}, entry_key="ok"),
                    _put("areas", "wrong/attachment", {"description": "bad"}, entry_key="bad"),
                ],
                db_path=initialized_db,
            )
        structure = ps.read_structure("test", db_path=initialized_db)
        assert structure["families"]["areas"] == []

    def test_multi_op_request_persists_every_entry(self, initialized_db: str):
        ops = [
            _put("areas", "project", {"description": "a"}, entry_key="a"),
            _put("areas", "project", {"description": "b"}, entry_key="b"),
            _put("areas", "project", {"description": "c"}, entry_key="c"),
        ]
        ps.apply_patch(
            "test", ops=ops, db_path=initialized_db,
        )
        structure = ps.read_structure("test", db_path=initialized_db)
        assert [e["entry_key"] for e in structure["families"]["areas"]] == [
            "a",
            "b",
            "c",
        ]


def _minimal_architecture_model() -> Dict[str, Any]:
    """Build a minimal valid architecture_model payload for round-trips."""
    return {
        "edge_semantics": "explicit_only",
        "domains": [
            {"id": "claims", "path_roots": ["runtime/api/domain/path_claims*.py"]},
        ],
        "layers": [
            {"id": "schema_storage",
             "may_depend_on": [],
             "forbidden_edges": ["orchestration"]},
            {"id": "orchestration",
             "may_depend_on": ["schema_storage"],
             "forbidden_edges": []},
        ],
        "cross_cutting_entrypoints": {
            "db_path": {
                "approved_modules": [
                    "yoke_core.domain.db_helpers",
                    "yoke_core.cli.db_router",
                ],
            },
        },
    }


def _mutate(payload: Dict[str, Any], mutate) -> Dict[str, Any]:
    mutate(payload)
    return payload


class TestArchitectureModelFamily:
    """``architecture_model`` is a project-attached singleton; payload
    validation enforces domains, layers, layer cross-refs, and the
    cross-cutting entrypoint registry shape."""

    def test_round_trip_minimal_payload(self, initialized_db: str):
        payload = _minimal_architecture_model()
        ps.apply_patch(
            "test",
            ops=[_put("architecture_model", "project", payload)],
            db_path=initialized_db,
        )
        slice_ = ps.read_structure(
            "test", family="architecture_model", db_path=initialized_db,
        )
        assert len(slice_["entries"]) == 1
        assert slice_["entries"][0]["payload"] == payload

    def test_singleton_rejects_entry_key(self, initialized_db: str):
        with pytest.raises(ps.ValidationError, match="singleton"):
            ps.apply_patch(
                "test",
                ops=[_put("architecture_model", "project",
                          _minimal_architecture_model(),
                          entry_key="extra")],
                db_path=initialized_db,
            )

    @pytest.mark.parametrize("mutate,match", [
        (lambda p: p.pop("domains"), "non-empty 'domains' list"),
        (lambda p: p.pop("layers"), "non-empty 'layers' list"),
        (lambda p: p.pop("cross_cutting_entrypoints"),
         "non-empty 'cross_cutting_entrypoints' object"),
        (lambda p: p["domains"].append(
            {"id": "claims", "path_roots": ["x"]}),
         "duplicate domain id"),
        (lambda p: p["layers"].append(
            {"id": "schema_storage", "may_depend_on": [], "forbidden_edges": []}),
         "duplicate layer id"),
        (lambda p: p["layers"][1]["may_depend_on"].append("ghost"),
         "references unknown layer"),
        (lambda p: p["cross_cutting_entrypoints"].__setitem__(
            "db_path", {"approved_modules": []}),
         "non-empty 'approved_modules' list"),
        (lambda p: p["cross_cutting_entrypoints"]["db_path"].__setitem__(
            "guarded_imports", ["sqlite3."]),
         "module.symbol"),
    ])
    def test_payload_validation_rejects(
        self, initialized_db: str, mutate, match,
    ):
        payload = _mutate(_minimal_architecture_model(), mutate)
        with pytest.raises(ps.ValidationError, match=match):
            ps.apply_patch(
                "test",
                ops=[_put("architecture_model", "project", payload)],
                db_path=initialized_db,
            )

    def test_approved_module_prefixes_optional(self, initialized_db: str):
        payload = _minimal_architecture_model()
        payload["cross_cutting_entrypoints"]["db_path"][
            "approved_module_prefixes"
        ] = ["yoke_core.domain.db_helpers_"]
        payload["cross_cutting_entrypoints"]["db_path"][
            "guarded_imports"
        ] = ["sqlite3.connect"]
        ps.apply_patch(
            "test",
            ops=[_put("architecture_model", "project", payload)],
            db_path=initialized_db,
        )

    def test_derive_edges_projects_layer_source(self):
        """``derive_edges`` exposes flat (from, to) tuples for HC use."""
        from yoke_core.domain.architecture_model import derive_edges

        payload = _minimal_architecture_model()
        allowed, forbidden = derive_edges(payload)
        assert ("orchestration", "schema_storage") in allowed
        assert ("schema_storage", "orchestration") in forbidden
