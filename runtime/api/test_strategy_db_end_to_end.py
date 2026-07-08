"""End-to-end coverage for the per-project strategy DB authority.

The full operator story through the REAL surfaces — no dispatch stubs:
the ``yoke`` CLI entrypoint builds envelopes (explicit ``--project``),
the real dispatcher binds identity and permissions, the real handlers
hit a disposable Postgres seeded with the shared strategy-doc fixture
corpus (the DB is the corpus authority; rendered ``.yoke/strategy``
views are local-only and untracked, so no checkout files are read),
renders land in a real git checkout, ingest CAS round-trips against
real files, the claim interplay (replace claim-gated, ingest
foreign-claim-bounced) plays out across two sessions, real
``StrategyDocReplaced`` events land in the events table with their
``source`` markers, and the staleness HC closes the loop.
"""

from __future__ import annotations

import io
import json
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_cli.main import main as cli_main
from yoke_core.domain import strategy_docs as sd
from yoke_core.domain.agents_render_workspace import RENDER_TARGET_ROOT_ENV_VAR
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.handlers._strategy_docs_test_helpers import (
    SEED_CONTENT,
    SEED_SLUGS,
    seed_docs,
    seed_session,
)
from yoke_core.domain.strategy_docs_header import parse_file_text
from yoke_core.domain.strategy_docs_paths import strategy_view_path
from yoke_core.domain.yoke_function_registry import reset_registry_for_tests
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

OPERATOR = "e2e-operator"
OTHER = "e2e-other-session"
PROJECT = 1  # the Yoke project in the schema seed

# The shared fixture corpus is body-only content, matching what real
# ingest stores (``parse_file_text(text).body``).
CORPUS_SLUGS = SEED_SLUGS


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Disposable Postgres + repo-file-seeded rows + a real git checkout."""
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        reset_registry_for_tests()
        register_all_handlers()
        conn = connect_test_db(db_path)
        try:
            seed_docs(conn)
            seed_session(conn, OPERATOR)
            seed_session(conn, OTHER)
        finally:
            conn.close()
        checkout = tmp_path / "checkout"
        checkout.mkdir()
        subprocess.run(["git", "init", "-q", str(checkout)], check=True, timeout=10)
        # Pin render anchor to the checkout — no real-repo pollution (see commit).
        monkeypatch.setenv(RENDER_TARGET_ROOT_ENV_VAR, str(checkout))
        yield SimpleNamespace(db=db_path, checkout=checkout)


def _cli(*argv: str, session_id: str = OPERATOR) -> tuple:
    out, err = io.StringIO(), io.StringIO()
    env = {"YOKE_SESSION_ID": session_id}
    with pytest.MonkeyPatch.context() as mp:
        for key, value in env.items():
            mp.setenv(key, value)
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli_main([*argv, "--project", str(PROJECT)])
    return rc, out.getvalue(), err.getvalue()


def _envelope(*argv: str, session_id: str = OPERATOR) -> dict:
    _, stdout, stderr = _cli(*argv, "--json", session_id=session_id)
    text = stdout if stdout.strip() else stderr
    return json.loads(text[text.index("{"):])


def _claims_cli(*argv: str, session_id: str = OPERATOR) -> dict:
    """Claims commands take no --project flag; dispatch them bare."""
    out, err = io.StringIO(), io.StringIO()
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("YOKE_SESSION_ID", session_id)
        with redirect_stdout(out), redirect_stderr(err):
            cli_main([*argv, "--json"])
    text = out.getvalue() if out.getvalue().strip() else err.getvalue()
    return json.loads(text[text.index("{"):])


def _row(db_path: str, slug: str) -> dict:
    conn = connect_test_db(db_path)
    try:
        row = conn.execute(
            f"SELECT content, updated_at FROM {sd.STRATEGY_DOCS_TABLE} "
            "WHERE project_id = %s AND slug = %s",
            (PROJECT, slug),
        ).fetchone()
    finally:
        conn.close()
    return {"content": str(row["content"]), "updated_at": str(row["updated_at"])}


def _replaced_event_envelopes(db_path: str) -> list:
    conn = connect_test_db(db_path)
    try:
        rows = conn.execute(
            "SELECT envelope FROM events "
            "WHERE event_name = 'StrategyDocReplaced' ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    return [str(r["envelope"]) for r in rows]


def _edit_body(checkout: Path, slug: str, new_body: str) -> None:
    path = strategy_view_path(checkout, slug)
    first_line, _, _ = path.read_text(encoding="utf-8").partition("\n")
    path.write_text(first_line + "\n" + new_body, encoding="utf-8")


def test_operator_lifecycle_end_to_end(world, tmp_path: Path) -> None:
    db, checkout = world.db, world.checkout
    root = str(checkout)

    # 1. The seed put the fixture corpus in as body-only content
    #    (matching real ingest); CLI lists them.
    rc, stdout, _ = _cli("strategy", "doc", "list")
    assert rc == 0
    for slug in CORPUS_SLUGS:
        assert slug in stdout
    assert _row(db, "MISSION")["content"] == SEED_CONTENT["MISSION"]

    # 2. Render writes headered views; bodies byte-match the DB rows.
    rc, _, _ = _cli("strategy", "render", "--target-root", root)
    assert rc == 0
    for slug in CORPUS_SLUGS:
        parsed = parse_file_text(
            strategy_view_path(checkout, slug).read_text(encoding="utf-8")
        )
        assert parsed.slug == slug
        assert parsed.body == _row(db, slug)["content"]

    # 3. Re-render is byte-idempotent (no wall-clock anywhere).
    before = {
        s: strategy_view_path(checkout, s).read_bytes() for s in CORPUS_SLUGS
    }
    rc, _, _ = _cli("strategy", "render", "--target-root", root)
    assert rc == 0
    after = {
        s: strategy_view_path(checkout, s).read_bytes() for s in CORPUS_SLUGS
    }
    assert before == after

    # 4. Operator edits PAD in their "editor"; dry-run previews, writes
    #    nothing; wet ingest CAS-writes, re-renders, emits source=ingest.
    pad_base = _row(db, "PAD")
    edited = pad_base["content"] + "\nE2E pen edit.\n"
    _edit_body(checkout, "PAD", edited)
    rc, stdout, _ = _cli(
        "strategy", "ingest", "PAD", "--dry-run", "--target-root", root,
    )
    assert rc == 0 and "changed" in stdout
    assert _row(db, "PAD") == pad_base
    rc, stdout, _ = _cli("strategy", "ingest", "PAD", "--target-root", root)
    assert rc == 0 and "written" in stdout
    pad_now = _row(db, "PAD")
    assert pad_now["content"] == edited
    parsed = parse_file_text(
        strategy_view_path(checkout, "PAD").read_text(encoding="utf-8")
    )
    assert parsed.updated_at == pad_now["updated_at"]  # header advanced
    rc, stdout, _ = _cli("strategy", "ingest", "PAD", "--target-root", root)
    assert rc == 0 and "unchanged" in stdout  # re-run no-ops
    assert any('"source": "ingest"' in e for e in _replaced_event_envelopes(db))

    # 5. Replace is claim-gated: without the process claim it bounces.
    content_file = tmp_path / "vision-next.md"
    vision_base = _row(db, "VISION")
    content_file.write_text(
        vision_base["content"] + "\nSharper E2E vision.\n", encoding="utf-8",
    )
    envelope = _envelope(
        "strategy", "doc", "replace", "VISION",
        "--content-file", str(content_file),
        "--base-updated-at", vision_base["updated_at"],
    )
    assert envelope["success"] is False
    assert envelope["error"]["code"] == "strategy_claim_required"

    # 6. Acquire the STRATEGIZE claim through the real CLI — a pure
    #    process lock: zero linked path claims (the retired linkage).
    acquired = _claims_cli(
        "claims", "work", "acquire", "--process", "STRATEGIZE",
        "--reason", "e2e lifecycle",
    )
    assert acquired["success"] is True
    claim_id = int(acquired["result"]["claim_id"])
    assert acquired["result"]["linked_path_claim_ids"] == []

    # 7. Claim held: CAS replace succeeds; the SAME base now conflicts.
    envelope = _envelope(
        "strategy", "doc", "replace", "VISION",
        "--content-file", str(content_file),
        "--base-updated-at", vision_base["updated_at"],
    )
    assert envelope["success"] is True
    assert any('"source": "replace"' in e for e in _replaced_event_envelopes(db))
    stale = _envelope(
        "strategy", "doc", "replace", "VISION",
        "--content-file", str(content_file),
        "--base-updated-at", vision_base["updated_at"],
    )
    assert stale["success"] is False
    assert stale["error"]["code"] == "replace_conflict"
    assert "doc get VISION" in stale["error"]["message"]

    # 8. Foreign-claim bounce: while OPERATOR holds the claim, another
    #    session's wet ingest refuses (dry-run still previews).
    _cli("strategy", "render", "--target-root", root)  # pick up VISION
    _edit_body(checkout, "MISSION", _row(db, "MISSION")["content"] + "\nX.\n")
    bounced = _envelope(
        "strategy", "ingest", "MISSION", "--target-root", root,
        session_id=OTHER,
    )
    assert bounced["success"] is False
    assert bounced["error"]["code"] == "ingest_blocked_by_live_process_claim"
    assert OPERATOR in bounced["error"]["message"]
    preview = _envelope(
        "strategy", "ingest", "MISSION", "--dry-run", "--target-root", root,
        session_id=OTHER,
    )
    assert preview["success"] is True

    # 9. Release the claim via the real CLI; the other session's ingest
    #    now lands.
    released = _claims_cli(
        "claims", "work", "release", "--claim-id", str(claim_id),
        "--reason", "e2e done",
    )
    assert released["success"] is True
    landed = _envelope(
        "strategy", "ingest", "MISSION", "--target-root", root,
        session_id=OTHER,
    )
    assert landed["success"] is True
    assert "\nX.\n" in _row(db, "MISSION")["content"]

    # 10. Staleness HC closes the loop: fresh views PASS; a DB write
    #     without re-render WARNs naming the doc.
    from yoke_core.engines import doctor_hc_strategy_render_staleness as hc

    rc, _, _ = _cli("strategy", "render", "--target-root", root)
    assert rc == 0

    class _Collector:
        def __init__(self):
            self.records = []

        def record(self, *args):
            self.records.append(args)

    conn = connect_test_db(db)
    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                hc, "_mapped_checkouts", lambda: [(checkout, PROJECT)],
            )
            collector = _Collector()
            hc.hc_strategy_render_staleness(
                conn, SimpleNamespace(quick=True), collector,
            )
            assert collector.records[-1][2] == "PASS"
            conn.execute(
                f"UPDATE {sd.STRATEGY_DOCS_TABLE} SET content = %s, "
                "updated_at = %s WHERE project_id = %s AND slug = %s",
                ("# WISPS\n\nmoved without render\n", "2026-06-12T00:00:00Z",
                 PROJECT, "WISPS"),
            )
            conn.commit()
            collector = _Collector()
            hc.hc_strategy_render_staleness(
                conn, SimpleNamespace(quick=True), collector,
            )
            assert collector.records[-1][2] == "WARN"
            assert "WISPS" in collector.records[-1][3]
    finally:
        conn.close()
