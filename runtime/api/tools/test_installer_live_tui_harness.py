from __future__ import annotations

from pathlib import Path

from yoke_core.domain import json_helper
from yoke_core.tools import installer_live_tui_harness as harness


def test_loads_scenario_tables_from_plan_doc(tmp_path: Path) -> None:
    """The parser extracts wave tables from a scenario-catalog doc.

    The operator's real catalog is a DB-authoritative strategy doc whose
    rendered view is local-only (untracked), so the test exercises the
    parsing contract against a fixture doc: multiple waves, both
    ``Profile`` and ``Host`` header variants, code-fenced ids, and
    non-scenario rows skipped.
    """
    plan = tmp_path / "scenario-catalog.md"
    plan.write_text(
        """
### Wave 1: Installer And First Wizard Smoke

| ID | Profile | Flow | Assertions |
| --- | --- | --- | --- |
| `INSTALL-SMOKE-001` | `bare-no-uv` | Interactive installer | welcome renders |
| `INSTALL-SMOKE-002` | `bare-no-uv` | Installer `--yes` | no TUI launch |
| (carried rows) | | | |

### Wave 6: Project Source Picker

| ID | Profile | Flow | Assertions |
| --- | --- | --- | --- |
| **`PROJECT-SOURCE-019`** | `prepared-git` | Clone public repo URL | source reachable |

### Wave 12: macOS Lane

| ID | Host | Flow | Assertions |
| --- | --- | --- | --- |
| `MAC-009` | test Mac | Stage installer in real SSH TTY | PATH repair works |
""".strip(),
        encoding="utf-8",
    )

    scenarios = harness.load_scenarios_from_plan(plan)

    by_id = {scenario.scenario_id: scenario for scenario in scenarios}
    assert set(by_id) == {
        "INSTALL-SMOKE-001",
        "INSTALL-SMOKE-002",
        "PROJECT-SOURCE-019",
        "MAC-009",
    }
    smoke = by_id["INSTALL-SMOKE-001"]
    assert smoke.wave == "Wave 1: Installer And First Wizard Smoke"
    assert smoke.host_profile == "bare-no-uv"
    assert smoke.flow == "Interactive installer"
    assert smoke.assertions == "welcome renders"
    # Bold markers are cleaned; the Host header variant maps to host_profile.
    assert by_id["PROJECT-SOURCE-019"].host_profile == "prepared-git"
    assert by_id["MAC-009"].host_profile == "test Mac"


def test_render_assignments_groups_related_scenarios(tmp_path: Path) -> None:
    scenarios = [
        harness.Scenario(
            "INSTALL-SMOKE-001",
            "Wave 1: Installer And First Wizard Smoke",
            "bare-no-uv",
            "Interactive installer",
            "welcome renders",
        ),
        harness.Scenario(
            "INSTALL-SMOKE-002",
            "Wave 1: Installer And First Wizard Smoke",
            "bare-no-uv",
            "Installer --yes",
            "no TUI launch",
        ),
        harness.Scenario(
            "PATH-001",
            "Wave 3: PATH Front Door",
            "prepared-path-broken",
            "Default PATH repair",
            "writes managed block",
        ),
    ]
    campaign_root = tmp_path / "campaign"

    manifest = harness.build_manifest(scenarios, campaign_root=campaign_root)
    assignments = harness.build_assignments(
        scenarios,
        campaign_root=campaign_root,
        assignment_size=2,
    )
    result = harness.write_campaign_files(
        campaign_root=campaign_root,
        manifest=manifest,
        assignments=assignments,
    )

    assert result["assignment_count"] == 2
    assert (campaign_root / "harness-manifest.json").is_file()
    first = json_helper.load_path(campaign_root / "assignments" / "A001.json")
    assert isinstance(first, dict)
    assert first["scenario_ids"] == ["INSTALL-SMOKE-001", "INSTALL-SMOKE-002"]
    assert first["host_profile"] == "bare-no-uv"


def test_secret_scan_reports_marker_without_printing_secret(tmp_path: Path) -> None:
    capture = tmp_path / "captures" / "screen.txt"
    capture.parent.mkdir()
    capture.write_text("token shape yoke_v1_should_not_be_here\n", encoding="utf-8")

    findings = harness.scan_secret_markers_in_paths([tmp_path])

    assert len(findings) == 1
    assert findings[0].path == str(capture)
    assert findings[0].markers == ("yoke_v1_",)


def test_collect_reports_requires_matching_screenshot(tmp_path: Path) -> None:
    campaign_root = tmp_path / "campaign"
    capture = campaign_root / "captures" / "A001" / "AUTH-007" / "010-after-token.txt"
    report = campaign_root / "reports" / "A001.json"
    capture.parent.mkdir(parents=True)
    report.parent.mkdir(parents=True)
    capture.write_text("friendly auth error\n", encoding="utf-8")
    json_helper.dump_path(
        report,
        {
            "assignment_id": "A001",
            "campaign_root": str(campaign_root),
            "overall_result": "pass",
            "scenarios": [
                {
                    "scenario_id": "AUTH-007",
                    "result": "pass",
                    "captures": [{"name": capture.name, "path": str(capture)}],
                    "screenshots": [],
                }
            ],
        },
    )

    missing = harness.collect_reports(campaign_root)

    assert missing["ok"] is False
    assert missing["evidence_issue_count"] == 1

    screenshot = (
        campaign_root
        / "screenshots"
        / "A001"
        / "AUTH-007"
        / "010-after-token.png"
    )
    screenshot.parent.mkdir(parents=True)
    screenshot.write_bytes(b"fake-png")

    complete = harness.collect_reports(campaign_root)

    assert complete["ok"] is True
    assert complete["evidence_issue_count"] == 0
