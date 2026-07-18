"""Seed recipe and CLI tests for ``yoke_core.domain.project_structure``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

import pytest

from yoke_core.domain import project_structure as ps
from yoke_core.domain.schema_common import _table_exists
from runtime.api.fixtures.file_test_db import init_test_db
from runtime.api.project_structure_test_helpers import seed_project


@pytest.fixture
def db_path(tmp_path: Path):
    with init_test_db(tmp_path, apply_schema=lambda: None) as path:
        yield path


@pytest.fixture
def initialized_db(db_path: str) -> str:
    ps.cmd_init(db_path=db_path)
    seed_project(db_path, 1, "yoke", "Yoke", github_repo="org/yoke")
    seed_project(db_path, 2, "externalwebapp", "ExternalWebapp", github_repo="org/externalwebapp")
    seed_project(db_path, 100, "fresh", "Fresh", github_repo="org/fresh")
    return db_path


def _put(family, attachment, payload, *, entry_key="", attachment_kind=""):
    op = {"op": "put", "family": family, "attachment": attachment, "payload": payload}
    if entry_key:
        op["entry_key"] = entry_key
    if attachment_kind:
        op["attachment_kind"] = attachment_kind
    return op


class TestSeed:
    # Families whose seeded entries are optional per-project.
    # ``deploy_defaults`` is optional because a project may legitimately have
    # no project-level deployment default; callers treat absence as a valid
    # "no project default" state.
    # ``merge_verification`` is optional because absence is the documented
    # default for both seeded projects: the merge engine emits an explicit
    # "no merge policy configured" log line and skips project tests at
    # merge time. Operators configure a command and timeout explicitly via
    # ``python3 -m yoke_core.domain.merge_verification set <project>
    # <command> --timeout-seconds <seconds>`` when they want a merge gate.
    # ``architecture_model`` is in the optional set until Slice 6
    # authors the concrete yoke architecture_model.payload seed; AC-2 lands
    # there alongside the AGENTS.md architecture-model documentation surface.
    _SEED_COVERAGE_OPTIONAL = {
        "deploy_defaults", "merge_verification", "architecture_model",
    }

    def test_seed_yoke_populates_every_required_net_new_family(
        self, initialized_db: str
    ):
        ps.cmd_seed("yoke", db_path=initialized_db)
        structure = ps.read_structure("yoke", db_path=initialized_db)
        for family in ps.NET_NEW_FAMILIES:
            if family in self._SEED_COVERAGE_OPTIONAL:
                continue
            assert structure["families"][family], (
                f"Net-new family '{family}' was not seeded for yoke"
            )

    def test_yoke_command_definitions_scope_coverage(self, initialized_db: str):
        """Yoke seeds ``full`` with the canonical local verification target.
        ``quick``, ``e2e``, and ``smoke`` are intentionally absent today and
        are exercised by the validator as ``empty`` rather than ``invalid``.
        """
        ps.cmd_seed("yoke", db_path=initialized_db)
        structure = ps.read_structure("yoke", family="command_definitions",
                                      db_path=initialized_db)
        scopes = {e["entry_key"] for e in structure["entries"]}
        assert scopes == {"full"}
        full_entry = next(e for e in structure["entries"]
                          if e["entry_key"] == "full")
        assert full_entry["payload"] == {
            "command": (
                "python3 -m yoke_core.tools.watch_pytest -- "
                "runtime/api/ runtime/harness/ tests/"
            ),
        }

    def test_yoke_seeds_deploy_defaults(self, initialized_db: str):
        """Yoke ships with a `deploy_defaults` entry pointing at its
        internal delivery flow. Other projects may legitimately have no
        entry — the helper returns None in that case."""
        ps.cmd_seed("yoke", db_path=initialized_db)
        structure = ps.read_structure(
            "yoke", family="deploy_defaults", db_path=initialized_db
        )
        assert len(structure["entries"]) == 1
        assert structure["entries"][0]["payload"] == {
            "deployment_flow": "yoke-internal"
        }

    def test_external_project_has_no_source_owned_seed(self, initialized_db: str):
        with pytest.raises(ps.UsageError, match="Known seeds: yoke"):
            ps.cmd_seed("externalwebapp", db_path=initialized_db)

    def test_seed_populates_context_routing(self, initialized_db: str):
        """Seed materializes Yoke's project-wide context entry."""
        ps.cmd_seed("yoke", db_path=initialized_db)
        yoke_cr = ps.read_structure("yoke", family="context_routing",
                                      db_path=initialized_db)
        yoke_keys = {e["entry_key"] for e in yoke_cr["entries"]}
        assert "always" in yoke_keys

    def test_seed_is_idempotent(self, initialized_db: str):
        ps.cmd_seed("yoke", db_path=initialized_db)
        second = ps.cmd_seed("yoke", db_path=initialized_db)
        assert second["applied_ops"] == []

    def test_seed_unknown_project_errors(self, initialized_db: str):
        with pytest.raises(ps.UsageError, match="No frozen seed recipe"):
            ps.cmd_seed("nonexistent", db_path=initialized_db)

    def test_seed_dogfoods_apply_patch_contract(self, initialized_db: str):
        """Seed goes through apply_patch, so structure rows exist post-seed.

        The invariant is that seed flowed through ``apply_patch`` and
        persisted entries in ``project_structure``.
        """
        ps.cmd_seed("yoke", db_path=initialized_db)
        from yoke_core.domain.db_helpers import connect
        conn = connect(initialized_db)
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM project_structure "
                "WHERE project_id=1"
            ).fetchone()[0]
        finally:
            conn.close()
        assert count > 0


class TestCli:
    def _run(self, argv: List[str], monkeypatch, db_path: str) -> int:
        monkeypatch.setenv("YOKE_DB", db_path)
        return ps.main(argv)

    def test_init_subcommand_creates_tables(self, db_path: str, monkeypatch):
        rc = self._run(["init"], monkeypatch, db_path)
        assert rc == 0
        from yoke_core.domain.db_helpers import connect
        conn = connect(db_path)
        try:
            exists = _table_exists(conn, "project_structure")
        finally:
            conn.close()
        assert exists

    def test_family_list_prints_registry(self, initialized_db: str, monkeypatch, capsys):
        rc = self._run(["family-list"], monkeypatch, initialized_db)
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert set(data["net_new"]) == set(ps.NET_NEW_FAMILIES)
        assert set(data) == {
            "net_new",
            "attachment_branches",
            "path_selector_kinds",
            "multiplicities",
        }

    def test_get_prints_empty_structure_for_new_project(
        self, initialized_db: str, monkeypatch, capsys
    ):
        rc = self._run(["get", "fresh"], monkeypatch, initialized_db)
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["project_id"] == "fresh"

    def test_patch_via_ops_file(
        self, initialized_db: str, monkeypatch, capsys, tmp_path: Path
    ):
        ops_path = tmp_path / "ops.json"
        ops_path.write_text(json.dumps({
            "ops": [_put("areas", "project", {"description": "x"}, entry_key="a")],
        }))
        rc = self._run(
            ["patch", "fresh", "--ops-file", str(ops_path)],
            monkeypatch, initialized_db,
        )
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert len(data["applied_ops"]) == 1

    def test_seed_cli_is_idempotent(
        self, initialized_db: str, monkeypatch, capsys
    ):
        rc1 = self._run(["seed", "yoke"], monkeypatch, initialized_db)
        assert rc1 == 0
        rc2 = self._run(["seed", "yoke"], monkeypatch, initialized_db)
        assert rc2 == 0
        # Second output signals the noop.
        out = capsys.readouterr().out
        # Parse the concatenated output and confirm the second call is a no-op.
        blocks = [json.loads(b) for b in _split_json_blocks(out)]
        assert blocks[-1]["applied_ops"] == []


def _split_json_blocks(text: str) -> List[str]:
    """Split a stream of concatenated top-level JSON objects into blocks.

    ``capsys`` captures both calls into a single ``out`` stream; each call
    prints one top-level JSON object.  We split on the balanced-brace
    boundary so each block can be parsed independently.
    """
    blocks: List[str] = []
    depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                blocks.append(text[start : i + 1])
                start = None
    return blocks
