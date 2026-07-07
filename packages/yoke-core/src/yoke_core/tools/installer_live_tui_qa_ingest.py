"""Import live installer/TUI campaign evidence into QA tables."""

from __future__ import annotations

import argparse
import contextlib
import io
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from yoke_core.domain import json_helper, qa
from yoke_core.domain.db_helpers import connect, query_scalar
from yoke_core.domain.qa_artifact_handle import local_handle, serialize_handle
from yoke_core.tools import installer_live_tui_harness as harness


REPORTS_DIR = "reports"
MANIFEST_NAME = "harness-manifest.json"


@dataclass(frozen=True)
class QATarget:
    item_id: int | None = None
    epic_id: int | None = None
    task_num: int | None = None
    deployment_run_id: str | None = None

    def validate(self) -> None:
        if (self.epic_id is None) != (self.task_num is None):
            raise ValueError("--epic-id and --task-num must be provided together")
        targets = 0
        if self.item_id is not None:
            targets += 1
        if self.epic_id is not None and self.task_num is not None:
            targets += 1
        if self.deployment_run_id:
            targets += 1
        if targets != 1:
            raise ValueError(
                "specify exactly one QA target: --item-id, "
                "--epic-id with --task-num, or --deployment-run-id"
            )

    def requirement_kwargs(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "epic_id": self.epic_id,
            "task_num": self.task_num,
            "deployment_run_id": self.deployment_run_id,
        }


@dataclass(frozen=True)
class ReportOccurrence:
    scenario_id: str
    assignment_id: str
    report_path: Path
    report: Mapping[str, object]
    scenario: Mapping[str, object]


def ingest_campaign(
    *,
    campaign_root: Path,
    target: QATarget,
    execute: bool,
    db_path: str | None = None,
    max_scenarios: int | None = None,
    allow_incomplete_evidence: bool = False,
) -> dict[str, object]:
    target.validate()
    manifest_path = campaign_root / MANIFEST_NAME
    manifest = _load_mapping(manifest_path, label="manifest")
    scenarios = _manifest_scenarios(manifest, max_scenarios=max_scenarios)
    occurrences = _report_occurrences(campaign_root)
    by_scenario = _occurrences_by_scenario(occurrences)
    evidence_summary = harness.collect_reports(campaign_root)
    orphan_scenarios = sorted(
        scenario_id
        for scenario_id in by_scenario
        if scenario_id not in {str(scenario["id"]) for scenario in scenarios}
    )
    requirement_specs = [
        _requirement_spec(manifest, scenario, target)
        for scenario in scenarios
    ]
    planned_runs = [
        (scenario, occurrence)
        for scenario in scenarios
        for occurrence in by_scenario.get(str(scenario["id"]), [])
    ]
    planned_artifact_count = sum(
        len(_artifact_specs(campaign_root, occurrence))
        for _, occurrence in planned_runs
    )
    summary: dict[str, object] = {
        "ok": True,
        "dry_run": not execute,
        "campaign_root": str(campaign_root),
        "manifest_path": str(manifest_path),
        "target": asdict(target),
        "scenario_count": len(scenarios),
        "requirement_count": len(requirement_specs),
        "run_count": len(planned_runs),
        "artifact_count": planned_artifact_count,
        "orphan_report_scenarios": orphan_scenarios,
        "evidence_ok": evidence_summary.get("ok") is True,
        "evidence_summary": evidence_summary,
    }
    if not execute:
        return summary
    if evidence_summary.get("ok") is not True and not allow_incomplete_evidence:
        raise ValueError(
            "campaign evidence is incomplete; rerun with "
            "--allow-incomplete-evidence to import anyway"
        )

    requirement_ids: dict[str, int] = {}
    created_requirements = 0
    reused_requirements = 0
    for scenario, spec in zip(scenarios, requirement_specs, strict=True):
        requirement_id, created = _ensure_requirement(db_path, target, spec)
        requirement_ids[str(scenario["id"])] = requirement_id
        if created:
            created_requirements += 1
        else:
            reused_requirements += 1

    run_ids: list[int] = []
    artifact_ids: list[int] = []
    for scenario, occurrence in planned_runs:
        scenario_id = str(scenario["id"])
        run_id = _add_run(
            db_path,
            requirement_id=requirement_ids[scenario_id],
            scenario=scenario,
            occurrence=occurrence,
        )
        run_ids.append(run_id)
        for artifact in _artifact_specs(campaign_root, occurrence):
            artifact_ids.append(_add_artifact(db_path, run_id=run_id, artifact=artifact))

    summary.update(
        {
            "created_requirement_count": created_requirements,
            "reused_requirement_count": reused_requirements,
            "requirement_ids": requirement_ids,
            "run_ids": run_ids,
            "artifact_ids": artifact_ids,
        }
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.tools.installer_live_tui_qa_ingest",
        description="Import installer live-TUI campaign evidence into QA tables.",
    )
    parser.add_argument("--campaign-root", required=True, type=Path)
    parser.add_argument("--db-path")
    parser.add_argument("--item-id", type=int)
    parser.add_argument("--epic-id", type=int)
    parser.add_argument("--task-num", type=int)
    parser.add_argument("--deployment-run-id")
    parser.add_argument("--max-scenarios", type=int)
    parser.add_argument("--allow-incomplete-evidence", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = ingest_campaign(
            campaign_root=args.campaign_root.expanduser(),
            target=QATarget(
                item_id=args.item_id,
                epic_id=args.epic_id,
                task_num=args.task_num,
                deployment_run_id=args.deployment_run_id,
            ),
            execute=args.execute,
            db_path=args.db_path,
            max_scenarios=args.max_scenarios,
            allow_incomplete_evidence=args.allow_incomplete_evidence,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    text = (
        f"requirements={payload['requirement_count']} "
        f"runs={payload['run_count']} artifacts={payload['artifact_count']}"
    )
    return _emit(payload, args.json, text)


def _load_mapping(path: Path, *, label: str) -> dict[str, object]:
    payload = json_helper.load_path(path)
    if not isinstance(payload, dict):
        raise ValueError(f"{label} root must be a JSON object: {path}")
    return payload


def _manifest_scenarios(
    manifest: Mapping[str, object],
    *,
    max_scenarios: int | None,
) -> list[dict[str, object]]:
    raw_scenarios = manifest.get("scenarios")
    if not isinstance(raw_scenarios, list) or not raw_scenarios:
        raise ValueError("manifest must contain at least one scenario")
    scenarios = [item for item in raw_scenarios if isinstance(item, dict)]
    if len(scenarios) != len(raw_scenarios):
        raise ValueError("every manifest scenario must be a JSON object")
    for index, scenario in enumerate(scenarios):
        if not str(scenario.get("id") or ""):
            raise ValueError(f"manifest scenario {index} is missing id")
    if max_scenarios is not None:
        if max_scenarios < 1:
            raise ValueError("max_scenarios must be at least 1")
        scenarios = scenarios[:max_scenarios]
    return scenarios


def _report_occurrences(campaign_root: Path) -> list[ReportOccurrence]:
    occurrences: list[ReportOccurrence] = []
    for report_path in sorted((campaign_root / REPORTS_DIR).glob("*.json")):
        report = _load_mapping(report_path, label="report")
        assignment_id = str(report.get("assignment_id") or report_path.stem)
        raw_scenarios = report.get("scenarios", [])
        if not isinstance(raw_scenarios, list):
            raise ValueError(f"report scenarios must be a JSON array: {report_path}")
        for scenario in raw_scenarios:
            if not isinstance(scenario, dict):
                continue
            scenario_id = str(scenario.get("scenario_id") or "")
            if not scenario_id:
                continue
            occurrences.append(
                ReportOccurrence(
                    scenario_id=scenario_id,
                    assignment_id=assignment_id,
                    report_path=report_path,
                    report=report,
                    scenario=scenario,
                )
            )
    return occurrences


def _occurrences_by_scenario(
    occurrences: Sequence[ReportOccurrence],
) -> dict[str, list[ReportOccurrence]]:
    grouped: dict[str, list[ReportOccurrence]] = {}
    for occurrence in occurrences:
        grouped.setdefault(occurrence.scenario_id, []).append(occurrence)
    return grouped


def _requirement_spec(
    manifest: Mapping[str, object],
    scenario: Mapping[str, object],
    target: QATarget,
) -> dict[str, object]:
    scenario_id = str(scenario["id"])
    target_env = str(scenario.get("target_env") or manifest.get("target_env") or "")
    capability_requirements = scenario.get("capability_requirements") or []
    if not isinstance(capability_requirements, list):
        capability_requirements = []
    policy = _success_policy(manifest, scenario)
    spec = {
        **target.requirement_kwargs(),
        "qa_kind": str(scenario.get("qa_kind") or "live-tui"),
        "qa_phase": "verification",
        "target_env": target_env or None,
        "blocking_mode": str(scenario.get("blocking_mode") or "blocking"),
        "requirement_source": "explicit",
        "success_policy": json_helper.dumps_compact(policy),
        "capability_requirements": json_helper.dumps_compact(
            [str(item) for item in capability_requirements]
        ),
        "suite_id": str(manifest.get("suite_id") or harness.SUITE_ID),
        "scenario_id": scenario_id,
    }
    return spec


def _success_policy(
    manifest: Mapping[str, object],
    scenario: Mapping[str, object],
) -> dict[str, object]:
    raw_policy = scenario.get("success_policy")
    policy = dict(raw_policy) if isinstance(raw_policy, dict) else {"type": "composite"}
    policy["harness"] = {
        "id": str(manifest.get("harness_id") or harness.HARNESS_ID),
        "suite_id": str(manifest.get("suite_id") or harness.SUITE_ID),
        "version": str(manifest.get("version") or ""),
    }
    policy["scenario"] = {
        "id": str(scenario["id"]),
        "wave": str(scenario.get("wave") or ""),
        "host_profile": str(scenario.get("host_profile") or ""),
        "flow": str(scenario.get("flow") or ""),
        "assertions": str(scenario.get("assertions") or ""),
    }
    return policy


def _ensure_requirement(
    db_path: str | None,
    target: QATarget,
    spec: Mapping[str, object],
) -> tuple[int, bool]:
    existing = _find_requirement(db_path, target, spec)
    if existing is not None:
        return existing, False
    kwargs = dict(spec)
    kwargs.pop("scenario_id", None)
    requirement_id = _quiet_call(qa.cmd_requirement_add, db_path=db_path, **kwargs)
    return int(requirement_id), True


def _find_requirement(
    db_path: str | None,
    target: QATarget,
    spec: Mapping[str, object],
) -> int | None:
    where = [
        "qa_kind = %s",
        "suite_id = %s",
        "success_policy = %s",
        "waived_at IS NULL",
    ]
    params: list[object] = [
        spec["qa_kind"],
        spec["suite_id"],
        spec["success_policy"],
    ]
    if target.item_id is not None:
        where.append(
            "item_id = %s AND epic_id IS NULL AND task_num IS NULL "
            "AND deployment_run_id IS NULL"
        )
        params.append(target.item_id)
    elif target.epic_id is not None and target.task_num is not None:
        where.append(
            "item_id IS NULL AND epic_id = %s AND task_num = %s "
            "AND deployment_run_id IS NULL"
        )
        params.extend([target.epic_id, target.task_num])
    else:
        where.append(
            "item_id IS NULL AND epic_id IS NULL AND task_num IS NULL "
            "AND deployment_run_id = %s"
        )
        params.append(target.deployment_run_id)
    conn = connect(path=db_path)
    try:
        value = query_scalar(
            conn,
            "SELECT id FROM qa_requirements WHERE "
            + " AND ".join(where)
            + " ORDER BY id LIMIT 1",
            tuple(params),
        )
    finally:
        conn.close()
    return int(value) if value is not None else None


def _add_run(
    db_path: str | None,
    *,
    requirement_id: int,
    scenario: Mapping[str, object],
    occurrence: ReportOccurrence,
) -> int:
    run_id = _quiet_call(
        qa.cmd_run_add,
        db_path=db_path,
        requirement_id=requirement_id,
        executor_type=str(
            scenario.get("executor_type")
            or occurrence.scenario.get("executor_type")
            or "agent"
        ),
        qa_kind=None,
        verdict=_verdict_for_occurrence(occurrence),
        raw_result=json_helper.dumps_compact(_raw_result(occurrence)),
        duration_ms=_duration_ms(occurrence.report),
    )
    return int(run_id)


def _add_artifact(
    db_path: str | None,
    *,
    run_id: int,
    artifact: Mapping[str, object],
) -> int:
    artifact_id = _quiet_call(
        qa.cmd_artifact_add,
        db_path=db_path,
        run_id=run_id,
        artifact_type=str(artifact["artifact_type"]),
        content_type=str(artifact["content_type"]),
        artifact_handle=str(artifact["artifact_handle"]),
        metadata=json_helper.dumps_compact(artifact["metadata"]),
    )
    return int(artifact_id)


def _artifact_specs(
    campaign_root: Path,
    occurrence: ReportOccurrence,
) -> list[dict[str, object]]:
    artifacts = [
        _artifact_spec(
            occurrence.report_path,
            artifact_type="report",
            content_type="application/json",
            metadata={
                "assignment_id": occurrence.assignment_id,
                "scenario_id": occurrence.scenario_id,
                "source": "report",
            },
        )
    ]
    for capture in _evidence_list(occurrence.scenario, "captures"):
        raw_path = str(capture.get("path") or "")
        if not raw_path:
            continue
        path = _resolve_campaign_path(campaign_root, raw_path)
        artifacts.append(
            _artifact_spec(
                path,
                artifact_type="log",
                content_type="text/plain",
                metadata=_evidence_metadata(occurrence, "capture", capture),
            )
        )
    for screenshot in _evidence_list(occurrence.scenario, "screenshots"):
        raw_path = str(screenshot.get("path") or "")
        if not raw_path:
            continue
        path = _resolve_campaign_path(campaign_root, raw_path)
        artifacts.append(
            _artifact_spec(
                path,
                artifact_type="screenshot",
                content_type="image/png",
                metadata=_evidence_metadata(occurrence, "screenshot", screenshot),
            )
        )
    return artifacts


def _artifact_spec(
    path: Path,
    *,
    artifact_type: str,
    content_type: str,
    metadata: Mapping[str, object],
) -> dict[str, object]:
    return {
        "artifact_type": artifact_type,
        "content_type": content_type,
        "artifact_handle": serialize_handle(local_handle(str(path), content_type)),
        "metadata": dict(metadata),
    }


def _evidence_list(
    scenario: Mapping[str, object],
    key: str,
) -> list[dict[str, object]]:
    raw = scenario.get(key) or []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _evidence_metadata(
    occurrence: ReportOccurrence,
    evidence_type: str,
    evidence: Mapping[str, object],
) -> dict[str, object]:
    metadata = {
        "assignment_id": occurrence.assignment_id,
        "scenario_id": occurrence.scenario_id,
        "source": evidence_type,
        "report_path": str(occurrence.report_path),
    }
    for key in ("name", "sha256", "bytes", "matches_capture"):
        if key in evidence:
            metadata[key] = evidence[key]
    return metadata


def _resolve_campaign_path(campaign_root: Path, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    return campaign_root / path


def _verdict_for_occurrence(occurrence: ReportOccurrence) -> str:
    result = str(
        occurrence.scenario.get("result")
        or occurrence.report.get("overall_result")
        or ""
    ).lower()
    if result in {"pass", "fail", "error"}:
        return result
    if str(occurrence.scenario.get("failure") or "").strip():
        return "fail"
    return "inconclusive"


def _raw_result(occurrence: ReportOccurrence) -> dict[str, object]:
    captures = _evidence_list(occurrence.scenario, "captures")
    screenshots = _evidence_list(occurrence.scenario, "screenshots")
    return {
        "assignment_id": occurrence.assignment_id,
        "scenario_id": occurrence.scenario_id,
        "report_path": str(occurrence.report_path),
        "host_id": str(occurrence.report.get("host_id") or ""),
        "result": str(
            occurrence.scenario.get("result")
            or occurrence.report.get("overall_result")
            or ""
        ),
        "failure": str(occurrence.scenario.get("failure") or ""),
        "assertions": occurrence.scenario.get("assertions") or {},
        "capture_count": len(captures),
        "screenshot_count": len(screenshots),
    }


def _duration_ms(report: Mapping[str, object]) -> int | None:
    started = _parse_time(str(report.get("started_at") or ""))
    completed = _parse_time(str(report.get("completed_at") or ""))
    if started is None or completed is None:
        return None
    duration = completed - started
    milliseconds = int(duration.total_seconds() * 1000)
    return milliseconds if milliseconds >= 0 else None


def _parse_time(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _quiet_call(fn: Callable[..., Any], *args: object, **kwargs: object) -> Any:
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


def _emit(
    payload: dict[str, object],
    as_json: bool,
    text: str,
) -> int:
    if as_json:
        print(json_helper.dumps_pretty(payload), end="")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
