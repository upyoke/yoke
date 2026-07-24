"""Tests for the evidence-building coordination-decision helper.

These tests pin the **packet shape**, not a decision oracle. Per
AC-15 / FR-6, the LLM agent owns the final coordination call; the
helper only assembles evidence. Tests that map (candidate, conflicting,
paths) input to a specific decision output are explicitly forbidden by
the task spec.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain import path_claim_coordination_decision as pccd
from yoke_core.domain.items_writes import insert_item, update_structured_field
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _seed_item_with_spec(
    db_path: str, item_id: int, title: str, spec: str,
) -> None:
    insert_item(item_id=item_id, title=title, db_path=db_path)
    if spec:
        update_structured_field(item_id, "spec", spec, db_path=db_path)


def _seed_path_target(
    conn,
    *,
    path_string: str,
    kind: str = "file",
    parent_target_id: int | None = None,
    generation: int = 1,
) -> int:
    p = _p(conn)
    cur = conn.execute(
        "INSERT INTO path_targets "
        "(project_id, kind, path_string, generation, parent_target_id, "
        "created_at) "
        f"VALUES (1, {p}, {p}, {p}, {p}, '2026-05-01T00:00:00Z') "
        "RETURNING id",
        (kind, path_string, generation, parent_target_id),
    )
    return int(cur.fetchone()[0])


def _seed_claim(
    conn, *, item_id: int,
    integration_target: str = "main", state: str = "active",
) -> int:
    if conn.execute("SELECT id FROM actors WHERE id = 1").fetchone() is None:
        conn.execute("INSERT INTO actors (id, name, kind, created_at) "
                     "VALUES (1, 'yoke', 'system', '2026-05-01T00:00:00Z')")
    p = _p(conn)
    cur = conn.execute(
        "INSERT INTO path_claims "
        "(state, mode, actor_id, item_id, integration_target, registered_at) "
        f"VALUES ({p}, 'exclusive', 1, {p}, {p}, '2026-05-01T00:00:00Z') "
        "RETURNING id",
        (state, item_id, integration_target),
    )
    conn.commit()
    return int(cur.fetchone()[0])


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict]:
    """Initialise a backend-appropriate Yoke DB and bind YOKE_DB env."""
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        conn = connect_test_db(db_path)
        yield {"db_path": db_path, "conn": conn}
        conn.close()


# ----- packet shape -----------------------------------------------------------


def test_build_coordination_context_returns_typed_dict_keys(env):
    conn = env["conn"]
    _seed_item_with_spec(env["db_path"], 100, "Candidate", "candidate spec")
    _seed_item_with_spec(env["db_path"], 200, "Conflicting", "conflicting spec")
    _seed_path_target(conn, path_string="AGENTS.md")
    claim_id = _seed_claim(conn, item_id=200)

    ctx = pccd.build_coordination_context(
        conn,
        candidate_item_id=100,
        conflicting_claim_id=claim_id,
        shared_paths=["AGENTS.md"],
    )

    expected_keys = {
        "candidate_item_id", "candidate_spec",
        "conflicting_claim_id", "conflicting_item_id",
        "conflicting_item_spec", "conflicting_claim_state",
        "shared_paths", "shared_path_metadata",
        "suggested_commands", "decision_options",
        "rationale_checklist",
    }
    assert set(ctx.keys()) == expected_keys
    assert ctx["candidate_item_id"] == 100
    assert ctx["conflicting_item_id"] == 200
    assert ctx["conflicting_claim_state"] == "active"
    assert ctx["decision_options"] == ["coordination_only", "directional", "escalate"]


def test_build_coordination_context_spec_truncation(env):
    conn = env["conn"]
    big_spec = "X" * 10_000
    _seed_item_with_spec(env["db_path"], 110, "Big candidate", big_spec)
    _seed_item_with_spec(env["db_path"], 210, "Other", "small")
    _seed_path_target(conn, path_string="AGENTS.md")
    claim_id = _seed_claim(conn, item_id=210)

    ctx = pccd.build_coordination_context(
        conn,
        candidate_item_id=110,
        conflicting_claim_id=claim_id,
        shared_paths=["AGENTS.md"],
    )

    assert len(ctx["candidate_spec"]) <= 4096
    assert ctx["candidate_spec"] == "X" * 4096


def test_build_coordination_context_shared_path_metadata(env):
    conn = env["conn"]
    _seed_item_with_spec(env["db_path"], 120, "A", "a")
    _seed_item_with_spec(env["db_path"], 220, "B", "b")
    parent = _seed_path_target(conn, path_string="docs", kind="directory")
    _seed_path_target(
        conn, path_string=".yoke/docs/lifecycle.md",
        kind="file", parent_target_id=parent,
    )
    _seed_path_target(conn, path_string="AGENTS.md")
    claim_id = _seed_claim(conn, item_id=220)

    ctx = pccd.build_coordination_context(
        conn,
        candidate_item_id=120,
        conflicting_claim_id=claim_id,
        shared_paths=["AGENTS.md", ".yoke/docs/lifecycle.md", "no/such/path"],
    )

    md = ctx["shared_path_metadata"]
    assert len(md) == 3
    assert {entry["path"] for entry in md} == {
        "AGENTS.md", ".yoke/docs/lifecycle.md", "no/such/path",
    }
    for entry in md:
        assert set(entry.keys()) == {"path", "kind", "lineage_depth"}
    unknown_entry = next(e for e in md if e["path"] == "no/such/path")
    assert unknown_entry["kind"] == "unknown"
    assert unknown_entry["lineage_depth"] == 0
    nested = next(e for e in md if e["path"] == ".yoke/docs/lifecycle.md")
    assert nested["lineage_depth"] >= 1
    assert nested["kind"] == "file"


def test_build_coordination_context_suggested_commands_include_all_decision_options(env):
    conn = env["conn"]
    _seed_item_with_spec(env["db_path"], 130, "Cand", "c")
    _seed_item_with_spec(env["db_path"], 230, "Other", "o")
    _seed_path_target(conn, path_string="AGENTS.md")
    claim_id = _seed_claim(conn, item_id=230)

    ctx = pccd.build_coordination_context(
        conn,
        candidate_item_id=130,
        conflicting_claim_id=claim_id,
        shared_paths=["AGENTS.md"],
    )

    cmds = ctx["suggested_commands"]
    assert len(cmds) >= 3
    cand_token = "YOK-130"
    other_token = "YOK-230"
    has_coordination = any(
        "--gate-point coordination_only" in c for c in cmds)
    has_activation = any(
        "--gate-point activation" in c and "fact:merged" in c for c in cmds)
    has_escalate = any("path-claim-override" in c for c in cmds)
    assert has_coordination
    assert has_activation
    assert has_escalate
    # The dependency-add commands name both items and include the candidate id.
    dep_add_lines = [c for c in cmds if "dependency-add" in c]
    assert all(cand_token in c for c in dep_add_lines)
    assert all(other_token in c for c in dep_add_lines)
    # Escalate line names the candidate.
    override_lines = [c for c in cmds if "path-claim-override" in c]
    assert all(cand_token in c for c in override_lines)


def test_suggested_commands_rationale_distinguishes_independence_from_directional(env):
    """AC-2 / AC-4: rationale templates per option name the required evidence
    and the rationale_checklist names the same required fields."""
    conn = env["conn"]
    _seed_item_with_spec(env["db_path"], 131, "Cand", "c")
    _seed_item_with_spec(env["db_path"], 231, "Other", "o")
    _seed_path_target(conn, path_string=".yoke/docs/lifecycle.md")
    claim_id = _seed_claim(conn, item_id=231)
    ctx = pccd.build_coordination_context(
        conn, candidate_item_id=131,
        conflicting_claim_id=claim_id,
        shared_paths=[".yoke/docs/lifecycle.md"],
    )
    cmds = ctx["suggested_commands"]
    coord_cmd = next(c for c in cmds if "--gate-point coordination_only" in c)
    activation_cmd = next(
        c for c in cmds if "--gate-point activation" in c
        and "fact:merged" in c)
    for token in ("decision=coordination_only", "independence_evidence",
                  ".yoke/docs/lifecycle.md", f"conflicting_claim_id={claim_id}"):
        assert token in coord_cmd
    for token in ("decision=directional", "why_order_matters",
                  ".yoke/docs/lifecycle.md", f"conflicting_claim_id={claim_id}"):
        assert token in activation_cmd
    checklist = ctx["rationale_checklist"]
    assert isinstance(checklist, list) and len(checklist) >= 4
    joined = "\n".join(checklist)
    for token in ("decision=", "shared_paths", "conflicting_claim_id",
                  "independence_evidence", "why_order_matters"):
        assert token in joined


# ----- existence / sparse-spec semantics --------------------------------------


def test_build_coordination_context_missing_item_raises_value_error(env):
    conn = env["conn"]
    _seed_item_with_spec(env["db_path"], 240, "Other", "o")
    _seed_path_target(conn, path_string="AGENTS.md")
    claim_id = _seed_claim(conn, item_id=240)

    missing_id = 99_999
    with pytest.raises(ValueError, match=str(missing_id)):
        pccd.build_coordination_context(
            conn,
            candidate_item_id=missing_id,
            conflicting_claim_id=claim_id,
            shared_paths=["AGENTS.md"],
        )


def test_build_coordination_context_empty_spec_passes_through(env):
    conn = env["conn"]
    # Insert the candidate without writing a spec.
    insert_item(item_id=150, title="Sparse candidate", db_path=env["db_path"])
    _seed_item_with_spec(env["db_path"], 250, "Other", "o")
    _seed_path_target(conn, path_string="AGENTS.md")
    claim_id = _seed_claim(conn, item_id=250)

    ctx = pccd.build_coordination_context(
        conn,
        candidate_item_id=150,
        conflicting_claim_id=claim_id,
        shared_paths=["AGENTS.md"],
    )
    assert ctx["candidate_spec"] == ""
