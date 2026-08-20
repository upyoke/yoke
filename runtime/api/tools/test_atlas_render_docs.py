"""Tests for the Atlas docs renderer (body, staleness, --from-report)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.tools import atlas_render_docs as ard


# Minimal fixture report carrying every top-level key the renderer reads.
_REPORT: dict = {
    "generated_at": "1970-01-01T00:00:00Z",
    "function_registry": {
        "count": 3,
        "by_stability": {"stable": 3},
        "by_adapter_status": {"live": 3},
        "rows": [
            {"function_id": "items.get.run", "stability": "stable",
             "owner_module": "x", "target_kinds": ["item"], "side_effects": [],
             "emitted_event_names": [], "guardrails": [], "adapter_status": "live",
             "version": "v1", "replacement_function_id": None,
             "removal_target_version": None, "claim_required_kind": None},
            {"function_id": "claims.work.acquire", "stability": "stable",
             "owner_module": "y", "target_kinds": ["item"], "side_effects": [],
             "emitted_event_names": [], "guardrails": [], "adapter_status": "live",
             "version": "v1", "replacement_function_id": None,
             "removal_target_version": None, "claim_required_kind": "item"},
            {"function_id": "lifecycle.transition.execute", "stability": "stable",
             "owner_module": "z", "target_kinds": ["item"], "side_effects": [],
             "emitted_event_names": [], "guardrails": [], "adapter_status": "live",
             "version": "v1", "replacement_function_id": None,
             "removal_target_version": None, "claim_required_kind": "item"},
        ],
    },
    "yoke_cli": {
        "count": 3,
        "rows": [
            {"cli_tokens": ["items", "get"], "cli_form": "yoke items get",
             "function_id": "items.get.run", "family": "items",
             "has_usage_line": True, "usage": "items get <YOK-N> ..."},
            {"cli_tokens": ["claims", "work", "acquire"],
             "cli_form": "yoke claims work acquire",
             "function_id": "claims.work.acquire", "family": "claims",
             "has_usage_line": True, "usage": "claims work acquire ..."},
            {"cli_tokens": ["lifecycle", "transition"],
             "cli_form": "yoke lifecycle transition",
             "function_id": "lifecycle.transition.execute", "family": "lifecycle",
             "has_usage_line": True, "usage": "lifecycle transition ..."},
        ],
    },
    "operation_tracker": {
        "count": 5,
        "by_status": {"wrapped": 3, "tool_cli": 1, "permanent": 1, "pending": 1},
        "rows": [
            {"shell_form": "python3 -m foo a", "family": "fa",
             "status": "wrapped", "reason": "wrapped_by_yoke_cli",
             "proposed_function_id": None},
            {"shell_form": "python3 -m foo b", "family": "fb",
             "status": "wrapped", "reason": "wrapped_by_yoke_cli",
             "proposed_function_id": None},
            {"shell_form": "python3 -m foo c", "family": "fc",
             "status": "wrapped", "reason": "wrapped_by_yoke_cli",
             "proposed_function_id": None},
            {"shell_form": "yoke watch pytest",
             "family": "tools.watch", "status": "tool_cli",
             "reason": "tool_shaped", "proposed_function_id": None},
            {"shell_form": "python3 -m yoke_core.cli.db_router something",
             "family": "something", "status": "pending",
             "reason": "no_handler_registered",
             "proposed_function_id": "something.list.run"},
        ],
    },
    "help_pages": {
        "top_level": {"exit_code": 0, "body": "yoke --help body\n"},
        "per_subcommand": {
            "items get": {"exit_code": 0, "body": "items get help", "stderr": "",
                          "has_usage_line": True},
            "claims work acquire": {"exit_code": 0, "body": "acquire help",
                                    "stderr": "", "has_usage_line": True},
            "lifecycle transition": {"exit_code": 0, "body": "transition help",
                                     "stderr": "", "has_usage_line": True},
        },
        "coverage": {"total": 3, "with_usable_help": 3, "missing": 0},
    },
    "teaching_places": {
        "groups": {"glob/a/**/*.md": ["file.md"], "glob/b/*.py": []},
        "totals": {"glob/a/**/*.md": 1, "glob/b/*.py": 0},
    },
    "recipes": {
        "total": 1, "template_skipped": 1, "failed": 0,
        "verdicts": [{"file": "x.md", "line_number": 1, "recipe": "yoke items get YOK-N",
                      "ok": True, "function_id": None, "expect_error": None,
                      "error": None, "template_skipped": True}],
    },
    "lints": {
        "count": 2,
        "with_field_note_reference": 1,
        "with_denial_text": 2,
        "rows": [
            {"module": "runtime/api/domain/lint_foo.py",
             "has_field_note_reference": True, "has_denial_text": True},
            {"module": "runtime/api/domain/lint_bar.py",
             "has_field_note_reference": False, "has_denial_text": True},
        ],
    },
    "field_notes": {
        "count": 2,
        "read_surface_status": "internal_db_direct",
        "rows": [
            {"id": 1, "timestamp": "2026-01-01", "agent": "engineer",
             "category": "failed", "project": "yoke", "excerpt": "x"},
            {"id": 2, "timestamp": "2026-01-02", "agent": "engineer",
             "category": "observation", "project": "yoke", "excerpt": "y"},
        ],
    },
    "contradictions": [
        {"id": "open-one", "kind": "promise-vs-live", "surface": "s1",
         "claim": "c1", "live_truth": "lt1", "resolution_hint": "h1",
         "status": "open"},
        {"id": "resolved-one", "kind": "work-item-promise-vs-live", "surface": "s2",
         "claim": "c2", "live_truth": "lt2", "resolution_hint": "h2",
         "status": "resolved", "resolution_note": "n"},
    ],
    "followup_candidates": [
        {"id": "pending-cli-adapter-conversions", "category": "cloud_blocker",
         "title": "1 pending row", "evidence": []},
    ],
    "summary": {
        "function_ids": 3, "yoke_cli_subcommands": 3,
        "operation_tracker": {"wrapped": 3, "tool_cli": 1, "permanent": 1, "pending": 1},
        "subcommand_help_coverage": {"total": 3, "with_usable_help": 3, "missing": 0},
        "recipes": {"total": 1, "template_skipped": 1, "failed": 0},
        "field_notes_recent": 2,
        "contradictions": {"total": 2, "open": 1},
    },
}


@pytest.fixture
def report() -> dict:
    return json.loads(json.dumps(_REPORT))


@pytest.fixture
def body(report: dict) -> str:
    return ard.render(report)


class TestRender:
    def test_header_and_sections_present_in_order(self, body: str) -> None:
        expected = [
            "# Yoke Atlas",
            "## 1. Summary",
            "## 2. Wrapped operation roster",
            "## 3. Tool-shaped CLI roster",
            "## 4. Permanent command-shaped boundary roster",
            "## 5. Pending handler-registration roster",
            "## 6. Teaching coverage",
            "## 7. Field-note hotspots",
            "## 8. Contradictions",
            "## 9. Next-slice recommendation",
        ]
        positions = [body.find(heading) for heading in expected]
        assert all(p >= 0 for p in positions), positions
        assert positions == sorted(positions)

    def test_permanent_roster_teaches_human_claim_release(self, body: str) -> None:
        assert "### Human-only stranded work-claim release" in body
        assert "service_client claim-release" in body
        assert "OperatorClaimOverride" in body

    def test_summary_surfaces_top_level_counts(self, body: str) -> None:
        assert "**3**" in body  # function_ids
        assert "1 pending" in body
        assert "**1 open**" in body or "open" in body

    def test_summary_explains_internal_function_without_cli_adapter(
        self,
        report: dict,
    ) -> None:
        report["function_registry"]["by_adapter_status"]["internal"] = 1
        rendered = ard.render(report)
        assert (
            "Internal dispatch-only functions without CLI adapters: **1**"
            in rendered
        )

    def test_wrapped_roster_lists_every_cli_row(self, body: str) -> None:
        assert "yoke items get" in body
        assert "yoke claims work acquire" in body
        assert "yoke lifecycle transition" in body

    def test_tool_cli_roster_lists_local_adapter(self, body: str) -> None:
        assert "## 3. Tool-shaped CLI roster" in body
        assert "yoke watch pytest" in body
        assert "without a dispatcher function id" in body

    def test_client_local_cli_row_renders_only_as_permanent_boundary(
        self,
        report: dict,
    ) -> None:
        report["yoke_cli"]["count"] = 4
        report["yoke_cli"]["rows"].append({
            "cli_tokens": ["project", "install"],
            "cli_form": "yoke project install",
            "function_id": "project.install",
            "family": "sessions",
            "has_usage_line": True,
            "usage": "project install",
            "dispatch_kind": "client_local",
        })
        report["operation_tracker"]["count"] = 6
        report["operation_tracker"]["by_status"]["permanent"] = 2
        report["operation_tracker"]["rows"].append({
            "shell_form": "yoke project install",
            "family": "sessions",
            "status": "permanent",
            "reason": "tool_shaped",
            "proposed_function_id": None,
        })
        report["help_pages"]["per_subcommand"]["project install"] = {
            "exit_code": 0,
            "body": "project install help",
            "stderr": "",
            "has_usage_line": True,
        }
        rendered = ard.render(report)
        wrapped, permanent = rendered.split(
            "## 4. Permanent command-shaped boundary roster", maxsplit=1
        )
        assert "yoke project install" not in wrapped
        assert permanent.count("yoke project install") == 1

    def test_pending_roster_lists_proposed_function_id(self, body: str) -> None:
        assert "something.list.run" in body

    def test_contradictions_section_shows_open_first(self, body: str) -> None:
        open_pos = body.find("open-one")
        resolved_pos = body.find("resolved-one")
        assert 0 <= open_pos < resolved_pos

    def test_next_slice_lists_candidate_titles(self, body: str) -> None:
        assert "1 pending row" in body


class TestStaleness:
    def test_missing_atlas_file_is_stale(self, tmp_path: Path, body: str) -> None:
        # tmp_path is under /var/folders/... which the workspace authority
        # guard allows as a free path, but is_stale only reads — no guard.
        assert ard.is_stale(tmp_path, body=body) is True

    def test_matching_atlas_file_is_not_stale(
        self, tmp_path: Path, body: str
    ) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "atlas.md").write_text(body, encoding="utf-8")
        assert ard.is_stale(tmp_path, body=body) is False

    def test_timestamp_only_diff_is_not_stale(
        self, tmp_path: Path, report: dict
    ) -> None:
        first = ard.render(report)
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "atlas.md").write_text(first, encoding="utf-8")
        report["generated_at"] = "2099-01-01T00:00:00Z"
        second = ard.render(report)
        assert second != first  # timestamp differs
        assert ard.is_stale(tmp_path, body=second) is False

    def test_field_note_count_diff_is_not_stale(
        self, tmp_path: Path, report: dict
    ) -> None:
        first = ard.render(report)
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "atlas.md").write_text(first, encoding="utf-8")
        # Mutate live DB read state only — field-note counts change.
        report["field_notes"]["count"] = 99
        report["summary"]["field_notes_recent"] = 99
        report["field_notes"]["rows"].append({
            "id": 3, "timestamp": "2026-01-03", "agent": "newbie",
            "category": "observation", "project": "yoke", "excerpt": "z",
        })
        second = ard.render(report)
        assert second != first  # field-note section differs
        assert ard.is_stale(tmp_path, body=second) is False

    def test_next_slice_followup_diff_is_not_stale(
        self, tmp_path: Path, report: dict
    ) -> None:
        first = ard.render(report)
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "atlas.md").write_text(first, encoding="utf-8")
        report["followup_candidates"] = []
        second = ard.render(report)
        assert second != first
        assert ard.is_stale(tmp_path, body=second) is False

    def test_content_diff_trips_staleness(
        self, tmp_path: Path, report: dict
    ) -> None:
        first = ard.render(report)
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "atlas.md").write_text(first, encoding="utf-8")
        # Mutate a real content field and re-render.
        report["contradictions"].append({
            "id": "new", "kind": "k", "surface": "s", "claim": "c",
            "live_truth": "lt", "resolution_hint": "h", "status": "open",
        })
        report["summary"]["contradictions"] = {"total": 3, "open": 2}
        second = ard.render(report)
        assert ard.is_stale(tmp_path, body=second) is True


class TestWrite:
    def test_writes_to_target_root(self, tmp_path: Path, body: str) -> None:
        path = ard.write(tmp_path, body=body)
        assert path == tmp_path / "docs" / "atlas.md"
        assert path.read_text(encoding="utf-8") == body


class TestCliProgress:
    def test_render_reports_stages_to_stderr(
        self, tmp_path: Path, report: dict, capsys: pytest.CaptureFixture[str]
    ) -> None:
        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        output = tmp_path / "atlas.md"

        rc = ard.main([
            "render",
            "--target-root", str(tmp_path),
            "--from-report", str(report_path),
            "--output", str(output),
        ])

        captured = capsys.readouterr()
        assert rc == 0
        assert output.exists()
        assert "atlas_render_docs: loading report" in captured.err
        assert "atlas_render_docs: rendering docs/atlas.md" in captured.err
        assert "atlas_render_docs: writing docs/atlas.md" in captured.err
