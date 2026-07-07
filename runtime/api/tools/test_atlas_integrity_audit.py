"""Tests for the Atlas integrity audit runner.

Covers: stable JSON shape (top-level keys), seed-contradiction
resolution against simulated live state, follow-up candidate derivation,
summary aggregation, ``--output`` writer round-trip, and the report's
byte-stability when the ``generated_at`` field is held constant.
"""

from __future__ import annotations

import json
import re
from types import SimpleNamespace
from pathlib import Path

import pytest

from yoke_core.tools import atlas_integrity_audit as aia
from yoke_core.tools import atlas_integrity_collect as collect


TOP_LEVEL_KEYS = {
    "generated_at",
    "function_registry",
    "yoke_cli",
    "operation_tracker",
    "help_pages",
    "teaching_places",
    "recipes",
    "lints",
    "field_notes",
    "contradictions",
    "followup_candidates",
    "summary",
}


@pytest.fixture
def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        if (parent / "runtime" / "api" / "tools").is_dir():
            return parent
    raise RuntimeError("could not infer repo root from test file path")


@pytest.fixture
def report(repo_root: Path) -> dict:
    return aia.build_report(repo_root, generated_at="1970-01-01T00:00:00Z")


class TestTopLevelShape:
    def test_all_keys_present(self, report: dict) -> None:
        assert set(report.keys()) == TOP_LEVEL_KEYS

    def test_function_registry_has_count_and_rows(self, report: dict) -> None:
        fr = report["function_registry"]
        assert fr["count"] >= 1
        assert isinstance(fr["rows"], list)
        assert all("function_id" in r for r in fr["rows"])
        assert fr["rows"] == sorted(fr["rows"], key=lambda r: r["function_id"])

    def test_yoke_cli_has_count_and_rows(self, report: dict) -> None:
        sc = report["yoke_cli"]
        assert sc["count"] >= 1
        for row in sc["rows"]:
            assert row["cli_form"].startswith("yoke ")
            assert "." in row["function_id"]
            assert row["family"] == row["function_id"].split(".", 1)[0]

    def test_operation_tracker_status_buckets(self, report: dict) -> None:
        ot = report["operation_tracker"]
        for row in ot["rows"]:
            assert row["status"] in {"wrapped", "permanent", "pending"}

    def test_help_pages_covers_every_subcommand(self, report: dict) -> None:
        cov = report["help_pages"]["coverage"]
        assert cov["total"] == report["yoke_cli"]["count"]
        assert cov["total"] == cov["with_usable_help"] + cov["missing"]

    def test_recipes_counts_consistent(self, report: dict) -> None:
        r = report["recipes"]
        assert r["total"] == len(r["verdicts"])
        assert r["template_skipped"] == sum(
            1 for v in r["verdicts"] if v["template_skipped"]
        )
        assert r["failed"] == sum(1 for v in r["verdicts"] if not v["ok"])

    def test_summary_aggregates_subordinate_counts(self, report: dict) -> None:
        s = report["summary"]
        assert s["function_ids"] == report["function_registry"]["count"]
        assert s["yoke_cli_subcommands"] == report["yoke_cli"]["count"]
        assert s["contradictions"]["total"] == len(report["contradictions"])


class TestFieldNoteCollection:
    def test_uses_field_note_cli_transport_surface(self, monkeypatch) -> None:
        seen = {}

        def fake_call_dispatcher(**kwargs):
            seen.update(kwargs)
            return SimpleNamespace(
                success=True,
                result={"entries": [{"id": 1, "agent": "tester"}]},
                error=None,
            )

        monkeypatch.setattr(
            "yoke_cli.transport.dispatcher.call_dispatcher",
            fake_call_dispatcher,
        )

        result = collect.collect_field_notes()

        assert result["read_surface_status"] == "agent_facing"
        assert result["rows"] == [{"id": 1, "agent": "tester"}]
        assert seen["function_id"] == "ouroboros.field_note.list"
        assert seen["target"].kind == "global"
        assert seen["payload"] == {
            "category_prefix": "field-note-",
            "limit": 50,
        }
        assert seen["actor"].session_id == "atlas-integrity-audit"


class TestSeedContradictionResolution:
    def test_both_seeds_present(self, report: dict) -> None:
        ids = {row["id"] for row in report["contradictions"]}
        assert "function-inventory-empty-registry-mismatch" in ids
        assert "claims-work-holder-get-flag-vs-positional" in ids

    def test_function_inventory_resolves_when_doc_missing(self) -> None:
        rows = [
            aia._resolve_seed_contradiction(
                seed,
                cli_help={"per_subcommand": {}},
                doc_state={"exists": False, "claims_empty_registry": False},
            )
            for seed in aia.SEED_CONTRADICTIONS
        ]
        by_id = {row["id"]: row for row in rows}
        assert by_id["function-inventory-empty-registry-mismatch"]["status"] == "resolved"

    def test_function_inventory_resolves_when_doc_no_longer_claims_empty(self) -> None:
        row = aia._resolve_seed_contradiction(
            aia.SEED_CONTRADICTIONS[0],
            cli_help={"per_subcommand": {}},
            doc_state={"exists": True, "claims_empty_registry": False},
        )
        assert row["status"] == "resolved"

    def test_holder_get_resolves_when_help_carries_item_flag(self) -> None:
        row = aia._resolve_seed_contradiction(
            aia.SEED_CONTRADICTIONS[1],
            cli_help={
                "per_subcommand": {
                    "claims work holder-get": {"body": "Usage: ... --item YOK-N ..."},
                }
            },
            doc_state={"exists": False, "claims_empty_registry": False},
        )
        assert row["status"] == "resolved"

    def test_holder_get_remains_open_for_positional_only(self) -> None:
        row = aia._resolve_seed_contradiction(
            aia.SEED_CONTRADICTIONS[1],
            cli_help={
                "per_subcommand": {
                    "claims work holder-get": {"body": "Usage: holder-get <YOK-N>"},
                }
            },
            doc_state={"exists": False, "claims_empty_registry": False},
        )
        assert row["status"] == "open"


class TestFollowupCandidates:
    def test_pending_rows_produce_cloud_blocker_candidate(self) -> None:
        candidates = aia._build_followup_candidates(
            operation_tracker={"rows": [
                {"status": "pending", "shell_form": "python3 -m foo",
                 "proposed_function_id": "foo.bar.baz"},
            ]},
            contradictions=[],
            field_notes={"read_surface_status": "agent_facing"},
            recipes={"verdicts": []},
        )
        ids = {c["id"] for c in candidates}
        assert "pending-cli-adapter-conversions" in ids
        cb = next(c for c in candidates if c["id"] == "pending-cli-adapter-conversions")
        assert cb["category"] == "cloud_blocker"

    def test_internal_field_note_surface_produces_candidate(self) -> None:
        candidates = aia._build_followup_candidates(
            operation_tracker={"rows": []},
            contradictions=[],
            field_notes={"read_surface_status": "internal_db_direct"},
            recipes={"verdicts": []},
        )
        assert any(c["id"] == "field-note-read-surface-gap" for c in candidates)

    def test_failing_recipes_produce_candidate(self) -> None:
        candidates = aia._build_followup_candidates(
            operation_tracker={"rows": []},
            contradictions=[],
            field_notes={"read_surface_status": "agent_facing"},
            recipes={"verdicts": [{
                "ok": False, "file": "x.md", "line_number": 1,
                "recipe": "yoke boom", "error": "kaboom",
            }]},
        )
        assert any(c["id"] == "failing-skill-recipes" for c in candidates)


class TestStableSerialisation:
    def test_serialise_is_sorted_and_terminated(self, report: dict) -> None:
        body = aia.serialise(report)
        assert body.endswith("\n")
        # sorted_keys + indent=2 puts every top-level key on its own line in
        # lexicographic order — pin a couple of anchor positions.
        positions = [body.find(f'"{key}"') for key in sorted(TOP_LEVEL_KEYS)]
        assert positions == sorted(positions)

    def test_re_serialise_is_byte_identical(self, report: dict) -> None:
        first = aia.serialise(report)
        second = aia.serialise(json.loads(first))
        assert first == second


class TestWriteReport:
    def test_writes_under_free_path(self, report: dict, tmp_path: Path) -> None:
        # tmp_path is under /var/folders/... which the workspace authority
        # guard allows as a free path.
        output = tmp_path / "report.json"
        path = aia.write_report(report, output)
        assert path == output
        assert output.exists()
        parsed = json.loads(output.read_text(encoding="utf-8"))
        assert set(parsed.keys()) == TOP_LEVEL_KEYS

    def test_creates_parent_directory(self, report: dict, tmp_path: Path) -> None:
        output = tmp_path / "nested" / "dir" / "report.json"
        aia.write_report(report, output)
        assert output.exists()


class TestGeneratedAt:
    def test_generated_at_matches_iso_format(self, report: dict) -> None:
        assert re.match(
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", report["generated_at"]
        )

    def test_explicit_generated_at_is_honoured(self, repo_root: Path) -> None:
        custom = "2030-12-31T23:59:59Z"
        report = aia.build_report(repo_root, generated_at=custom)
        assert report["generated_at"] == custom
