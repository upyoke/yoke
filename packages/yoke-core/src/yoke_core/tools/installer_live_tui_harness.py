"""Validation helpers for live public-installer TUI campaigns.

The live installer/TUI campaign uses retained evidence on disk: a strategy-doc
scenario catalog, assignment JSON files, captured terminal text, matching
screenshots, per-assignment reports, and summary JSON. This module keeps that
scrappy harness deterministic while the broader fleet runner is still maturing.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence

from yoke_core.domain import json_helper
from yoke_core.tools.installer_live_tui_catalog import (
    Scenario,
    load_scenarios_from_plan,
)


HARNESS_ID = "installer-live-tui"
SUITE_ID = "yoke.installer-live-tui"
SURFACE = "yoke onboard"
HARNESS_VERSION = "0.1"
DEFAULT_ENDPOINT = "stage"
DEFAULT_ASSIGNMENT_SIZE = 5
SECRET_MARKERS: tuple[str, ...] = (
    "yoke_v1_",
    "ghu_",
    "ghs_",
    "ghr_",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_ACCESS_KEY_ID",
)


@dataclass(frozen=True)
class Assignment:
    assignment_id: str
    endpoint: str
    campaign_root: str
    host_profile: str
    scenario_ids: tuple[str, ...]
    scenarios: tuple[dict[str, object], ...]
    rules: tuple[str, ...]


@dataclass(frozen=True)
class SecretFinding:
    path: str
    markers: tuple[str, ...]


@dataclass(frozen=True)
class EvidenceIssue:
    scenario_id: str
    kind: str
    message: str
    path: str


def build_manifest(
    scenarios: Sequence[Scenario],
    *,
    campaign_root: Path,
    endpoint: str = DEFAULT_ENDPOINT,
) -> dict[str, object]:
    root = str(campaign_root)
    return {
        "harness_id": HARNESS_ID,
        "suite_id": SUITE_ID,
        "surface": SURFACE,
        "version": HARNESS_VERSION,
        "target_env": endpoint,
        "evidence_root": root,
        "scenario_count": len(scenarios),
        "scenarios": [
            {
                "id": scenario.scenario_id,
                "wave": scenario.wave,
                "host_profile": scenario.host_profile,
                "flow": scenario.flow,
                "assertions": scenario.assertions,
                "qa_kind": "live-tui",
                "executor_type": "agent",
                "future_executor_type": "ssh-tui",
                "target_env": endpoint,
                "blocking_mode": "blocking",
                "capability_requirements": capability_requirements(scenario),
                "success_policy": success_policy_for_scenario(scenario),
            }
            for scenario in scenarios
        ],
    }


def build_assignments(
    scenarios: Sequence[Scenario],
    *,
    campaign_root: Path,
    endpoint: str = DEFAULT_ENDPOINT,
    assignment_size: int = DEFAULT_ASSIGNMENT_SIZE,
) -> list[Assignment]:
    if assignment_size < 1:
        raise ValueError("assignment_size must be at least 1")
    grouped: dict[tuple[str, str], list[Scenario]] = defaultdict(list)
    for scenario in scenarios:
        grouped[(scenario.wave, scenario.host_profile)].append(scenario)

    assignments: list[Assignment] = []
    next_id = 1
    for key in sorted(grouped, key=lambda value: (_wave_sort_key(value[0]), value[1])):
        group = grouped[key]
        for offset in range(0, len(group), assignment_size):
            chunk = group[offset : offset + assignment_size]
            assignments.append(
                Assignment(
                    assignment_id=f"A{next_id:03d}",
                    endpoint=endpoint,
                    campaign_root=str(campaign_root),
                    host_profile=chunk[0].host_profile,
                    scenario_ids=tuple(s.scenario_id for s in chunk),
                    scenarios=tuple(_assignment_scenario(s, endpoint) for s in chunk),
                    rules=_assignment_rules(),
                )
            )
            next_id += 1
    return assignments


def write_campaign_files(
    *,
    campaign_root: Path,
    manifest: dict[str, object],
    assignments: Sequence[Assignment],
) -> dict[str, object]:
    campaign_root.mkdir(parents=True, exist_ok=True)
    for dirname in (
        "assignments",
        "captures",
        "screenshots",
        "post-apply",
        "reports",
        "summaries",
        "raw-host-staging",
        "logs",
    ):
        (campaign_root / dirname).mkdir(exist_ok=True)
    manifest_path = campaign_root / "harness-manifest.json"
    json_helper.dump_path(manifest_path, manifest)
    assignment_paths = []
    for assignment in assignments:
        path = campaign_root / "assignments" / f"{assignment.assignment_id}.json"
        json_helper.dump_path(path, asdict(assignment))
        assignment_paths.append(str(path))
    return {
        "campaign_root": str(campaign_root),
        "manifest_path": str(manifest_path),
        "assignment_count": len(assignments),
        "assignment_paths": assignment_paths,
    }


def capability_requirements(scenario: Scenario) -> list[str]:
    requirements = {"ssh", "screenshot"}
    profile = scenario.host_profile.lower()
    text = f"{scenario.wave} {scenario.flow} {scenario.assertions}".lower()
    if "macos" in scenario.wave.lower() or "mac" in profile:
        requirements.add("mac-terminal")
    if "token" in text or "auth" in text or "stage" in text or "prod" in text:
        requirements.add("token-file")
    if "github" in text or "repo" in text or "clone" in text or "push" in text:
        requirements.add("github")
    if "git" in profile or "git" in text:
        requirements.add("git")
    if profile.startswith("bare") or "installer" in scenario.wave.lower():
        requirements.add("public-installer")
    if "fault" in profile or "failure" in text or "invalid" in text:
        requirements.add("fault-injection")
    return sorted(requirements)


def success_policy_for_scenario(scenario: Scenario) -> dict[str, object]:
    steps: list[dict[str, object]] = [
        {"name": "initial", "evidence": ["text_capture", "screenshot"]},
        {"name": "screen_flow", "evidence": ["text_capture", "screenshot"]},
    ]
    lower = f"{scenario.flow} {scenario.assertions}".lower()
    if "apply" in lower or "post-apply" in lower or "post apply" in lower:
        steps.append(
            {
                "name": "apply_result",
                "evidence": ["text_capture", "screenshot", "apply_report"],
            }
        )
        steps.append(
            {
                "name": "post_apply_truth",
                "checks": [
                    "apply_report_done",
                    "secret_free",
                    "checkout_contents",
                    "install_strategy",
                    "status_or_push_smoke",
                ],
            }
        )
    return {"type": "composite", "steps": steps}


def scan_secret_markers_in_paths(paths: Iterable[Path]) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    for root in paths:
        for path in _iter_files(root):
            text = path.read_bytes().decode("utf-8", errors="ignore")
            markers = tuple(marker for marker in SECRET_MARKERS if marker in text)
            if markers:
                findings.append(SecretFinding(str(path), markers))
    return findings


def validate_report_evidence(
    report_path: Path,
    *,
    campaign_root: Path | None = None,
) -> list[EvidenceIssue]:
    payload = json_helper.load_path(report_path)
    if not isinstance(payload, dict):
        raise ValueError(f"report root must be a JSON object: {report_path}")
    root = campaign_root or Path(
        str(payload.get("campaign_root") or report_path.parent.parent)
    )
    issues: list[EvidenceIssue] = []
    for scenario in payload.get("scenarios", []):
        if not isinstance(scenario, dict):
            continue
        scenario_id = str(scenario.get("scenario_id") or "")
        listed_screenshots = _listed_screenshot_paths(scenario)
        for capture in scenario.get("captures", []):
            if not isinstance(capture, dict):
                continue
            capture_path = _resolve_report_path(root, str(capture.get("path") or ""))
            if not capture_path.is_file():
                issues.append(
                    EvidenceIssue(
                        scenario_id,
                        "missing_capture",
                        "capture path does not exist",
                        str(capture_path),
                    )
                )
                continue
            expected = _expected_screenshot_path(root, capture_path)
            if str(expected) not in listed_screenshots and not expected.is_file():
                issues.append(
                    EvidenceIssue(
                        scenario_id,
                        "missing_screenshot",
                        "no matching screenshot for capture prefix",
                        str(expected),
                    )
                )
        for screenshot_path in listed_screenshots:
            resolved = _resolve_report_path(root, screenshot_path)
            if not resolved.is_file():
                issues.append(
                    EvidenceIssue(
                        scenario_id,
                        "missing_screenshot",
                        "listed screenshot path does not exist",
                        str(resolved),
                    )
                )
    return issues


def collect_reports(campaign_root: Path) -> dict[str, object]:
    reports_dir = campaign_root / "reports"
    report_paths = sorted(reports_dir.glob("*.json"))
    verdicts: Counter[str] = Counter()
    evidence_issues: list[EvidenceIssue] = []
    for report_path in report_paths:
        payload = json_helper.load_path(report_path)
        if isinstance(payload, dict):
            verdicts[str(payload.get("overall_result") or "unknown")] += 1
        evidence_issues.extend(
            validate_report_evidence(report_path, campaign_root=campaign_root)
        )
    secret_findings = scan_secret_markers_in_paths(
        [
            campaign_root / "captures",
            campaign_root / "screenshots",
            campaign_root / "logs",
            campaign_root / "post-apply",
            campaign_root / "raw-host-staging",
        ]
    )
    return {
        "campaign_root": str(campaign_root),
        "report_count": len(report_paths),
        "verdicts": dict(sorted(verdicts.items())),
        "evidence_issue_count": len(evidence_issues),
        "evidence_issues": [asdict(issue) for issue in evidence_issues],
        "secret_scan": {
            "ok": not secret_findings,
            "findings": [asdict(finding) for finding in secret_findings],
        },
        "ok": not evidence_issues and not secret_findings,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.tools.installer_live_tui_harness",
        description="Render and validate live installer/TUI campaign evidence.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    catalog = subparsers.add_parser("catalog")
    catalog.add_argument("--plan", required=True, type=Path)
    catalog.add_argument("--json", action="store_true")

    render = subparsers.add_parser("render-assignments")
    render.add_argument("--plan", required=True, type=Path)
    render.add_argument("--campaign-root", required=True, type=Path)
    render.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    render.add_argument("--assignment-size", default=DEFAULT_ASSIGNMENT_SIZE, type=int)
    render.add_argument("--json", action="store_true")

    scan = subparsers.add_parser("secret-scan")
    scan.add_argument("paths", nargs="+", type=Path)
    scan.add_argument("--json", action="store_true")

    validate = subparsers.add_parser("validate-report")
    validate.add_argument("--report", required=True, type=Path)
    validate.add_argument("--campaign-root", type=Path)
    validate.add_argument("--json", action="store_true")

    collect = subparsers.add_parser("collect-reports")
    collect.add_argument("--campaign-root", required=True, type=Path)
    collect.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "catalog":
            scenarios = load_scenarios_from_plan(args.plan.expanduser())
            payload = {
                "scenario_count": len(scenarios),
                "scenarios": [asdict(s) for s in scenarios],
            }
            return _emit(payload, args.json, f"Loaded {len(scenarios)} scenarios")
        if args.command == "render-assignments":
            plan = args.plan.expanduser()
            campaign_root = args.campaign_root.expanduser()
            scenarios = load_scenarios_from_plan(plan)
            manifest = build_manifest(
                scenarios,
                campaign_root=campaign_root,
                endpoint=args.endpoint,
            )
            assignments = build_assignments(
                scenarios,
                campaign_root=campaign_root,
                endpoint=args.endpoint,
                assignment_size=args.assignment_size,
            )
            payload = write_campaign_files(
                campaign_root=campaign_root,
                manifest=manifest,
                assignments=assignments,
            )
            return _emit(
                payload,
                args.json,
                "Rendered "
                f"{payload['assignment_count']} assignments to {campaign_root}",
            )
        if args.command == "secret-scan":
            findings = scan_secret_markers_in_paths(
                path.expanduser() for path in args.paths
            )
            payload = {"ok": not findings, "findings": [asdict(f) for f in findings]}
            if not findings:
                return _emit(payload, args.json, "PASS: no secret markers found")
            return _emit(payload, args.json, "ERROR: secret markers found", rc=1)
        if args.command == "validate-report":
            issues = validate_report_evidence(
                args.report.expanduser(),
                campaign_root=args.campaign_root.expanduser()
                if args.campaign_root is not None
                else None,
            )
            payload = {"ok": not issues, "issues": [asdict(issue) for issue in issues]}
            if not issues:
                return _emit(payload, args.json, "PASS: report evidence is complete")
            return _emit(payload, args.json, "ERROR: report evidence is incomplete", rc=1)
        if args.command == "collect-reports":
            payload = collect_reports(args.campaign_root.expanduser())
            text = (
                f"reports={payload['report_count']} "
                f"evidence_issues={payload['evidence_issue_count']} "
                f"secret_ok={payload['secret_scan']['ok']}"
            )
            return _emit(payload, args.json, text, rc=0 if payload["ok"] else 1)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    raise AssertionError(f"unhandled command: {args.command}")


def _assignment_rules() -> tuple[str, ...]:
    return (
        "Never print token contents.",
        "Capture text and screenshot evidence before and after every transition.",
        "Stop immediately on raw secret leakage.",
        "Save retained captures under <campaign-root>/captures/<assignment-id>/<scenario-id>/.",
        "Save retained screenshots under <campaign-root>/screenshots/<assignment-id>/<scenario-id>/.",
        "Write <campaign-root>/reports/<assignment-id>.json before finishing.",
        "Use /tmp/yoke-tui only as remote host staging; copy retained evidence back before marking a scenario pass.",
    )


def _assignment_scenario(scenario: Scenario, endpoint: str) -> dict[str, object]:
    return {
        "scenario_id": scenario.scenario_id,
        "wave": scenario.wave,
        "host_profile": scenario.host_profile,
        "endpoint": endpoint,
        "flow": scenario.flow,
        "assertions": scenario.assertions,
        "capability_requirements": capability_requirements(scenario),
        "success_policy": success_policy_for_scenario(scenario),
    }


def _emit(
    payload: dict[str, object],
    as_json: bool,
    text: str,
    *,
    rc: int = 0,
) -> int:
    if as_json:
        print(json_helper.dumps_pretty(payload), end="")
    else:
        stream = sys.stdout if rc == 0 else sys.stderr
        print(text, file=stream)
    return rc


def _wave_sort_key(wave: str) -> tuple[int, str]:
    match = re.search(r"Wave (\d+)", wave)
    return (int(match.group(1)) if match else 999, wave)


def _iter_files(path: Path) -> Iterable[Path]:
    if path.is_file():
        yield path
    elif path.is_dir():
        for child in sorted(path.rglob("*")):
            if child.is_file():
                yield child


def _listed_screenshot_paths(scenario: dict[str, object]) -> set[str]:
    paths: set[str] = set()
    for screenshot in scenario.get("screenshots", []):
        if isinstance(screenshot, dict) and screenshot.get("path"):
            paths.add(str(screenshot["path"]))
    return paths


def _resolve_report_path(root: Path, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    return root / path


def _expected_screenshot_path(root: Path, capture_path: Path) -> Path:
    try:
        relative = capture_path.relative_to(root / "captures")
    except ValueError:
        relative = Path(capture_path.name)
    return root / "screenshots" / relative.with_suffix(".png")


if __name__ == "__main__":
    raise SystemExit(main())
