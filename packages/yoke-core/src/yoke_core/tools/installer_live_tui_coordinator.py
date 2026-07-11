"""Coordinate small batches of live installer/TUI assignments."""

from __future__ import annotations

import argparse
import math
import os
import shlex
import sys
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from yoke_contracts.api_urls import HOSTED_PROD_URL, HOSTED_STAGE_URL

from yoke_core.domain import json_helper
from yoke_core.tools import installer_live_tui_fleet as fleet
from yoke_core.tools import installer_live_tui_harness as harness
from yoke_core.tools import installer_live_tui_runner as scenario_runner
from yoke_core.tools.installer_live_tui_harness import Assignment


DEFAULT_PLAN_NAME = "coordinator-plan.json"
DEFAULT_CAMPAIGN_PLAN_NAME = "campaign-plan.json"
DEFAULT_RECIPE_COMPILE_NAME = "recipe-compile-summary.json"
DEFAULT_RECIPE_STUBS_DIR = "recipe-stubs"
DEFAULT_RUN_SPECS_DIR = "run-specs"
DEFAULT_PANE = scenario_runner.DEFAULT_PANE
READY_RECIPE_STATUS = "ready"
PATH_HEALTH_EXPECTED_TEXT = (
    "A new Terminal login shell sees:",
    "your shell is ready",
)
PATH_HEALTH_PLAIN_EXPECTED_TEXT = (
    "A new Terminal login shell sees:",
    "OK yoke",
    "up/down navigate",
)
PATH_HEALTH_CONNECT_EXPECTED_TEXT = (
    *PATH_HEALTH_EXPECTED_TEXT,
    "Where should this Yoke live?",
    "This machine",
    "upyoke.com",
)
KNOWN_RECIPE_IDS = {
    "INSTALL-SMOKE-001",
    "INSTALL-SMOKE-002",
    "INSTALL-SMOKE-003",
    "INSTALL-SMOKE-004",
    "INSTALL-SMOKE-005",
    "INSTALL-UV-001",
    "INSTALL-UV-002",
    "INSTALL-UV-003",
    "INSTALL-UV-004",
    "INSTALL-UV-005",
    "INSTALL-UV-006",
    "INSTALL-UV-007",
    "INSTALL-UV-008",
    "INSTALL-UV-009",
    "INSTALL-UV-010",
    "INSTALL-UV-011",
    "INSTALL-UV-012",
    "PATH-001",
    "PATH-002",
    "PATH-003",
    "PATH-004",
    "PATH-005",
    "PATH-006",
    "PATH-007",
    "PATH-008",
    "AUTH-001",
    "AUTH-002",
    "AUTH-003",
    "AUTH-004",
    "AUTH-005",
    "AUTH-006",
    "AUTH-007",
    "AUTH-008",
    "AUTH-009",
    "AUTH-010",
    "AUTH-011",
    *(f"GITHUB-{number:03d}" for number in range(1, 42)),
    "PROJECT-SOURCE-001",
    "PROJECT-SOURCE-002",
    "PROJECT-SOURCE-003",
    "PROJECT-SOURCE-004",
    "PROJECT-SOURCE-005",
    "PROJECT-SOURCE-006",
    "PROJECT-SOURCE-007",
    "PROJECT-SOURCE-008",
    "PROJECT-SOURCE-009",
    "PROJECT-SOURCE-010",
    "PROJECT-SOURCE-011",
    "PROJECT-SOURCE-012",
    "PROJECT-SOURCE-013",
    "PROJECT-SOURCE-014",
    "PROJECT-SOURCE-015",
    "PROJECT-SOURCE-016",
    "PROJECT-SOURCE-017",
    "PROJECT-SOURCE-018",
    "PROJECT-SOURCE-019",
    "PROJECT-META-001",
    "PROJECT-META-002",
    "PROJECT-META-003",
    "PROJECT-META-004",
    "PROJECT-META-005",
    "PROJECT-META-006",
    "PROJECT-META-007",
    "PROJECT-META-008",
    "PROJECT-META-009",
    "PROJECT-META-010",
    "PROJECT-META-011",
    "PUBLISH-001",
    "PUBLISH-002",
    "PUBLISH-003",
    "PUBLISH-004",
    "PUBLISH-005",
    "PUBLISH-006",
    "PUBLISH-007",
    "PUBLISH-008",
    "PUBLISH-009",
    "PUBLISH-010",
    "PUBLISH-011",
    "PUBLISH-012",
    "PUBLISH-013",
    "APPLY-001",
    "APPLY-002",
    "APPLY-003",
    "APPLY-004",
    "APPLY-005",
    "APPLY-006",
    "APPLY-007",
    "APPLY-008",
    "APPLY-009",
    "APPLY-010",
    "APPLY-011",
    "APPLY-012",
    "TERM-001",
    "TERM-002",
    "TERM-003",
    "TERM-004",
    "TERM-005",
    "TERM-006",
    "TERM-007",
    "TERM-008",
    "TERM-009",
    "TERM-010",
    "TERM-011",
    "TERM-012",
    "STATE-001",
    "STATE-002",
    "STATE-003",
    "STATE-004",
    "STATE-005",
    "STATE-006",
    "STATE-007",
    "STATE-008",
    "STATE-009",
}
MANUAL_GITHUB_APP_RECIPE_IDS = {
    *(f"GITHUB-{number:03d}" for number in range(2, 42)),
    "PROJECT-SOURCE-006",
    "PROJECT-META-008",
    *(f"PUBLISH-{number:03d}" for number in range(2, 14)),
    "APPLY-005",
    "APPLY-008",
    "STATE-002",
    "STATE-007",
}
PROD_BASE_URL = HOSTED_PROD_URL
PROD_TOKEN_FILE_ENV = "YOKE_INSTALLER_LIVE_PROD_TOKEN_FILE"
REMOTE_PROD_TOKEN_PATH = "/tmp/yoke-prod.token"
REMOTE_STAGE_TOKEN_PATH = "/tmp/yoke-stage.token"
REMOTE_EMPTY_TOKEN_PATH = "/tmp/yoke-empty.token"
REMOTE_FAKE_YOKE_TOKEN_PATH = "/tmp/yoke-fake-api.token"
REMOTE_INVALID_TOKEN_PATH = "/tmp/yoke-invalid.token"
REMOTE_MISSING_TOKEN_PATH = "/tmp/yoke-missing.token"
REMOTE_STORED_YOKE_TOKEN_PATH = "/tmp/yoke-api.token"
AUTH_FAKE_CUSTOM_API_PORT = 19087
AUTH_FAKE_NO_ACCESS_API_PORT = 19088
AUTH_FAKE_MANY_ACCESS_API_PORT = 19089
AUTH_FAKE_TOKEN_VALUE = "test-token-for-live-recipe"
STATE_TUI_SETUP_START_DELAY = 45.0
PROJECT_SOURCE_NEW_PATH = "/tmp/yoke-project-source-new"
PROJECT_SOURCE_EXISTING_PATH = "/tmp/yoke-project-source-existing"
PROJECT_SOURCE_CONFLICT_PATH = "/tmp/yoke-project-source-conflict"
PROJECT_SOURCE_CLONE_MAIN_PATH = "/tmp/yoke-project-source-clone-main"
PROJECT_SOURCE_CLONE_MASTER_PATH = "/tmp/yoke-project-source-clone-master"
PROJECT_SOURCE_MAIN_REMOTE_PATH = (
    "/tmp/yoke-project-source-remotes/github.com/recipe/main-source.git"
)
PROJECT_SOURCE_MASTER_REMOTE_PATH = (
    "/tmp/yoke-project-source-remotes/github.com/recipe/master-source.git"
)
PROJECT_SOURCE_MAIN_REMOTE_URL = f"file://{PROJECT_SOURCE_MAIN_REMOTE_PATH}"
PROJECT_SOURCE_MASTER_REMOTE_URL = f"file://{PROJECT_SOURCE_MASTER_REMOTE_PATH}"
PROJECT_SOURCE_MISSING_REMOTE_URL = (
    "file:///tmp/yoke-project-source-remotes/github.com/recipe/missing-source.git"
)
PROJECT_SOURCE_DEV_YOKE_API_PORT = 19106
PROJECT_SOURCE_DEV_NO_ACCESS_API_PORT = 19107
PROJECT_SOURCE_DEV_FRESH_YOKE_API_PORT = 19112
PROJECT_SOURCE_DEV_EXISTING_YOKE_API_PORT = 19114
PROJECT_SOURCE_DEV_CONFLICT_YOKE_API_PORT = 19116
PROJECT_SOURCE_DEV_DEFAULT_YOKE_API_PORT = 19118
PROJECT_SOURCE_DEV_PUSH_YOKE_API_PORT = 19120
PROJECT_SOURCE_DEV_FRESH_PATH = "/tmp/yoke-project-source-dev-fresh"
PROJECT_SOURCE_DEV_EXISTING_PATH = "/tmp/yoke-project-source-dev-existing"
PROJECT_SOURCE_DEV_CONFLICT_PATH = "/tmp/yoke-project-source-dev-conflict"
PROJECT_SOURCE_DEV_DEFAULT_PATH = "/tmp/yoke-project-source-dev-default"
PROJECT_SOURCE_DEV_PUSH_PATH = "/tmp/yoke-project-source-dev-push"
PROJECT_SOURCE_DEV_REMOTE_PATH = (
    "/tmp/yoke-project-source-dev-remotes/github.com/upyoke/yoke.git"
)
PROJECT_SOURCE_DEV_REMOTE_URL = f"file://{PROJECT_SOURCE_DEV_REMOTE_PATH}"
PROJECT_SOURCE_DEV_SEED_PATH = "/tmp/yoke-project-source-dev-remotes/source-dev-seed"
PROJECT_SOURCE_DEV_GIT_CONFIG_PATH = "/tmp/yoke-source-dev-post-apply.gitconfig"
PROJECT_SOURCE_DEV_APPLY_REPORT_PATH = "/tmp/yoke-source-dev-post-apply.json"
PROJECT_SOURCE_DEV_CHECKOUT_OK = "source-dev checkout files: ok"
PROJECT_SOURCE_DEV_GIT_OK = "source-dev git history: ok"
PROJECT_SOURCE_DEV_LINKS_OK = "source-dev source-link files: ok"
PROJECT_SOURCE_DEV_MANIFEST_OK = "source-dev source-link manifest: ok"
PROJECT_SOURCE_DEV_HOOKS_OK = "source-dev git hooks: ok"
PROJECT_SOURCE_DEV_POST_APPLY_OK = "source-dev post-apply proof: ok"
PROJECT_META_CHECKOUT_PATH = "/tmp/yoke-project-meta-checkout"
PROJECT_META_CREATE_PATH = "/tmp/yoke-project-meta-create"
PROJECT_META_BOARD_DATA_FAIL_PATH = "/tmp/yoke-project-meta-board-data-fail"
PROJECT_META_TILDE_IMMEDIATE_PATH = "~/code/yoke-project-meta-immediate"
PROJECT_META_TILDE_SETTLED_PATH = "~/code/yoke-project-meta-settled"
PROJECT_META_FAKE_YOKE_API_PORT = 19109
PROJECT_META_LONG_TEXT_INPUT = "a" * 70
PROJECT_PUBLISH_LOCAL_PATH = "/tmp/yoke-project-publish-local"
APPLY_CREATE_PATH = "/tmp/yoke-apply-create"
APPLY_CLONE_PATH = "/tmp/yoke-apply-clone"
APPLY_PROJECT_DENIED_PATH = "/tmp/yoke-apply-project-denied"
APPLY_CLONE_CONFLICT_PATH = "/tmp/yoke-apply-clone-conflict"
APPLY_BOARD_FAIL_PATH = "/tmp/yoke-apply-board-fail"
APPLY_RESUME_PATH = "/tmp/yoke-apply-resume"
APPLY_REPORT_AUDIT_PATH = "/tmp/yoke-apply-report-audit"
APPLY_CTRL_C_PATH = "/tmp/yoke-apply-ctrl-c"
APPLY_PROJECT_DENIED_YOKE_API_PORT = 19119
APPLY_SUCCESS_YOKE_API_PORT = 19120
APPLY_BOARD_FAIL_YOKE_API_PORT = 19121
APPLY_RESUME_YOKE_API_PORT = 19122
APPLY_CTRL_C_YOKE_API_PORT = 19123
STATE_ONE_PROJECT_YOKE_API_PORT = 19124
STATE_MULTI_PROJECT_YOKE_API_PORT = 19125
STATE_MISSING_PROJECT_YOKE_API_PORT = 19126
STATE_ENV_SWITCH_YOKE_API_PORT = 19127
STATE_PROJECT_ONE_PATH = "/tmp/yoke-state-project-one"
STATE_PROJECT_TWO_PATH = "/tmp/yoke-state-project-two"
STATE_PROJECT_MISSING_PATH = "/tmp/yoke-state-project-missing"
TERM_LONG_PROJECT_NAME = "yoke-term-long-project-name-" + ("a" * 32)
TERM_LONG_PROJECT_PATH = f"/tmp/{TERM_LONG_PROJECT_NAME}"


def assign_hosts(
    *,
    campaign_root: Path,
    ledger_path: Path,
    slots_per_host: int = 1,
    max_assignments: int | None = None,
) -> dict[str, object]:
    if slots_per_host < 1:
        raise ValueError("slots_per_host must be at least 1")
    assignments = _load_assignments(campaign_root, max_assignments=max_assignments)
    ledger = _load_ledger(ledger_path)
    host_slots = _host_slots_by_profile(ledger, slots_per_host=slots_per_host)
    assigned: list[dict[str, object]] = []
    blocked: list[dict[str, object]] = []

    for assignment in assignments:
        slots = host_slots.get(assignment.host_profile, [])
        if not slots:
            blocked.append(
                {
                    "assignment_id": assignment.assignment_id,
                    "host_profile": assignment.host_profile,
                    "scenario_ids": list(assignment.scenario_ids),
                    "reason": "no available host with matching profile",
                }
            )
            continue
        host = slots.pop(0)
        assigned.append(
            {
                "assignment_id": assignment.assignment_id,
                "host_id": str(host.get("host_id") or ""),
                "instance_id": str(host.get("instance_id") or ""),
                "public_ip": str(host.get("public_ip") or ""),
                "ssh_user": str(host.get("ssh_user") or ledger.get("ssh_user") or ""),
                "host_profile": assignment.host_profile,
                "scenario_ids": list(assignment.scenario_ids),
            }
        )

    payload = {
        "ok": not blocked,
        "campaign_root": str(campaign_root),
        "ledger_path": str(ledger_path),
        "assignment_count": len(assignments),
        "assigned_count": len(assigned),
        "blocked_count": len(blocked),
        "assigned": assigned,
        "blocked": blocked,
    }
    json_helper.dump_path(campaign_root / DEFAULT_PLAN_NAME, payload)
    return payload


def plan_campaign(
    *,
    plan_path: Path,
    campaign_root: Path,
    endpoint: str = harness.DEFAULT_ENDPOINT,
    assignment_size: int = harness.DEFAULT_ASSIGNMENT_SIZE,
    slots_per_host: int = 1,
    max_scenarios: int | None = None,
    include_mac: bool = False,
) -> dict[str, object]:
    if slots_per_host < 1:
        raise ValueError("slots_per_host must be at least 1")
    if assignment_size < 1:
        raise ValueError("assignment_size must be at least 1")
    scenarios = harness.load_scenarios_from_plan(plan_path)
    mac_scenarios = [scenario for scenario in scenarios if _is_mac_scenario(scenario)]
    selected_scenarios = [
        scenario
        for scenario in scenarios
        if include_mac or not _is_mac_scenario(scenario)
    ]
    if max_scenarios is not None:
        if max_scenarios < 1:
            raise ValueError("max_scenarios must be at least 1")
        selected_scenarios = selected_scenarios[:max_scenarios]
    manifest = harness.build_manifest(
        selected_scenarios,
        campaign_root=campaign_root,
        endpoint=endpoint,
    )
    assignments = harness.build_assignments(
        selected_scenarios,
        campaign_root=campaign_root,
        endpoint=endpoint,
        assignment_size=assignment_size,
    )
    written = harness.write_campaign_files(
        campaign_root=campaign_root,
        manifest=manifest,
        assignments=assignments,
    )
    recipe_paths = _write_recipe_stubs(
        campaign_root,
        selected_scenarios,
        endpoint=endpoint,
    )
    profile_demands = _profile_demands(
        assignments,
        slots_per_host=slots_per_host,
    )
    recipe_blockers = _recipe_blockers(
        selected_scenarios,
        recipe_paths,
    )
    payload = {
        "ok": True,
        "campaign_executable": not recipe_blockers,
        "campaign_root": str(campaign_root),
        "plan_path": str(plan_path),
        "endpoint": endpoint,
        "scenario_count": len(selected_scenarios),
        "mac_scenario_count": len(mac_scenarios),
        "mac_included": include_mac,
        "assignment_count": len(assignments),
        "assignment_size": assignment_size,
        "slots_per_host": slots_per_host,
        "profile_demands": profile_demands,
        "recipe_stub_count": len(recipe_paths),
        "recipe_blocker_count": len(recipe_blockers),
        "recipe_blockers": recipe_blockers,
        "recipe_stub_paths": [str(path) for path in recipe_paths],
        "campaign_files": written,
    }
    json_helper.dump_path(campaign_root / DEFAULT_CAMPAIGN_PLAN_NAME, payload)
    return payload


def compile_recipes(
    *,
    campaign_root: Path,
    host_plan_path: Path | None = None,
    recipe_dir: Path | None = None,
    spec_dir: Path | None = None,
    runs_per_spec: int = 1,
    max_runs: int | None = None,
) -> dict[str, object]:
    if runs_per_spec < 1:
        raise ValueError("runs_per_spec must be at least 1")
    if max_runs is not None and max_runs < 1:
        raise ValueError("max_runs must be at least 1")
    resolved_host_plan = host_plan_path or campaign_root / DEFAULT_PLAN_NAME
    resolved_recipe_dir = recipe_dir or campaign_root / DEFAULT_RECIPE_STUBS_DIR
    resolved_spec_dir = spec_dir or campaign_root / DEFAULT_RUN_SPECS_DIR
    assignments = {
        assignment.assignment_id: assignment
        for assignment in _load_assignments(campaign_root, max_assignments=None)
    }
    host_plan = _load_host_plan(resolved_host_plan)
    runs: list[dict[str, object]] = []
    blocked: list[dict[str, object]] = []

    for item in host_plan.get("blocked", []):
        if isinstance(item, dict):
            blocked.append(
                {
                    "assignment_id": str(item.get("assignment_id") or ""),
                    "scenario_ids": [
                        str(value) for value in item.get("scenario_ids", [])
                    ],
                    "reason": str(item.get("reason") or "assignment is blocked"),
                }
            )
    for assigned in _assigned_host_entries(host_plan):
        assignment_id = str(assigned.get("assignment_id") or "")
        assignment = assignments.get(assignment_id)
        if assignment is None:
            blocked.append(
                {
                    "assignment_id": assignment_id,
                    "reason": "assignment JSON is missing",
                }
            )
            continue
        host_id = str(assigned.get("host_id") or "")
        if not host_id:
            blocked.append(
                {
                    "assignment_id": assignment_id,
                    "scenario_ids": list(assignment.scenario_ids),
                    "reason": "host assignment is missing host_id",
                }
            )
            continue
        for scenario_id in assignment.scenario_ids:
            recipe_path = resolved_recipe_dir / f"{scenario_id}.json"
            if not recipe_path.is_file():
                blocked.append(
                    {
                        "assignment_id": assignment_id,
                        "scenario_id": scenario_id,
                        "recipe_path": str(recipe_path),
                        "reason": "recipe JSON is missing",
                    }
                )
                continue
            recipe = _load_recipe(recipe_path)
            blocker = _recipe_compile_blocker(
                recipe,
                recipe_path=recipe_path,
                assignment_id=assignment_id,
                scenario_id=scenario_id,
            )
            if blocker is not None:
                blocked.append(blocker)
                continue
            run = _run_from_recipe(
                recipe,
                assignment_id=assignment_id,
                scenario_id=scenario_id,
                host_id=host_id,
                host_profile=assignment.host_profile,
            )
            runs.append(run)
            if max_runs is not None and len(runs) >= max_runs:
                break
        if max_runs is not None and len(runs) >= max_runs:
            break

    spec_paths = _write_run_specs(
        campaign_root=campaign_root,
        ledger_path=str(host_plan.get("ledger_path") or ""),
        spec_dir=resolved_spec_dir,
        runs=runs,
        runs_per_spec=runs_per_spec,
    )
    payload = {
        "ok": bool(runs) and not blocked,
        "campaign_root": str(campaign_root),
        "host_plan_path": str(resolved_host_plan),
        "recipe_dir": str(resolved_recipe_dir),
        "spec_dir": str(resolved_spec_dir),
        "runs_per_spec": runs_per_spec,
        "run_count": len(runs),
        "run_spec_count": len(spec_paths),
        "run_spec_paths": [str(path) for path in spec_paths],
        "blocked_count": len(blocked),
        "blocked": blocked,
    }
    json_helper.dump_path(campaign_root / DEFAULT_RECIPE_COMPILE_NAME, payload)
    return payload


def seed_known_recipes(
    *,
    campaign_root: Path,
    endpoint: str = harness.DEFAULT_ENDPOINT,
    recipe_dir: Path | None = None,
    scenario_ids: Sequence[str] = (),
    overwrite: bool = False,
) -> dict[str, object]:
    resolved_recipe_dir = recipe_dir or campaign_root / DEFAULT_RECIPE_STUBS_DIR
    if not resolved_recipe_dir.is_dir():
        raise ValueError(f"recipe directory is missing: {resolved_recipe_dir}")
    requested = {scenario_id for scenario_id in scenario_ids if scenario_id}
    base_url = fleet._base_url_for_endpoint(endpoint)  # noqa: SLF001
    seeded: list[dict[str, object]] = []
    skipped_ready: list[dict[str, object]] = []
    unseeded: list[dict[str, object]] = []

    for path in sorted(resolved_recipe_dir.glob("*.json")):
        recipe = _load_recipe(path)
        scenario_id = str(recipe.get("scenario_id") or path.stem)
        if requested and scenario_id not in requested:
            continue
        template = _known_recipe_template(scenario_id, base_url)
        if template is None:
            reason = (
                "manual GitHub App validation requires an HTTPS device-flow "
                "and installation fixture"
                if scenario_id in MANUAL_GITHUB_APP_RECIPE_IDS
                else "no grounded recipe template is available"
            )
            unseeded.append(
                {
                    "scenario_id": scenario_id,
                    "recipe_path": str(path),
                    "reason": reason,
                }
            )
            continue
        if recipe.get("status") == READY_RECIPE_STATUS and not overwrite:
            skipped_ready.append(
                {
                    "scenario_id": scenario_id,
                    "recipe_path": str(path),
                    "reason": "ready recipe preserved",
                }
            )
            continue
        ready_recipe = {
            **recipe,
            **template,
            "scenario_id": scenario_id,
            "status": READY_RECIPE_STATUS,
            "next_step": "Compile after host assignment.",
        }
        ready_recipe.pop("blocked_reason", None)
        json_helper.dump_path(path, ready_recipe)
        seeded.append({"scenario_id": scenario_id, "recipe_path": str(path)})

    payload = {
        "ok": True,
        "campaign_root": str(campaign_root),
        "recipe_dir": str(resolved_recipe_dir),
        "endpoint": endpoint,
        "requested_count": len(requested),
        "known_recipe_count": len(KNOWN_RECIPE_IDS),
        "seeded_count": len(seeded),
        "skipped_ready_count": len(skipped_ready),
        "unseeded_count": len(unseeded),
        "seeded": seeded,
        "skipped_ready": skipped_ready,
        "unseeded": unseeded,
    }
    json_helper.dump_path(campaign_root / "recipe-seed-summary.json", payload)
    return payload


def run_batch(
    *,
    spec_path: Path,
    execute: bool,
    campaign_root: Path | None = None,
    ledger_path: Path | None = None,
    max_wall_seconds: float | None = None,
    runner: scenario_runner.capture_tool.CommandRunner | None = None,
    sleeper=scenario_runner.time.sleep,  # noqa: ANN001
) -> dict[str, object]:
    spec = _load_run_spec(spec_path)
    resolved_campaign_root = campaign_root or Path(str(spec.get("campaign_root") or ""))
    resolved_ledger_path = ledger_path or Path(str(spec.get("ledger") or ""))
    if not str(resolved_campaign_root):
        raise ValueError("campaign_root is required in the spec or CLI")
    if not str(resolved_ledger_path):
        raise ValueError("ledger is required in the spec or CLI")
    runs = _spec_runs(spec)
    if max_wall_seconds is not None:
        runs = [{**item, "max_wall_seconds": max_wall_seconds} for item in runs]
    if not execute:
        return {
            "ok": True,
            "dry_run": True,
            "campaign_root": str(resolved_campaign_root),
            "ledger_path": str(resolved_ledger_path),
            "run_count": len(runs),
            "runs": runs,
        }

    selected_runner = runner or scenario_runner.capture_tool.CommandRunner()
    results: list[dict[str, object]] = []
    for item in runs:
        result = _run_one(
            item,
            campaign_root=resolved_campaign_root,
            ledger_path=resolved_ledger_path,
            runner=selected_runner,
            sleeper=sleeper,
        )
        results.append(result)
    summary = {
        "ok": all(result.get("ok") is True for result in results),
        "campaign_root": str(resolved_campaign_root),
        "ledger_path": str(resolved_ledger_path),
        "run_count": len(results),
        "results": results,
        "written_at": _now_iso(),
    }
    summary_path = _write_summary(resolved_campaign_root, summary)
    summary["summary_path"] = str(summary_path)
    return summary


def run_waves(
    *,
    spec_dir: Path,
    execute: bool,
    max_parallel: int = 4,
    max_specs: int | None = None,
    max_wall_seconds: float | None = None,
    campaign_root: Path | None = None,
    ledger_path: Path | None = None,
    runner_factory: Callable[[], scenario_runner.capture_tool.CommandRunner]
    | None = None,
    sleeper=scenario_runner.time.sleep,  # noqa: ANN001
) -> dict[str, object]:
    if max_parallel < 1:
        raise ValueError("max_parallel must be at least 1")
    spec_paths = _load_spec_paths(spec_dir, max_specs=max_specs)
    dry_runs = [
        run_batch(
            spec_path=path,
            execute=False,
            campaign_root=campaign_root,
            ledger_path=ledger_path,
            max_wall_seconds=max_wall_seconds,
        )
        for path in spec_paths
    ]
    if not execute:
        return {
            "ok": True,
            "dry_run": True,
            "spec_dir": str(spec_dir),
            "spec_count": len(spec_paths),
            "max_parallel": max_parallel,
            "max_wall_seconds": max_wall_seconds,
            "run_count": sum(int(result.get("run_count") or 0) for result in dry_runs),
            "batches": [
                {
                    "spec_path": str(path),
                    "run_count": result.get("run_count"),
                    "campaign_root": result.get("campaign_root"),
                    "ledger_path": result.get("ledger_path"),
                }
                for path, result in zip(spec_paths, dry_runs, strict=True)
            ],
        }

    results = _execute_wave_specs(
        spec_paths=spec_paths,
        dry_runs=dry_runs,
        max_parallel=max_parallel,
        max_wall_seconds=max_wall_seconds,
        campaign_root=campaign_root,
        ledger_path=ledger_path,
        runner_factory=runner_factory,
        sleeper=sleeper,
    )
    finished = [result for result in results if result is not None]
    summary_root = (
        campaign_root
        or _campaign_root_from_batch_results(finished)
        or _campaign_root_from_batch_results(dry_runs)
        or _campaign_root_from_spec_dir(spec_dir)
    )
    summary = {
        "ok": all(result.get("ok") is True for result in finished),
        "spec_dir": str(spec_dir),
        "spec_count": len(spec_paths),
        "max_parallel": max_parallel,
        "max_wall_seconds": max_wall_seconds,
        "run_count": sum(int(result.get("run_count") or 0) for result in finished),
        "results": finished,
        "written_at": _now_iso(),
    }
    if summary_root is not None:
        summary_path = _write_wave_summary(summary_root, summary)
        summary["summary_path"] = str(summary_path)
    return summary


def _execute_wave_specs(
    *,
    spec_paths: Sequence[Path],
    dry_runs: Sequence[Mapping[str, object]],
    max_parallel: int,
    max_wall_seconds: float | None,
    campaign_root: Path | None,
    ledger_path: Path | None,
    runner_factory: Callable[[], scenario_runner.capture_tool.CommandRunner] | None,
    sleeper,  # noqa: ANN001
) -> list[dict[str, object]]:
    results: list[dict[str, object] | None] = [None] * len(spec_paths)
    host_sets = [_host_ids_from_dry_run(result) for result in dry_runs]
    pending = list(range(len(spec_paths)))
    active_hosts: set[str] = set()
    max_workers = min(max_parallel, len(spec_paths))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {}
        while pending or futures:
            submitted = False
            while len(futures) < max_workers and pending:
                selected = _next_schedulable_index(
                    pending,
                    host_sets,
                    active_hosts=active_hosts,
                )
                if selected is None:
                    break
                pending.remove(selected)
                hosts = host_sets[selected]
                active_hosts.update(hosts)
                future = pool.submit(
                    run_batch,
                    spec_path=spec_paths[selected],
                    execute=True,
                    campaign_root=campaign_root,
                    ledger_path=ledger_path,
                    max_wall_seconds=max_wall_seconds,
                    runner=runner_factory() if runner_factory is not None else None,
                    sleeper=sleeper,
                )
                futures[future] = (selected, hosts)
                submitted = True
            if not futures:
                continue
            if submitted and len(futures) < max_workers and pending:
                continue
            done, _pending_futures = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                index, hosts = futures.pop(future)
                active_hosts.difference_update(hosts)
                try:
                    results[index] = future.result()
                except Exception as exc:  # noqa: BLE001
                    results[index] = {
                        "ok": False,
                        "spec_path": str(spec_paths[index]),
                        "failure": str(exc),
                    }
    return [result for result in results if result is not None]


def _host_ids_from_dry_run(result: Mapping[str, object]) -> set[str]:
    host_ids = set()
    for run in result.get("runs", []):
        if isinstance(run, Mapping):
            host_id = str(run.get("host_id") or "").strip()
            if host_id:
                host_ids.add(host_id)
    return host_ids


def _next_schedulable_index(
    pending: Sequence[int],
    host_sets: Sequence[set[str]],
    *,
    active_hosts: set[str],
) -> int | None:
    for index in pending:
        hosts = host_sets[index]
        if not hosts or active_hosts.isdisjoint(hosts):
            return index
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.tools.installer_live_tui_coordinator",
        description="Shard and run small live installer/TUI assignment batches.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    assign = subparsers.add_parser("assign-hosts")
    assign.add_argument("--campaign-root", required=True, type=Path)
    assign.add_argument("--ledger", required=True, type=Path)
    assign.add_argument("--slots-per-host", type=int, default=1)
    assign.add_argument("--max-assignments", type=int)
    assign.add_argument("--json", action="store_true")

    run = subparsers.add_parser("run-batch")
    run.add_argument("--spec", required=True, type=Path)
    run.add_argument("--campaign-root", type=Path)
    run.add_argument("--ledger", type=Path)
    run.add_argument(
        "--max-wall-seconds",
        type=float,
        help="Override each scenario wall-clock cap; pass 0 to disable.",
    )
    run.add_argument("--execute", action="store_true")
    run.add_argument("--json", action="store_true")

    campaign = subparsers.add_parser("plan-campaign")
    campaign.add_argument("--plan", required=True, type=Path)
    campaign.add_argument("--campaign-root", required=True, type=Path)
    campaign.add_argument("--endpoint", default=harness.DEFAULT_ENDPOINT)
    campaign.add_argument(
        "--assignment-size",
        type=int,
        default=harness.DEFAULT_ASSIGNMENT_SIZE,
    )
    campaign.add_argument("--slots-per-host", type=int, default=1)
    campaign.add_argument("--max-scenarios", type=int)
    campaign.add_argument("--include-mac", action="store_true")
    campaign.add_argument("--json", action="store_true")

    compile_parser = subparsers.add_parser("compile-recipes")
    compile_parser.add_argument("--campaign-root", required=True, type=Path)
    compile_parser.add_argument("--host-plan", type=Path)
    compile_parser.add_argument("--recipe-dir", type=Path)
    compile_parser.add_argument("--spec-dir", type=Path)
    compile_parser.add_argument("--runs-per-spec", type=int, default=1)
    compile_parser.add_argument("--max-runs", type=int)
    compile_parser.add_argument("--json", action="store_true")

    seed = subparsers.add_parser("seed-recipes")
    seed.add_argument("--campaign-root", required=True, type=Path)
    seed.add_argument("--endpoint", default=harness.DEFAULT_ENDPOINT)
    seed.add_argument("--recipe-dir", type=Path)
    seed.add_argument("--scenario-id", action="append", default=[])
    seed.add_argument("--overwrite", action="store_true")
    seed.add_argument("--json", action="store_true")

    waves = subparsers.add_parser("run-waves")
    waves.add_argument("--spec-dir", required=True, type=Path)
    waves.add_argument("--campaign-root", type=Path)
    waves.add_argument("--ledger", type=Path)
    waves.add_argument("--max-parallel", type=int, default=4)
    waves.add_argument("--max-specs", type=int)
    waves.add_argument(
        "--max-wall-seconds",
        type=float,
        help="Override each scenario wall-clock cap; pass 0 to disable.",
    )
    waves.add_argument("--execute", action="store_true")
    waves.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "assign-hosts":
            payload = assign_hosts(
                campaign_root=args.campaign_root.expanduser(),
                ledger_path=args.ledger.expanduser(),
                slots_per_host=args.slots_per_host,
                max_assignments=args.max_assignments,
            )
            text = (
                f"assigned={payload['assigned_count']} "
                f"blocked={payload['blocked_count']}"
            )
            return _emit(payload, args.json, text, rc=0 if payload["ok"] else 1)
        if args.command == "run-batch":
            payload = run_batch(
                spec_path=args.spec.expanduser(),
                execute=args.execute,
                campaign_root=args.campaign_root.expanduser()
                if args.campaign_root is not None
                else None,
                ledger_path=args.ledger.expanduser()
                if args.ledger is not None
                else None,
                max_wall_seconds=args.max_wall_seconds,
            )
            if payload.get("dry_run"):
                return _emit(
                    payload,
                    args.json,
                    f"dry-run run_count={payload['run_count']}",
                )
            text = f"runs={payload['run_count']} ok={payload['ok']}"
            return _emit(payload, args.json, text, rc=0 if payload["ok"] else 1)
        if args.command == "plan-campaign":
            payload = plan_campaign(
                plan_path=args.plan.expanduser(),
                campaign_root=args.campaign_root.expanduser(),
                endpoint=args.endpoint,
                assignment_size=args.assignment_size,
                slots_per_host=args.slots_per_host,
                max_scenarios=args.max_scenarios,
                include_mac=args.include_mac,
            )
            text = (
                f"assignments={payload['assignment_count']} "
                f"recipe_blockers={payload['recipe_blocker_count']}"
            )
            return _emit(payload, args.json, text)
        if args.command == "compile-recipes":
            payload = compile_recipes(
                campaign_root=args.campaign_root.expanduser(),
                host_plan_path=args.host_plan.expanduser()
                if args.host_plan is not None
                else None,
                recipe_dir=args.recipe_dir.expanduser()
                if args.recipe_dir is not None
                else None,
                spec_dir=args.spec_dir.expanduser()
                if args.spec_dir is not None
                else None,
                runs_per_spec=args.runs_per_spec,
                max_runs=args.max_runs,
            )
            text = (
                f"run_specs={payload['run_spec_count']} "
                f"blocked={payload['blocked_count']}"
            )
            return _emit(payload, args.json, text, rc=0 if payload["ok"] else 1)
        if args.command == "seed-recipes":
            payload = seed_known_recipes(
                campaign_root=args.campaign_root.expanduser(),
                endpoint=args.endpoint,
                recipe_dir=args.recipe_dir.expanduser()
                if args.recipe_dir is not None
                else None,
                scenario_ids=args.scenario_id,
                overwrite=args.overwrite,
            )
            text = (
                f"seeded={payload['seeded_count']} unseeded={payload['unseeded_count']}"
            )
            return _emit(payload, args.json, text)
        if args.command == "run-waves":
            payload = run_waves(
                spec_dir=args.spec_dir.expanduser(),
                execute=args.execute,
                max_parallel=args.max_parallel,
                max_specs=args.max_specs,
                max_wall_seconds=args.max_wall_seconds,
                campaign_root=args.campaign_root.expanduser()
                if args.campaign_root is not None
                else None,
                ledger_path=args.ledger.expanduser()
                if args.ledger is not None
                else None,
            )
            if payload.get("dry_run"):
                return _emit(
                    payload,
                    args.json,
                    f"dry-run specs={payload['spec_count']} runs={payload['run_count']}",
                )
            text = (
                f"specs={payload['spec_count']} runs={payload['run_count']} "
                f"ok={payload['ok']}"
            )
            return _emit(payload, args.json, text, rc=0 if payload["ok"] else 1)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    raise AssertionError(f"unhandled command: {args.command}")


def _load_assignments(
    campaign_root: Path,
    *,
    max_assignments: int | None,
) -> list[Assignment]:
    paths = sorted((campaign_root / "assignments").glob("*.json"))
    if max_assignments is not None:
        if max_assignments < 1:
            raise ValueError("max_assignments must be at least 1")
        paths = paths[:max_assignments]
    assignments: list[Assignment] = []
    for path in paths:
        payload = json_helper.load_path(path)
        if not isinstance(payload, dict):
            raise ValueError(f"assignment root must be a JSON object: {path}")
        assignments.append(
            Assignment(
                assignment_id=str(payload.get("assignment_id") or path.stem),
                endpoint=str(payload.get("endpoint") or ""),
                campaign_root=str(payload.get("campaign_root") or campaign_root),
                host_profile=str(payload.get("host_profile") or ""),
                scenario_ids=tuple(
                    str(value) for value in payload.get("scenario_ids", [])
                ),
                scenarios=tuple(
                    item
                    for item in payload.get("scenarios", [])
                    if isinstance(item, dict)
                ),
                rules=tuple(str(value) for value in payload.get("rules", [])),
            )
        )
    if not assignments:
        raise ValueError(f"no assignment JSON files found under {campaign_root}")
    return assignments


def _load_ledger(path: Path) -> dict[str, object]:
    payload = json_helper.load_path(path)
    if not isinstance(payload, dict):
        raise ValueError(f"ledger root must be a JSON object: {path}")
    return payload


def _load_host_plan(path: Path) -> dict[str, object]:
    payload = json_helper.load_path(path)
    if not isinstance(payload, dict):
        raise ValueError(f"host plan root must be a JSON object: {path}")
    return payload


def _host_slots_by_profile(
    ledger: Mapping[str, object],
    *,
    slots_per_host: int,
) -> dict[str, list[dict[str, object]]]:
    slots: dict[str, list[dict[str, object]]] = {}
    for host in ledger.get("hosts", []):
        if not isinstance(host, dict):
            continue
        if str(host.get("lease_state") or "available") != "available":
            continue
        profile = str(host.get("profile") or "")
        if not profile:
            continue
        slots.setdefault(profile, []).extend([host] * slots_per_host)
    return slots


def _is_mac_scenario(scenario: harness.Scenario) -> bool:
    profile = scenario.host_profile.lower()
    return "mac" in profile or "macos" in scenario.wave.lower()


def _profile_demands(
    assignments: Sequence[Assignment],
    *,
    slots_per_host: int,
) -> list[dict[str, object]]:
    by_profile: dict[str, list[str]] = {}
    for assignment in assignments:
        by_profile.setdefault(assignment.host_profile, []).append(
            assignment.assignment_id
        )
    demands = []
    for profile, assignment_ids in sorted(by_profile.items()):
        demands.append(
            {
                "profile": profile,
                "assignment_count": len(assignment_ids),
                "host_count": math.ceil(len(assignment_ids) / slots_per_host),
                "assignment_ids": assignment_ids,
            }
        )
    return demands


def _write_recipe_stubs(
    campaign_root: Path,
    scenarios: Sequence[harness.Scenario],
    *,
    endpoint: str,
) -> list[Path]:
    recipe_dir = campaign_root / DEFAULT_RECIPE_STUBS_DIR
    recipe_dir.mkdir(parents=True, exist_ok=True)
    base_url = fleet._base_url_for_endpoint(endpoint)  # noqa: SLF001
    paths = []
    for scenario in scenarios:
        path = recipe_dir / f"{scenario.scenario_id}.json"
        json_helper.dump_path(path, _recipe_stub_payload(path, scenario, base_url))
        paths.append(path)
    return paths


def _recipe_stub_payload(
    path: Path,
    scenario: harness.Scenario,
    base_url: str,
) -> dict[str, object]:
    existing = _load_optional_recipe(path)
    payload: dict[str, object] = {
        "scenario_id": scenario.scenario_id,
        "status": "blocked",
        "blocked_reason": "exact key/action recipe is not authored",
        "host_profile": scenario.host_profile,
        "wave": scenario.wave,
        "flow": scenario.flow,
        "assertions": scenario.assertions,
        "launch_command_hint": _launch_command_hint(scenario, base_url),
        "actions": [],
        "expected_text": [],
        "post_checks": [],
        "next_step": (
            "Author exact actions/expected_text/post_checks before "
            "including this scenario in an executable run spec."
        ),
    }
    if existing.get("status") == READY_RECIPE_STATUS:
        for key in (
            "status",
            "command",
            "actions",
            "expected_text",
            "post_checks",
            "stage_files",
            "execution_mode",
            "expected_return_codes",
            "pane",
            "start_delay",
            "step_delay",
            "reset_profile",
            "notes",
        ):
            if key in existing:
                payload[key] = existing[key]
        payload.pop("blocked_reason", None)
        payload["next_step"] = "Ready recipe preserved; compile after host assignment."
    return payload


def _recipe_blockers(
    scenarios: Sequence[harness.Scenario],
    recipe_paths: Sequence[Path],
) -> list[dict[str, object]]:
    blockers = []
    for scenario, path in zip(scenarios, recipe_paths, strict=True):
        recipe = _load_recipe(path)
        if recipe.get("status") == READY_RECIPE_STATUS:
            continue
        blockers.append(
            {
                "scenario_id": scenario.scenario_id,
                "host_profile": scenario.host_profile,
                "reason": str(
                    recipe.get("blocked_reason")
                    or "exact key/action recipe is not authored"
                ),
            }
        )
    return blockers


def _known_recipe_template(
    scenario_id: str,
    base_url: str,
) -> dict[str, object] | None:
    if scenario_id in MANUAL_GITHUB_APP_RECIPE_IDS:
        return None
    interactive_accept = {
        "command": _install_command(base_url),
        "actions": [
            {"step": "000-consent-screen"},
            {"step": "010-accept-default", "keys": ["Enter"]},
        ],
        "expected_text": [
            "Your operating system for software delivery",
            "Yoke's only prerequisite",
            "is installed.",
            "Continue",
        ],
        "post_checks": ["secret_free"],
        "start_delay": 2.0,
        "step_delay": 45.0,
        "notes": "Grounded from public installer consent and onboard handoff behavior.",
    }
    if scenario_id in {"INSTALL-SMOKE-001", "INSTALL-UV-001", "INSTALL-UV-003"}:
        return interactive_accept
    if scenario_id in {"INSTALL-SMOKE-002", "INSTALL-UV-007"}:
        return {
            "command": _install_command(
                base_url,
                args=("--yes",),
                env={"YOKE_INSTALL_YES": "1"},
            ),
            "execution_mode": "ssh-command",
            "actions": [{"step": "000-after-install"}],
            "expected_text": [
                "Setting up Yoke",
                "Yoke v",
                "Run yoke onboard",
            ],
            "post_checks": ["secret_free"],
            "start_delay": 45.0,
            "step_delay": 0.5,
            "notes": "Grounded from --yes noninteractive installer handoff behavior.",
        }
    if scenario_id == "INSTALL-SMOKE-003":
        return {
            "command": "TERM=xterm-256color yoke onboard",
            "actions": [{"step": "000-initial"}],
            "expected_text": ["Set up your machine"],
            "post_checks": ["secret_free"],
            "start_delay": 3.0,
            "step_delay": 0.5,
            "notes": "Grounded from onboard wizard PATH screen text.",
        }
    if scenario_id == "INSTALL-SMOKE-004":
        return {
            "command": _machine_only_onboard_command(
                env_name="stage",
                api_url=base_url.rstrip("/"),
                token_path=REMOTE_STAGE_TOKEN_PATH,
            ),
            "execution_mode": "ssh-command",
            "stage_files": [
                {
                    "source_path": REMOTE_STAGE_TOKEN_PATH,
                    "remote_path": REMOTE_STAGE_TOKEN_PATH,
                }
            ],
            "actions": [{"step": "000-machine-only-stage"}],
            "expected_text": [
                '"applied": true',
                '"final_status": "done"',
                '"active_env": "stage"',
                '"ok": true',
                '"env": "stage"',
            ],
            "post_checks": ["secret_free"],
            "start_delay": 8.0,
            "step_delay": 0.5,
            "notes": (
                "Grounded from noninteractive machine-only stage onboarding "
                "using a staged token file path."
            ),
        }
    if scenario_id == "INSTALL-SMOKE-005":
        return {
            "command": _machine_only_onboard_command(
                env_name="prod",
                api_url=PROD_BASE_URL,
                token_path=REMOTE_PROD_TOKEN_PATH,
            ),
            "execution_mode": "ssh-command",
            "stage_files": [
                {
                    "source_path": _local_prod_token_path(),
                    "remote_path": REMOTE_PROD_TOKEN_PATH,
                }
            ],
            "actions": [{"step": "000-machine-only-prod"}],
            "expected_text": [
                '"applied": true',
                '"final_status": "done"',
                '"active_env": "prod"',
                '"ok": true',
                '"env": "prod"',
            ],
            "post_checks": ["secret_free"],
            "start_delay": 8.0,
            "step_delay": 0.5,
            "notes": (
                "Grounded from noninteractive machine-only prod onboarding "
                "using a staged token file path."
            ),
        }
    if scenario_id == "INSTALL-UV-002":
        return {
            "command": _install_command(base_url, piped_answer="n"),
            "execution_mode": "ssh-command",
            "actions": [{"step": "000-after-decline"}],
            "expected_text": [
                "uv/uvx is required to install Yoke.",
                "Install it yourself with:",
                "Then rerun:",
            ],
            "expected_return_codes": [1],
            "post_checks": ["secret_free"],
            "start_delay": 2.0,
            "step_delay": 0.5,
            "notes": "Grounded from public installer decline screen behavior.",
        }
    if scenario_id == "INSTALL-UV-004":
        return {
            "command": _install_command(
                base_url,
                args=("--yes",),
                env={"YOKE_INSTALL_YES": "1"},
                download=False,
            ),
            "execution_mode": "ssh-command",
            "stage_files": [
                {
                    "source_url": f"{base_url.rstrip('/')}/install",
                    "remote_path": "/tmp/yoke-install",
                }
            ],
            "actions": [{"step": "000-missing-curl"}],
            "expected_text": ["uv/uvx is required and curl is missing"],
            "expected_return_codes": [1],
            "post_checks": ["secret_free"],
            "start_delay": 2.0,
            "step_delay": 0.5,
            "notes": "Grounded by pre-staging /install before exercising the no-curl host.",
        }
    if scenario_id == "INSTALL-UV-005":
        return {
            "command": _install_command(base_url, piped_answer="y"),
            "execution_mode": "ssh-command",
            "actions": [{"step": "000-after-install"}],
            "expected_text": ["Yoke's only prerequisite", "Run yoke onboard"],
            "expected_return_codes": [0],
            "post_checks": [
                "secret_free", "no_text:/dev/tty", "no_text:Starting Yoke onboard",
            ],
            "start_delay": 45.0,
            "step_delay": 0.5,
            "notes": "Grounded from noninteractive public installer handoff behavior.",
        }
    if scenario_id == "INSTALL-UV-006":
        return {
            "command": (
                "cat /tmp/yoke-install | " + _install_env_prefix(base_url) + " sh"
            ),
            "stage_files": [
                {
                    "source_url": f"{base_url.rstrip('/')}/install",
                    "remote_path": "/tmp/yoke-install",
                }
            ],
            "execution_mode": "ssh-command",
            "expected_return_codes": [1],
            "actions": [{"step": "000-no-tty-decline"}],
            "expected_text": [
                "uv/uvx is required to install Yoke.",
                "Install it yourself with:",
                "Then rerun:",
            ],
            "post_checks": ["secret_free", "no_text:Device not configured"],
            "start_delay": 0.0,
            "step_delay": 0.5,
            "notes": "Grounded from piped shell invocation with no TTY available.",
        }
    if scenario_id == "INSTALL-UV-008":
        return {
            "command": _install_command(
                base_url,
                args=("--yes", "--no-onboard"),
                env={"YOKE_INSTALL_YES": "1", "YOKE_NO_ONBOARD": "1"},
            ),
            "execution_mode": "ssh-command",
            "actions": [{"step": "000-after-install"}],
            "expected_text": [
                "Setting up Yoke",
                "Yoke v",
            ],
            "post_checks": [
                "secret_free",
                "no_text:Run yoke onboard",
                "no_text:Starting Yoke onboard",
            ],
            "start_delay": 45.0,
            "step_delay": 0.5,
            "notes": "Grounded from --no-onboard installer behavior.",
        }
    if scenario_id == "INSTALL-UV-009":
        return {
            "command": _install_command(
                base_url,
                args=("--yes", "--no-onboard"),
                env={"YOKE_INSTALL_YES": "1", "YOKE_NO_ONBOARD": "1"},
            ),
            "execution_mode": "ssh-command",
            "actions": [{"step": "000-after-rerun"}],
            "expected_text": [
                "Setting up Yoke",
                "Yoke v",
            ],
            "post_checks": ["secret_free"],
            "start_delay": 45.0,
            "step_delay": 0.5,
            "notes": "Grounded from installer rerun accepting already-installed or reinstall output.",
        }
    if scenario_id == "INSTALL-UV-010":
        return {
            "command": _install_command(
                base_url,
                args=("--yes", "--no-onboard"),
                env={
                    "YOKE_CHANNEL": "yoke-missing-channel",
                    "YOKE_INSTALL_YES": "1",
                    "YOKE_NO_ONBOARD": "1",
                },
            ),
            "execution_mode": "ssh-command",
            "expected_return_codes": [1],
            "actions": [{"step": "000-bad-channel"}],
            "expected_text": [
                "Install failed",
                "Couldn't find a Yoke release to install",
                "yoke-missing-channel",
                "Try again:",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 0.0,
            "step_delay": 0.5,
            "notes": "Grounded from public installer bad-channel recovery behavior.",
        }
    if scenario_id == "INSTALL-UV-011":
        return {
            "command": (
                f"curl -fsSL {shlex.quote(base_url.rstrip('/') + '/dist/install.py')} "
                "-o /tmp/yoke-install.py && "
                'YOKE_NO_ONBOARD=1 "$HOME/.local/bin/uv" run --no-project '
                "python /tmp/yoke-install.py --base-url http://127.0.0.1:9 "
                "--version 0.0.0 --yes"
            ),
            "execution_mode": "ssh-command",
            "expected_return_codes": [1],
            "actions": [{"step": "000-index-unreachable"}],
            "expected_text": [
                "Setting up Yoke",
                "Install failed",
                "Couldn't install Yoke",
                "127.0.0.1:9",
                "Try again:",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 0.0,
            "step_delay": 0.5,
            "notes": "Grounded from install.py dead private-index recovery behavior.",
        }
    if scenario_id == "INSTALL-UV-012":
        return {
            "command": _install_command(
                base_url,
                args=("--yes", "--no-onboard"),
                env={
                    "TERM": "screen",
                    "YOKE_INSTALL_FORCE_COLOR": "0",
                    "YOKE_INSTALL_FORCE_PLAIN": "1",
                    "YOKE_INSTALL_YES": "1",
                    "YOKE_NO_ONBOARD": "1",
                },
            ),
            "execution_mode": "ssh-command",
            "actions": [{"step": "000-screen-terminal"}],
            "expected_text": [
                "* Setting up Yoke",
                "* Yoke v",
            ],
            "post_checks": [
                "secret_free",
                "no_text:☀",
                "no_text:Traceback",
            ],
            "start_delay": 45.0,
            "step_delay": 0.5,
            "notes": "Grounded from installer plain-glyph screen-terminal behavior.",
        }
    if scenario_id == "PATH-001":
        return {
            "command": _onboard_command(post_install=True),
            "actions": [
                {"step": "000-install-summary"},
                {"step": "010-path-diagnosis", "keys": ["Enter"]},
                {"step": "020-path-verified", "keys": ["Enter"]},
            ],
            "expected_text": _path_fix_expected_text(),
            "post_checks": ["secret_free"],
            "start_delay": 3.0,
            "step_delay": 3.0,
            "notes": "Grounded from default PATH repair and verified-screen copy.",
        }
    if scenario_id == "PATH-002":
        return {
            "command": _onboard_command(post_install=True),
            "actions": [
                {"step": "000-install-summary"},
                {"step": "010-path-diagnosis", "keys": ["Enter"]},
                {"step": "020-path-preview", "keys": ["Down", "Enter"]},
                {"step": "030-path-verified", "keys": ["Enter"]},
            ],
            "expected_text": [
                "Add Yoke to your PATH.",
                "BEGIN YOKE MANAGED PATH",
                "END YOKE MANAGED PATH",
                "Wrote the managed block",
                "Checked a fresh login shell:",
                "Your next terminal will find Yoke.",
            ],
            "post_checks": ["secret_free"],
            "start_delay": 3.0,
            "step_delay": 3.0,
            "notes": "Grounded from preview-then-apply PATH repair behavior.",
        }
    if scenario_id == "PATH-003":
        return {
            "command": _onboard_command(post_install=True),
            "actions": [
                {"step": "000-install-summary"},
                {"step": "010-path-diagnosis", "keys": ["Enter"]},
                {
                    "step": "020-destination-after-skip",
                    "keys": ["Down", "Down", "Enter"],
                },
            ],
            "expected_text": [
                "Add Yoke to your PATH.",
                "Where should this Yoke live?",
                "This machine",
                "upyoke.com",
            ],
            "post_checks": ["secret_free"],
            "start_delay": 3.0,
            "step_delay": 2.0,
            "notes": "Grounded from PATH skip advancing to the Account step.",
        }
    if scenario_id == "PATH-004":
        return {
            "command": _onboard_command(),
            "actions": [
                {"step": "000-path-all-clear"},
                {"step": "010-after-first-continue", "keys": ["Enter"]},
                {"step": "020-after-second-continue", "keys": ["Enter"]},
            ],
            "expected_text": [
                "Continue",
                "Connect to Yoke.",
            ],
            "post_checks": ["secret_free"],
            "start_delay": 3.0,
            "step_delay": 2.0,
            "notes": "Grounded from all-clear PATH diagnosis behavior.",
        }
    if scenario_id == "PATH-005":
        return {
            "command": _onboard_command(post_install=True),
            "actions": [
                {"step": "000-install-summary"},
                {"step": "010-path-diagnosis", "keys": ["Enter"]},
                {"step": "020-path-verified", "keys": ["Enter"]},
            ],
            "expected_text": [
                *_path_fix_expected_text(),
                "An SSH command sees:",
                "Checked an SSH command:",
            ],
            "post_checks": ["secret_free"],
            "start_delay": 3.0,
            "step_delay": 3.0,
            "notes": "Grounded from SSH startup-file PATH repair verification.",
        }
    if scenario_id == "PATH-006":
        return {
            "command": (
                '"$HOME/.local/bin/yoke" path fix --yes '
                ">/tmp/yoke-path-rerun-first.out 2>&1 && "
                '"$HOME/.local/bin/yoke" path fix --yes '
                ">/tmp/yoke-path-rerun-second.out 2>&1 && "
                'printf "\\nPATH-006 retained path fix evidence\\n" && '
                'printf "first path fix output: " && '
                "grep -m1 '^Applied\\.$' /tmp/yoke-path-rerun-first.out && "
                'printf "second path fix output: " && '
                "grep -m1 '^Applied\\.$' /tmp/yoke-path-rerun-second.out && "
                'printf "managed block counts:\\n" && '
                "grep -H -c 'BEGIN YOKE MANAGED PATH' "
                '"$HOME/.bash_profile" "$HOME/.bashrc" && '
                'printf "\\nPress Enter to continue to onboard\\n" && '
                "read _ && "
                + _onboard_command()
            ),
            "actions": [
                {"step": "000-path-fix-evidence"},
                {"step": "010-path-all-clear", "keys": ["Enter"]},
                {"step": "020-destination-after-continue", "keys": ["Enter"]},
                {"step": "030-env-after-hosted-pick", "keys": ["Enter"]},
            ],
            "expected_text": [
                "PATH-006 retained path fix evidence",
                "first path fix output:",
                "second path fix output:",
                "managed block counts:",
                ".bash_profile:1",
                ".bashrc:1",
                "Press Enter to continue to onboard",
                "Connect to Yoke.",
                "Production",
                "Stage",
            ],
            "post_checks": ["secret_free"],
            "start_delay": 3.0,
            "step_delay": 2.0,
            "notes": "Grounded from idempotent path fix before onboarding rerun.",
        }
    if scenario_id == "PATH-007":
        return {
            "command": _onboard_command(
                post_install=True,
                env={
                    "TERM": "screen-256color",
                    "YOKE_ONBOARD_FORCE_PLAIN": "1",
                },
            ),
            "actions": [
                {"step": "000-install-summary"},
                {"step": "010-path-diagnosis", "keys": ["Enter"]},
            ],
            "expected_text": [
                "* Yoke",
                "up/down navigate",
                "Add Yoke to your PATH.",
                "An SSH command sees:",
                "not on PATH",
            ],
            "post_checks": _plain_glyph_post_checks(),
            "start_delay": 3.0,
            "step_delay": 2.0,
            "notes": "Grounded from screen-terminal PATH diagnosis behavior.",
        }
    if scenario_id == "PATH-008":
        return {
            "command": _onboard_command(post_install=True),
            "actions": [
                {"step": "000-install-summary"},
                {"step": "010-after-quit", "keys": ["Down", "Enter"], "capture": False},
            ],
            "expected_text": [
                "is installed.",
                "Quit",
            ],
            "post_checks": ["secret_free", "tmux_exit_code:130"],
            "start_delay": 3.0,
            "step_delay": 2.0,
            "notes": "Grounded from post-install summary quit behavior.",
        }
    if scenario_id == "AUTH-001":
        return {
            "command": _path_ready_onboard_command(),
            "stage_files": [
                {
                    "source_path": REMOTE_STAGE_TOKEN_PATH,
                    "remote_path": REMOTE_STAGE_TOKEN_PATH,
                }
            ],
            "actions": _auth_token_file_actions(
                env_keys=("Down", "Enter"),
                token_path=REMOTE_STAGE_TOKEN_PATH,
            ),
            "expected_text": _auth_success_expected_text(
                env_label="Stage",
                token_prompt="~/.yoke/secrets/stage.token",
            ),
            "post_checks": ["secret_free"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": "Grounded from interactive Stage token-file verification.",
        }
    if scenario_id == "AUTH-002":
        return {
            "command": _path_ready_onboard_command(),
            "stage_files": [
                {
                    "source_path": _local_prod_token_path(),
                    "remote_path": REMOTE_PROD_TOKEN_PATH,
                }
            ],
            "actions": _auth_token_file_actions(
                env_keys=("Enter",),
                token_path=REMOTE_PROD_TOKEN_PATH,
            ),
            "expected_text": _auth_success_expected_text(
                env_label="Production",
                token_prompt="~/.yoke/secrets/prod.token",
            ),
            "post_checks": ["secret_free"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": "Grounded from interactive Production token-file verification.",
        }
    if scenario_id == "AUTH-003":
        port = AUTH_FAKE_CUSTOM_API_PORT
        api_url = f"http://127.0.0.1:{port}"
        return {
            "command": _fake_yoke_api_onboard_command(
                port=port,
                payload=_fake_success_identity_payload(),
            ),
            "actions": _auth_custom_token_file_actions(
                api_url=api_url,
                token_path=REMOTE_FAKE_YOKE_TOKEN_PATH,
            ),
            "expected_text": [
                "A team server",
                "Enter your Yoke server URL.",
                "Yoke token connected.",
                "Success! You've authenticated with Yoke.",
                "Actor: recipe actor",
                "Projects: recipe-project (admin)",
            ],
            "post_checks": ["secret_free"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": "Grounded from custom API URL token-file verification.",
        }
    if scenario_id == "AUTH-004":
        return {
            "command": _path_ready_onboard_command(),
            "stage_files": [
                {
                    "source_path": REMOTE_STAGE_TOKEN_PATH,
                    "remote_path": REMOTE_STAGE_TOKEN_PATH,
                }
            ],
            "actions": _auth_token_paste_actions(
                env_keys=("Down", "Enter"),
                token_path=REMOTE_STAGE_TOKEN_PATH,
            ),
            "expected_text": [
                "Stage",
                "Paste your Yoke API token.",
                "Never shown on screen.",
                "Yoke token connected.",
                "Success! You've authenticated with Yoke.",
            ],
            "post_checks": ["secret_free"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": (
                "Grounded from interactive password-field paste using a "
                "file-backed tmux paste action."
            ),
        }
    if scenario_id == "AUTH-005":
        return {
            "command": _prepare_missing_token_onboard_command(
                REMOTE_MISSING_TOKEN_PATH,
            ),
            "actions": _auth_token_file_actions(
                env_keys=("Down", "Enter"),
                token_path=REMOTE_MISSING_TOKEN_PATH,
            ),
            "expected_text": [
                "Yoke token could not be verified.",
                "token file is missing",
                "Try again",
                "Back",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": "Grounded from missing token-file retry behavior.",
        }
    if scenario_id == "AUTH-006":
        return {
            "command": _prepare_empty_token_onboard_command(REMOTE_EMPTY_TOKEN_PATH),
            "actions": _auth_token_file_actions(
                env_keys=("Down", "Enter"),
                token_path=REMOTE_EMPTY_TOKEN_PATH,
            ),
            "expected_text": [
                "Yoke token could not be verified.",
                "token file is empty",
                "Try again",
                "Back",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": "Grounded from empty token-file retry behavior.",
        }
    if scenario_id == "AUTH-007":
        return {
            "command": _prepare_invalid_token_onboard_command(
                REMOTE_INVALID_TOKEN_PATH,
            ),
            "actions": _auth_token_file_actions(
                env_keys=("Down", "Enter"),
                token_path=REMOTE_INVALID_TOKEN_PATH,
            ),
            "expected_text": [
                "Yoke token could not be verified.",
                "Yoke token check failed",
                "HTTP 401",
                "Try again",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": "Grounded from invalid stage token retry behavior.",
        }
    if scenario_id == "AUTH-008":
        port = AUTH_FAKE_NO_ACCESS_API_PORT
        api_url = f"http://127.0.0.1:{port}"
        return {
            "command": (
                _clear_yoke_auth_state_command()
                + _fake_yoke_api_onboard_command(
                    port=port,
                    payload=_fake_no_access_identity_payload(),
                )
            ),
            "actions": _auth_custom_token_file_actions(
                api_url=api_url,
                token_path=REMOTE_FAKE_YOKE_TOKEN_PATH,
            ),
            "expected_text": [
                "Yoke token could not be verified.",
                "Yoke token is valid, but it does not include access",
                "Ask a Yoke admin",
                "Try again",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": (
                "Grounded from a localhost identity response with no org or "
                "project grants."
            ),
        }
    if scenario_id == "AUTH-009":
        return {
            "command": _restore_stored_yoke_token_onboard_command(),
            "stage_files": _stage_stage_yoke_token_files(),
            "actions": _auth_stored_token_actions(),
            "expected_text": [
                "Using existing environment:",
                "Using existing Yoke token file from machine config.",
                "Yoke token connected.",
                "Success! You've authenticated with Yoke.",
            ],
            "post_checks": ["secret_free"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": "Grounded from prepared stored-state token reuse.",
        }
    if scenario_id == "AUTH-010":
        return {
            "command": _prepare_invalid_stored_yoke_token_onboard_command(),
            "actions": _auth_stored_token_actions(),
            "expected_text": [
                "Yoke token could not be verified.",
                "Yoke token check failed",
                "HTTP 401",
                "Try again",
                "Back",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": "Grounded from invalid prepared stored-state token replacement route.",
        }
    if scenario_id == "AUTH-011":
        port = AUTH_FAKE_MANY_ACCESS_API_PORT
        api_url = f"http://127.0.0.1:{port}"
        return {
            "command": _fake_yoke_api_onboard_command(
                port=port,
                payload=_fake_many_access_identity_payload(),
            ),
            "actions": _auth_custom_token_file_actions(
                api_url=api_url,
                token_path=REMOTE_FAKE_YOKE_TOKEN_PATH,
            ),
            "expected_text": [
                "Yoke token connected.",
                "Organizations:",
                "o1 (owner)",
                "Projects:",
                "p1 (admin)",
                "and 2 more",
            ],
            "post_checks": ["secret_free", "no_text:including"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": (
                "Grounded from a localhost identity response with more than "
                "four orgs and projects."
            ),
        }
    if scenario_id == "GITHUB-001":
        return {
            "command": _path_ready_onboard_command(),
            "stage_files": _stage_stage_yoke_token_files(),
            "actions": _github_skip_actions(),
            "expected_text": [
                "Connect GitHub?",
                "Use backlog only",
                "Set up a project.",
                "Where's the code?",
            ],
            "post_checks": ["secret_free"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": "Grounded from choosing backlog-only at the machine App step.",
        }
    if scenario_id == "PROJECT-SOURCE-001":
        return {
            "command": _project_source_onboard_command(),
            "stage_files": _stage_stage_yoke_token_files(),
            "actions": _project_source_machine_only_actions(),
            "expected_text": [
                "Set up a project.",
                "Don't set up a project now",
                "On this machine (~/.yoke)",
                "Make \"stage\" your active environment",
                "Skip connecting GitHub for now",
            ],
            "post_checks": ["secret_free"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": "Grounded from the project machine-only path into Review.",
        }
    if scenario_id == "PROJECT-SOURCE-002":
        return {
            "command": _project_source_onboard_command(),
            "stage_files": _stage_stage_yoke_token_files(),
            "actions": _project_source_create_folder_actions(PROJECT_SOURCE_NEW_PATH),
            "expected_text": [
                "Create a new project",
                "Name your new project folder.",
                "yoke-project-source-new",
                "Name your project.",
                "Short ID",
            ],
            "post_checks": ["secret_free"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": "Grounded from create-new folder input into project metadata.",
        }
    if scenario_id == "PROJECT-SOURCE-003":
        return {
            "command": _project_source_onboard_command(
                existing_checkout=True,
            ),
            "stage_files": _stage_stage_yoke_token_files(),
            "actions": _project_source_existing_folder_actions(
                PROJECT_SOURCE_EXISTING_PATH,
            ),
            "expected_text": [
                "Existing folder on my machine",
                "Point at your project folder.",
                "yoke-project-source-existing",
                "Name your project.",
                "Short ID",
            ],
            "post_checks": ["secret_free"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": "Grounded from existing local checkout into project metadata.",
        }
    if scenario_id == "PROJECT-SOURCE-004":
        return {
            "command": _project_source_onboard_command(
                existing_checkout=True,
            ),
            "stage_files": _stage_stage_yoke_token_files(),
            "actions": _project_source_create_existing_redirect_actions(
                PROJECT_SOURCE_EXISTING_PATH,
            ),
            "expected_text": [
                "Name your new project folder.",
                "That folder already exists.",
                PROJECT_SOURCE_EXISTING_PATH,
                "instead of creating a new one",
            ],
            "post_checks": ["secret_free"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": "Grounded from create-new redirecting to existing-project setup.",
        }
    if scenario_id == "PROJECT-SOURCE-005":
        return {
            "command": _project_source_onboard_command(
                remote_branches={"main-source": "main"},
            ),
            "stage_files": _stage_stage_yoke_token_files(),
            "actions": _project_source_clone_actions(
                remote_url=PROJECT_SOURCE_MAIN_REMOTE_URL,
                clone_path=PROJECT_SOURCE_CLONE_MAIN_PATH,
            ),
            "expected_text": [
                "Clone a project from GitHub.",
                "Where should Yoke clone it?",
                "How do you want to copy recipe/main-source?",
                "Clone it",
            ],
            "post_checks": ["secret_free"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": (
                "Grounded from a local bare file:// source with GitHub-shaped "
                "owner/repo path and default branch main."
            ),
        }
    if scenario_id == "PROJECT-SOURCE-007":
        return {
            "command": _project_source_onboard_command(),
            "stage_files": _stage_stage_yoke_token_files(),
            "actions": _project_source_clone_url_error_actions(
                PROJECT_SOURCE_MISSING_REMOTE_URL,
            ),
            "expected_text": [
                "Clone a project from GitHub.",
                "Couldn't reach that repo.",
                "Yoke couldn't reach that repo - check the URL",
                "Change URL",
                "Try again",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": "Grounded from unreachable clone URL recovery copy.",
        }
    if scenario_id == "PROJECT-SOURCE-008":
        return {
            "command": _project_source_onboard_command(
                remote_branches={"master-source": "master"},
            ),
            "stage_files": _stage_stage_yoke_token_files(),
            "actions": _project_source_clone_actions(
                remote_url=PROJECT_SOURCE_MASTER_REMOTE_URL,
                clone_path=PROJECT_SOURCE_CLONE_MASTER_PATH,
            ),
            "expected_text": [
                "Clone a project from GitHub.",
                "How do you want to copy recipe/master-source?",
                "Clone it",
            ],
            "post_checks": ["secret_free"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": (
                "Grounded from a local bare source whose HEAD symref is master; "
                "later metadata/review recipes assert the carried branch."
            ),
        }
    if scenario_id == "PROJECT-SOURCE-009":
        return {
            "command": _project_source_onboard_command(
                remote_branches={"main-source": "main"},
                conflict_checkout=True,
            ),
            "stage_files": _stage_stage_yoke_token_files(),
            "actions": _project_source_clone_conflict_actions(
                remote_url=PROJECT_SOURCE_MAIN_REMOTE_URL,
                clone_path=PROJECT_SOURCE_CONFLICT_PATH,
            ),
            "expected_text": [
                "Where should Yoke clone it?",
                PROJECT_SOURCE_CONFLICT_PATH,
                "That folder already has files",
                "pick an empty or new path",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": "Grounded from non-empty clone destination inline validation.",
        }
    if scenario_id == "PROJECT-SOURCE-010":
        return {
            "command": _project_source_onboard_command(),
            "stage_files": _stage_stage_yoke_token_files(),
            "actions": _project_source_git_required_actions(),
            "expected_text": [
                "Git is required for project setup.",
                "Git is needed to create, clone, import, or inspect a project checkout.",
                "Try again",
                "Back",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": "Grounded from selecting a project mode on a no-git host.",
        }
    if scenario_id == "PROJECT-SOURCE-011":
        return {
            "command": _project_source_onboard_command(),
            "stage_files": _stage_stage_yoke_token_files(),
            "actions": _project_source_git_install_actions(),
            "expected_text": [
                "Git is required for project setup.",
                "Install Git",
                "Point at your project folder.",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 3.0,
            "step_delay": 30.0,
            "notes": "Grounded from automatic Git install returning to project flow.",
        }
    if scenario_id == "PROJECT-SOURCE-012":
        return {
            "command": _project_source_onboard_command(),
            "stage_files": _stage_stage_yoke_token_files(),
            "actions": _project_source_git_required_actions(),
            "expected_text": [
                "Git is required for project setup.",
                "Run this manually, then choose Try again",
                "Try again",
                "Back",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": "Grounded from manual-only no-sudo Git guidance.",
        }
    if scenario_id == "PROJECT-SOURCE-013":
        return {
            "command": _project_source_dev_onboard_command(
                yoke_port=PROJECT_SOURCE_DEV_NO_ACCESS_API_PORT,
                yoke_payload=_fake_source_dev_yoke_payload(access=False),
            ),
            "actions": _project_source_dev_mode_actions(),
            "expected_text": [
                "Develop Yoke itself",
                "This Yoke token can't reach the Yoke project",
                "you need access to develop",
                "Press esc to go back",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": "Grounded from source-dev Yoke-project access denial.",
        }
    if scenario_id == "PROJECT-SOURCE-014":
        return {
            "command": _project_source_dev_onboard_command(
                yoke_port=PROJECT_SOURCE_DEV_YOKE_API_PORT,
            ),
            "actions": _project_source_dev_checkout_actions(
                PROJECT_SOURCE_DEV_FRESH_PATH,
            ),
            "expected_text": [
                PROJECT_SOURCE_DEV_FRESH_PATH,
                "In the Yoke core database",
                "Register the Yoke project in the Yoke core database",
                'Use Yoke\'s GitHub "origin" remote from the clone',
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": "Grounded from the allowed source-dev/admin review plan.",
        }
    if scenario_id == "PROJECT-SOURCE-015":
        return {
            "command": _project_source_dev_post_apply_command(
                yoke_port=PROJECT_SOURCE_DEV_FRESH_YOKE_API_PORT,
            ),
            "execution_mode": "ssh-command",
            "actions": [{"step": "000-source-dev-post-apply"}],
            "expected_text": [
                PROJECT_SOURCE_DEV_CHECKOUT_OK,
                PROJECT_SOURCE_DEV_GIT_OK,
                PROJECT_SOURCE_DEV_LINKS_OK,
                PROJECT_SOURCE_DEV_MANIFEST_OK,
                PROJECT_SOURCE_DEV_HOOKS_OK,
                PROJECT_SOURCE_DEV_POST_APPLY_OK,
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 0.0,
            "step_delay": 0.5,
            "notes": (
                "Grounded from noninteractive source-dev/admin apply plus "
                "post-apply clone/source-link filesystem proof."
            ),
        }
    if scenario_id == "PROJECT-SOURCE-016":
        return {
            "command": _project_source_dev_onboard_command(
                yoke_port=PROJECT_SOURCE_DEV_EXISTING_YOKE_API_PORT,
                existing_dev_checkout=True,
            ),
            "actions": _project_source_dev_checkout_actions(
                PROJECT_SOURCE_DEV_EXISTING_PATH,
            ),
            "expected_text": [
                "Where is your Yoke checkout?",
                PROJECT_SOURCE_DEV_EXISTING_PATH,
                "Register the Yoke project in the Yoke core database",
                "Set up the Yoke source checkout at",
                'Use Yoke\'s GitHub "origin" remote from the clone',
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": "Grounded from pointing source-dev at an existing Yoke checkout.",
        }
    if scenario_id == "PROJECT-SOURCE-017":
        return {
            "command": _project_source_dev_onboard_command(
                yoke_port=PROJECT_SOURCE_DEV_CONFLICT_YOKE_API_PORT,
                conflict_dev_checkout=True,
            ),
            "actions": _project_source_dev_checkout_actions(
                PROJECT_SOURCE_DEV_CONFLICT_PATH,
            ),
            "expected_text": [
                "Where is your Yoke checkout?",
                PROJECT_SOURCE_DEV_CONFLICT_PATH,
                "already has files",
                "source checkout",
                "existing Yoke clone",
                "Press esc to go back",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": "Grounded from pre-Apply non-Yoke folder refusal.",
        }
    if scenario_id == "PROJECT-SOURCE-018":
        return {
            "command": _project_source_dev_onboard_command(
                yoke_port=PROJECT_SOURCE_DEV_DEFAULT_YOKE_API_PORT,
            ),
            "actions": _project_source_dev_checkout_actions(
                PROJECT_SOURCE_DEV_DEFAULT_PATH,
            ),
            "expected_text": [
                "Where is your Yoke checkout?",
                "~/code/yoke",
                PROJECT_SOURCE_DEV_DEFAULT_PATH,
                "Register the Yoke project in the Yoke core database",
                'Use Yoke\'s GitHub "origin" remote from the clone',
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": "Grounded from source-dev default checkout placeholder and review wording.",
        }
    if scenario_id == "PROJECT-SOURCE-019":
        return {
            "command": _project_source_dev_onboard_command(
                yoke_port=PROJECT_SOURCE_DEV_PUSH_YOKE_API_PORT,
            ),
            "actions": _project_source_dev_checkout_actions(
                PROJECT_SOURCE_DEV_PUSH_PATH,
            ),
            "expected_text": [
                PROJECT_SOURCE_DEV_PUSH_PATH,
                "Set up the Yoke source checkout",
                'Use Yoke\'s GitHub "origin" remote from the clone',
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": (
                "Live TUI recipe covers source-dev push review; "
                "post-apply helper behavior is covered by source-dev apply tests."
            ),
        }
    if scenario_id == "PROJECT-META-001":
        return {
            "command": _project_meta_onboard_command(),
            "stage_files": _stage_stage_yoke_token_files(),
            "actions": _project_meta_review_actions(PROJECT_META_CHECKOUT_PATH),
            "expected_text": [
                "Name your project.",
                "Give it a friendly name.",
                "Pick the default branch.",
                "Pick the issue ID prefix.",
                "Review what Yoke will save.",
                "Register this checkout in ~/.yoke/config.json",
                "In the Yoke core database",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": "Grounded from valid local project metadata through Review.",
        }
    if scenario_id == "PROJECT-META-002":
        return {
            "command": _project_meta_onboard_command(),
            "stage_files": _stage_stage_yoke_token_files(),
            "actions": [
                *_project_meta_existing_folder_actions(PROJECT_META_CHECKOUT_PATH),
                {"step": "090-empty-slug-error", "keys": ["C-u", "Enter"]},
            ],
            "expected_text": [
                "Name your project.",
                "A value is required.",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": "Grounded from clearing the prefilled slug and submitting blank.",
        }
    if scenario_id == "PROJECT-META-003":
        return {
            "command": _project_meta_onboard_command(),
            "stage_files": _stage_stage_yoke_token_files(),
            "actions": [
                *_project_meta_existing_folder_actions(PROJECT_META_CHECKOUT_PATH),
                {
                    "step": "090-clear-slug",
                    "keys": ["C-u"],
                    "capture": False,
                },
                {
                    "step": "100-invalid-slug-error",
                    "keys": ["Bad Slug", "Enter"],
                },
            ],
            "expected_text": [
                "Name your project.",
                "Use lowercase letters, digits, and hyphens",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": "Grounded from project slug inline format validation.",
        }
    if scenario_id == "PROJECT-META-004":
        return {
            "command": _project_meta_onboard_command(),
            "stage_files": _stage_stage_yoke_token_files(),
            "actions": [
                *_project_meta_existing_folder_actions(PROJECT_META_CHECKOUT_PATH),
                {
                    "step": "090-clear-slug",
                    "keys": ["C-u"],
                    "capture": False,
                },
                {
                    "step": "100-long-slug-error",
                    "keys": [PROJECT_META_LONG_TEXT_INPUT, "Enter"],
                },
            ],
            "expected_text": [
                "Name your project.",
                "Use 63 characters or fewer.",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": "Grounded from project slug length validation.",
        }
    if scenario_id == "PROJECT-META-005":
        return {
            "command": _project_meta_onboard_command(),
            "stage_files": _stage_stage_yoke_token_files(),
            "actions": [
                *_project_meta_existing_folder_actions(PROJECT_META_CHECKOUT_PATH),
                {"step": "090-project-name-input", "keys": ["Enter"]},
                {"step": "100-empty-name-error", "keys": ["C-u", "Enter"]},
            ],
            "expected_text": [
                "Give it a friendly name.",
                "A value is required.",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": (
                "Grounded from clearing the prefilled display name and submitting "
                "blank."
            ),
        }
    if scenario_id == "PROJECT-META-006":
        return {
            "command": _project_meta_onboard_command(),
            "stage_files": _stage_stage_yoke_token_files(),
            "actions": [
                *_project_meta_metadata_prefix_actions(PROJECT_META_CHECKOUT_PATH),
                {
                    "step": "120-invalid-branch-error",
                    "keys": ["bad branch", "Enter"],
                },
            ],
            "expected_text": [
                "Pick the default branch.",
                "A branch name can't contain spaces.",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": "Grounded from default-branch inline validation.",
        }
    if scenario_id == "PROJECT-META-007":
        return {
            "command": _project_meta_onboard_command(),
            "stage_files": _stage_stage_yoke_token_files(),
            "actions": [
                *_project_meta_metadata_prefix_actions(PROJECT_META_CHECKOUT_PATH),
                {"step": "130-prefix-input-ready", "keys": ["Enter"]},
                {
                    "step": "140-invalid-prefix-error",
                    "keys": ["toolong", "Enter"],
                },
            ],
            "expected_text": [
                "Pick the issue ID prefix.",
                "Use 2-6 letters or digits starting with a letter",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": "Grounded from public item-prefix inline validation.",
        }
    if scenario_id == "PROJECT-META-009":
        return {
            "command": _project_meta_board_data_failure_onboard_command(),
            "actions": _project_meta_apply_failure_actions(
                PROJECT_META_BOARD_DATA_FAIL_PATH,
            ),
            "expected_text": [
                "Couldn't finish setup.",
                "board.data.get failed",
                "Failed step: 06-project-write-board-art",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": (
                "Grounded from the interactive metadata Apply flow reaching "
                "the board-art write against a deliberate fake board.data.get "
                "failure; "
                "projects.create permission denial is covered by APPLY-006."
            ),
        }
    if scenario_id == "PROJECT-META-010":
        return {
            "command": _project_meta_onboard_command(),
            "stage_files": _stage_stage_yoke_token_files(),
            "actions": _project_meta_create_folder_actions(
                PROJECT_META_TILDE_IMMEDIATE_PATH,
            ),
            "expected_text": [
                "Name your new project folder.",
                "yoke-project-meta-immediate",
                "Name your project.",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": "Grounded from immediate leading-tilde typing on input mount.",
        }
    if scenario_id == "PROJECT-META-011":
        return {
            "command": _project_meta_onboard_command(),
            "stage_files": _stage_stage_yoke_token_files(),
            "actions": _project_meta_create_folder_actions(
                PROJECT_META_TILDE_SETTLED_PATH,
                settled=True,
            ),
            "expected_text": [
                "Name your new project folder.",
                "yoke-project-meta-settled",
                "Name your project.",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": "Grounded from settled leading-tilde typing on input mount.",
        }
    if scenario_id == "PUBLISH-001":
        return {
            "command": _project_publish_stage_onboard_command(
                PROJECT_PUBLISH_LOCAL_PATH,
            ),
            "stage_files": _stage_stage_yoke_token_files(),
            "actions": _project_publish_no_publish_actions(
                PROJECT_PUBLISH_LOCAL_PATH,
            ),
            "expected_text": [
                "Also publish to GitHub?",
                "No \u2014 keep it local",
                "Review what Yoke will save.",
                "Nothing is written until you choose Apply.",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": "Grounded from create-project Review with GitHub publish declined.",
        }
    if scenario_id == "APPLY-001":
        return {
            "command": _machine_only_onboard_command(
                env_name="stage",
                api_url=base_url.rstrip("/"),
                token_path=REMOTE_STAGE_TOKEN_PATH,
            ),
            "execution_mode": "ssh-command",
            "stage_files": _stage_stage_yoke_token_files(),
            "actions": [{"step": "000-machine-only-apply"}],
            "expected_text": [
                '"project_mode": "machine-only"',
                '"applied": true',
                '"final_status": "done"',
                '"active_env": "stage"',
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 8.0,
            "step_delay": 0.5,
            "notes": "Grounded from noninteractive machine-only Apply success.",
        }
    if scenario_id == "APPLY-002":
        return {
            "command": _project_publish_stage_onboard_command(APPLY_CREATE_PATH),
            "stage_files": _stage_stage_yoke_token_files(),
            "actions": _project_publish_no_publish_actions(APPLY_CREATE_PATH),
            "expected_text": [
                "yoke-apply-create",
                "Yoke core database",
                "GitHub",
                "Apply",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": "Grounded from full create-project Review write-plan grouping.",
        }
    if scenario_id == "APPLY-003":
        return {
            "command": _project_apply_clone_review_command(),
            "execution_mode": "ssh-command",
            "actions": [{"step": "000-clone-review-report"}],
            "expected_text": [
                '"applied": false',
                '"project_mode": "clone-remote"',
                '"project-clone-remote"',
                '"project-install-scaffold"',
                '"project-write-board-art"',
                PROJECT_SOURCE_MAIN_REMOTE_URL,
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 1.0,
            "step_delay": 0.5,
            "notes": "Grounded from noninteractive clone-mode Review plan.",
        }
    if scenario_id == "APPLY-004":
        return {
            "command": _project_apply_machine_config_failure_command(),
            "execution_mode": "ssh-command",
            "expected_return_codes": [1],
            "actions": [{"step": "000-machine-config-failure"}],
            "expected_text": [
                "error:",
                "failed step:",
                "report:",
                "resume:",
                "03-store-token-reference",
                "File exists: '/dev/null'",
            ],
            "post_checks": [
                "secret_free",
                "no_text:Traceback",
                f"no_text:{AUTH_FAKE_TOKEN_VALUE}",
            ],
            "start_delay": 0.0,
            "step_delay": 0.5,
            "notes": "Grounded from noninteractive Apply failing while storing token reference under an unusable config path.",
        }
    if scenario_id == "APPLY-006":
        return {
            "command": _project_apply_project_create_failure_command(),
            "execution_mode": "ssh-command",
            "expected_return_codes": [1],
            "actions": [{"step": "000-project-create-failure"}],
            "expected_text": [
                "Your API token lacks project.create rights.",
                "failed step:",
                "report:",
                "resume:",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 0.0,
            "step_delay": 0.5,
            "notes": "Grounded from projects.create permission denial during Apply after missing-project lookup.",
        }
    if scenario_id == "APPLY-007":
        return {
            "command": _project_apply_clone_conflict_failure_command(),
            "execution_mode": "ssh-command",
            "expected_return_codes": [1],
            "actions": [{"step": "000-clone-conflict-failure"}],
            "expected_text": [
                APPLY_CLONE_CONFLICT_PATH,
                "already has files but isn't a clone of this repo",
                "pick an empty folder to resume cleanly",
                "failed step:",
                "report:",
                "resume:",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 0.0,
            "step_delay": 0.5,
            "notes": "Grounded from clone Apply target-folder recovery guidance.",
        }
    if scenario_id == "APPLY-009":
        api_url = f"http://127.0.0.1:{APPLY_BOARD_FAIL_YOKE_API_PORT}"
        return {
            "command": _project_apply_interactive_fake_yoke_command(
                path=APPLY_BOARD_FAIL_PATH,
                port=APPLY_BOARD_FAIL_YOKE_API_PORT,
                payload=_fake_apply_yoke_payload(board_art_conflict=True),
                log_name="board-fail",
                base_url=base_url,
            ),
            "actions": _project_apply_interactive_local_actions(
                APPLY_BOARD_FAIL_PATH,
                api_url=api_url,
            ),
            "expected_text": [
                "couldn't write your board art",
                "Failed step:",
                "project-write-board-art",
                "Report:",
                "Resume:",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 45.0,
            "step_delay": 4.0,
            "notes": "Grounded from Apply-time board-art failure attribution.",
        }
    if scenario_id == "APPLY-010":
        return {
            "command": _project_apply_resume_success_command(),
            "execution_mode": "ssh-command",
            "actions": [{"step": "000-resume-apply"}],
            "expected_text": [
                '"applied": true',
                '"final_status": "done"',
                '"resume_command": "yoke onboard --resume run-apply-resume"',
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 1.0,
            "step_delay": 0.5,
            "notes": "Grounded from a saved apply report resumed through the CLI.",
        }
    if scenario_id == "APPLY-011":
        return {
            "command": _project_apply_success_command(
                path=APPLY_REPORT_AUDIT_PATH,
                port=APPLY_SUCCESS_YOKE_API_PORT,
                slug="apply-report-audit",
            ),
            "execution_mode": "ssh-command",
            "actions": [{"step": "000-apply-report-audit"}],
            "expected_text": [
                '"applied": true',
                '"final_status": "done"',
                "onboarding-runs/apply-reports",
                '"project-write-board-art"',
            ],
            "post_checks": [
                "secret_free",
                "no_text:Traceback",
                f"no_text:{AUTH_FAKE_TOKEN_VALUE}",
            ],
            "start_delay": 1.0,
            "step_delay": 0.5,
            "notes": "Grounded from successful Apply report audit JSON.",
        }
    if scenario_id == "APPLY-012":
        api_url = f"http://127.0.0.1:{APPLY_CTRL_C_YOKE_API_PORT}"
        return {
            "command": _project_apply_interactive_fake_yoke_command(
                path=APPLY_CTRL_C_PATH,
                port=APPLY_CTRL_C_YOKE_API_PORT,
                payload=_fake_apply_yoke_payload(
                    function_delays={"onboard.checklist.run": 6},
                ),
                log_name="ctrl-c",
                base_url=base_url,
            ),
            "actions": [
                *_project_apply_interactive_local_actions(
                    APPLY_CTRL_C_PATH,
                    api_url=api_url,
                ),
                {"step": "210-ctrl-c-during-apply", "keys": ["C-c"]},
            ],
            "expected_text": [
                "Applying your setup.",
                "Saved .yoke/board-art and rebuilt your board.",
            ],
            "post_checks": [
                "secret_free",
                "no_text:Couldn't finish setup.",
                "no_text:Traceback",
            ],
            "start_delay": 45.0,
            "step_delay": 4.0,
            "notes": "Grounded from Ctrl-C suppression while Apply is in progress.",
        }
    if scenario_id.startswith("TERM-"):
        return _terminal_recipe_template(scenario_id)
    if scenario_id.startswith("STATE-"):
        return _state_recipe_template(scenario_id, base_url)
    return None


def _install_command(
    base_url: str,
    *,
    args: Sequence[str] = (),
    env: Mapping[str, str] | None = None,
    piped_answer: str | None = None,
    download: bool = True,
) -> str:
    download_command = (
        f"curl -fsSL {shlex.quote(base_url.rstrip('/') + '/install')} "
        "-o /tmp/yoke-install"
    )
    command_env = {
        **dict(env or {}),
    }
    env_prefix = _install_env_prefix(base_url, env=command_env)
    install_args = " ".join(shlex.quote(value) for value in args)
    run = f"{env_prefix} sh /tmp/yoke-install"
    if install_args:
        run = f"{run} {install_args}"
    if piped_answer is None:
        return f"{download_command} && {run}" if download else run
    if piped_answer not in {"y", "n"}:
        raise ValueError(f"unsupported piped answer: {piped_answer}")
    piped_run = f"printf '{piped_answer}\\n' | {run}"
    return f"{download_command} && {piped_run}" if download else piped_run


def _refresh_installed_yoke_command(base_url: str, *, log_name: str) -> str:
    install = _install_command(
        base_url,
        args=("--yes", "--no-onboard"),
        env={"YOKE_INSTALL_YES": "1", "YOKE_NO_ONBOARD": "1"},
    )
    safe_name = "".join(
        character if character.isalnum() or character in {"-", "_"} else "-"
        for character in log_name
    ).strip("-")
    if not safe_name:
        safe_name = "refresh"
    return f"({install}) >/tmp/yoke-{safe_name}-install-refresh.log 2>&1"


def _state_refresh_command(base_url: str, *, log_name: str) -> str:
    safe_name = "".join(
        character if character.isalnum() or character in {"-", "_"} else "-"
        for character in log_name
    ).strip("-")
    if not safe_name:
        safe_name = "state"
    return (
        'rm -f "$HOME/.local/bin/yoke"; '
        f"{_refresh_installed_yoke_command(base_url, log_name=log_name)} || true; "
        f'"$HOME/.local/bin/yoke" --version '
        f">/tmp/yoke-{safe_name}-version.txt 2>&1 || exit $?"
    )


def _restore_prepared_state_connection_command(base_url: str) -> str:
    quoted_base = shlex.quote(base_url.rstrip("/"))
    yoke_bin = '"$HOME/.local/bin/yoke"'
    config_path = '"$HOME/.yoke/config.json"'
    token_path = '"$HOME/.yoke/secrets/stage.token"'
    return (
        f"test -f {token_path} && "
        f"{yoke_bin} connection set stage --transport https "
        f"--api-url {quoted_base} --token-file {token_path} --non-prod "
        f"--config {config_path} >/tmp/yoke-state-restore-env.json 2>&1 && "
        f"{yoke_bin} env use stage --config {config_path} "
        ">/tmp/yoke-state-restore-active-env.json 2>&1 || exit $?"
    )


def _state_onboard_command(base_url: str, *, log_name: str) -> str:
    return (
        f"{_state_refresh_command(base_url, log_name=log_name)}; "
        f"{_restore_prepared_state_connection_command(base_url)}; "
        f"{_onboard_command()}"
    )


def _machine_only_onboard_command(
    *,
    env_name: str,
    api_url: str,
    token_path: str,
) -> str:
    yoke_bin = '"$HOME/.local/bin/yoke"'
    onboard_args = [
        "onboard",
        "--non-interactive",
        "--quick",
        "--env",
        env_name,
        "--api-url",
        api_url,
        "--token-file",
        token_path,
        "--project-mode",
        "machine-only",
        "--yes",
        "--json",
    ]
    onboard = " ".join([yoke_bin, *(shlex.quote(value) for value in onboard_args)])
    return f"{onboard} && {yoke_bin} status --json"


def _onboard_command(
    *,
    post_install: bool = False,
    env: Mapping[str, str] | None = None,
) -> str:
    yoke_bin = '"$HOME/.local/bin/yoke"'
    args = ["onboard"]
    if post_install:
        args.append("--post-install")
    env_prefix = " ".join(
        f"{key}={shlex.quote(value)}" for key, value in sorted(dict(env or {}).items())
    )
    command = " ".join([yoke_bin, *(shlex.quote(value) for value in args)])
    return f"{env_prefix} {command}" if env_prefix else command


def _path_fix_command(log_name: str) -> str:
    safe_name = "".join(
        character if character.isalnum() or character in {"-", "_"} else "-"
        for character in log_name
    ).strip("-")
    if not safe_name:
        safe_name = "onboard"
    return (
        '"$HOME/.local/bin/yoke" path fix --yes '
        f">/tmp/yoke-{safe_name}-path-fix.out 2>&1"
    )


def _path_ready_onboard_command(
    *,
    post_install: bool = False,
    env: Mapping[str, str] | None = None,
    log_name: str = "onboard-ready",
) -> str:
    return f"{_path_fix_command(log_name)} && {_onboard_command(post_install=post_install, env=env)}"


def _terminal_recipe_template(scenario_id: str) -> dict[str, object] | None:
    terminal_sizes = {
        "TERM-001": (80, 24, "80x24 terminal"),
        "TERM-002": (100, 32, "100x32 terminal"),
        "TERM-003": (140, 40, "140x40 terminal"),
    }
    if scenario_id in terminal_sizes:
        cols, rows, label = terminal_sizes[scenario_id]
        return {
            "command": _terminal_onboard_command(cols=cols, rows=rows),
            "actions": [
                {"step": "000-path-all-clear"},
                {"step": "010-connect-screen", "keys": ["Enter"]},
            ],
            "expected_text": list(PATH_HEALTH_CONNECT_EXPECTED_TEXT),
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 3.0,
            "step_delay": 2.0,
            "notes": f"Grounded from onboard PATH/account screens at {label}.",
        }
    if scenario_id == "TERM-004":
        return {
            "command": _terminal_onboard_command(
                env={"TERM": "screen-256color", "YOKE_ONBOARD_FORCE_PLAIN": "1"},
                post_install=True,
            ),
            "actions": [
                {"step": "000-plain-path-summary"},
                {"step": "010-plain-path-diagnosis", "keys": ["Enter"]},
            ],
            "expected_text": [
                "* Yoke",
                "Add Yoke to your PATH.",
                *PATH_HEALTH_PLAIN_EXPECTED_TEXT,
            ],
            "post_checks": _plain_glyph_post_checks(),
            "start_delay": 3.0,
            "step_delay": 2.0,
            "notes": "Grounded from onboard plain-glyph behavior under screen terminals.",
        }
    if scenario_id == "TERM-005":
        return {
            "command": _terminal_onboard_command(
                env={"TERM": "dumb", "YOKE_ONBOARD_FORCE_PLAIN": "1"},
                post_install=True,
            ),
            "actions": [
                {"step": "000-dumb-path-summary"},
                {"step": "010-dumb-path-diagnosis", "keys": ["Enter"]},
            ],
            "expected_text": [
                "* Yoke",
                "Add Yoke to your PATH.",
                *PATH_HEALTH_PLAIN_EXPECTED_TEXT,
            ],
            "post_checks": _plain_glyph_post_checks(),
            "start_delay": 3.0,
            "step_delay": 2.0,
            "notes": "Grounded from onboard plain-glyph behavior under TERM=dumb.",
        }
    if scenario_id == "TERM-006":
        return {
            "command": _onboard_command(),
            "actions": [
                {"step": "000-path-all-clear"},
                {"step": "010-up-stays-on-continue", "keys": ["Up"]},
                {"step": "020-down-stays-on-continue", "keys": ["Down"]},
            ],
            "expected_text": [*PATH_HEALTH_EXPECTED_TEXT, "Continue"],
            "post_checks": ["secret_free", "no_text:Traceback", "no_text:Quit"],
            "start_delay": 3.0,
            "step_delay": 1.0,
            "notes": "Grounded from single-action first-screen navigation behavior.",
        }
    if scenario_id in {"TERM-007", "TERM-008"}:
        select_key = "Space" if scenario_id == "TERM-007" else "C-j"
        label = "Space" if scenario_id == "TERM-007" else "Ctrl-J"
        return {
            "command": _onboard_command(),
            "actions": [
                {"step": "000-path-all-clear"},
                {"step": "010-connect-screen", "keys": [select_key]},
            ],
            "expected_text": list(PATH_HEALTH_CONNECT_EXPECTED_TEXT),
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 3.0,
            "step_delay": 2.0,
            "notes": f"Grounded from {label} selecting the highlighted row.",
        }
    if scenario_id == "TERM-009":
        return {
            "command": _onboard_command(),
            "actions": [
                {"step": "000-path-all-clear"},
                {"step": "010-connect-screen", "keys": ["Enter"]},
                {"step": "020-back-to-path", "keys": ["Escape"]},
            ],
            "expected_text": [
                *PATH_HEALTH_EXPECTED_TEXT,
                "Where should this Yoke live?",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 3.0,
            "step_delay": 2.0,
            "notes": "Grounded from Escape backing out of the Account step.",
        }
    if scenario_id == "TERM-010":
        return {
            "command": _onboard_command(),
            "actions": [
                {"step": "000-path-all-clear"},
                {"step": "010-ctrl-c", "keys": ["C-c"], "capture": False},
            ],
            "expected_text": list(PATH_HEALTH_EXPECTED_TEXT),
            "post_checks": [
                "secret_free",
                "no_text:Traceback",
                "tmux_exit_code:0",
                "tmux_exit_code:130",
            ],
            "start_delay": 3.0,
            "step_delay": 1.0,
            "notes": "Grounded from clean Ctrl-C exit before Apply starts.",
        }
    if scenario_id == "TERM-011":
        return {
            "command": _terminal_onboard_command(
                env={"TERM": "screen-256color", "YOKE_ONBOARD_FORCE_PLAIN": "1"},
            ),
            "actions": [{"step": "000-screen-compat-account"}],
            "expected_text": [
                "* Yoke",
                *PATH_HEALTH_PLAIN_EXPECTED_TEXT,
            ],
            "post_checks": [
                *_plain_glyph_post_checks(),
                "no_text:[<",
            ],
            "start_delay": 3.0,
            "step_delay": 1.0,
            "notes": "Grounded from screen-compatible onboard rendering with mouse noise absent.",
        }
    if scenario_id == "TERM-012":
        return {
            "command": _project_meta_onboard_command(path=TERM_LONG_PROJECT_PATH),
            "stage_files": _stage_stage_yoke_token_files(),
            "actions": [
                *_project_meta_existing_folder_actions(TERM_LONG_PROJECT_PATH),
                {
                    "step": "090-project-name-input",
                    "keys": ["Enter"],
                },
                {
                    "step": "100-publish-prompt",
                    "keys": ["Enter"],
                },
            ],
            "expected_text": [
                "Give it a friendly name.",
                TERM_LONG_PROJECT_NAME,
                "Also publish to GitHub?",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 3.0,
            "step_delay": 4.0,
            "notes": "Grounded from long project path/name wrapping in the metadata flow.",
        }
    return None


def _state_recipe_template(
    scenario_id: str,
    base_url: str,
) -> dict[str, object] | None:
    if scenario_id == "STATE-001":
        return {
            "command": _state_onboard_command(base_url, log_name="state-001"),
            "actions": _auth_stored_token_actions(),
            "expected_text": [
                "Using existing environment:",
                "Using existing Yoke token file from machine config.",
                "Yoke token connected.",
                "Success! You've authenticated with Yoke.",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": STATE_TUI_SETUP_START_DELAY,
            "step_delay": 4.0,
            "notes": "Grounded from live prepared-stored-state Account reuse proof.",
        }
    if scenario_id == "STATE-003":
        return {
            "command": _state_project_onboard_command(
                base_url=base_url,
                port=STATE_ONE_PROJECT_YOKE_API_PORT,
                projects=[(STATE_PROJECT_ONE_PATH, 101)],
            ),
            "actions": [
                *_state_stored_project_prefix_actions(),
                {"step": "040-existing-project-ready"},
            ],
            "expected_text": [
                "Existing Yoke project found.",
                "Local machine: found project id 101 in machine config.",
                "Yoke core database: verified project id 101.",
                "Project: state-project-one",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": STATE_TUI_SETUP_START_DELAY,
            "step_delay": 4.0,
            "notes": "Grounded from one stored checkout auto-verifying its project id.",
        }
    if scenario_id == "STATE-004":
        return {
            "command": _state_project_onboard_command(
                base_url=base_url,
                port=STATE_MULTI_PROJECT_YOKE_API_PORT,
                projects=[
                    (STATE_PROJECT_ONE_PATH, 101),
                    (STATE_PROJECT_TWO_PATH, 102),
                ],
            ),
            "actions": [
                *_state_stored_project_prefix_actions(),
                {"step": "040-stored-project-picker"},
                {"step": "050-existing-project-ready", "keys": ["Enter"]},
            ],
            "expected_text": [
                "Use an existing checkout?",
                "Yoke found project mappings already saved on this machine.",
                STATE_PROJECT_ONE_PATH,
                STATE_PROJECT_TWO_PATH,
                "Choose another project",
                "Existing Yoke project found.",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": STATE_TUI_SETUP_START_DELAY,
            "step_delay": 4.0,
            "notes": "Grounded from stored project picker behavior with multiple checkouts.",
        }
    if scenario_id == "STATE-005":
        return {
            "command": _state_project_onboard_command(
                base_url=base_url,
                port=STATE_MISSING_PROJECT_YOKE_API_PORT,
                projects=[(STATE_PROJECT_MISSING_PATH, 404)],
                function_errors={
                    "projects.get": {
                        "code": "not_found",
                        "message": "project 404 was not found",
                    }
                },
            ),
            "actions": [
                *_state_stored_project_prefix_actions(),
                {"step": "040-project-missing"},
            ],
            "expected_text": [
                "Can't use that Yoke project.",
                "project 404 was not found",
                "Try again",
                "Back",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": STATE_TUI_SETUP_START_DELAY,
            "step_delay": 4.0,
            "notes": "Grounded from stored checkout project-id lookup failure.",
        }
    if scenario_id == "STATE-006":
        return {
            "command": _state_env_switch_command(base_url),
            "execution_mode": "ssh-command",
            "actions": [{"step": "000-env-switch"}],
            "expected_text": [
                f'"api_url": "{HOSTED_STAGE_URL}"',
                '"env": "stage"',
                f'"api_url": "{HOSTED_PROD_URL}"',
                '"env": "prod"',
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 0.0,
            "step_delay": 0.5,
            "notes": "Grounded from machine config with stage and prod credential-file connections.",
        }
    if scenario_id == "STATE-008":
        return {
            "command": _state_one_shot_path_command(base_url),
            "execution_mode": "ssh-command",
            "actions": [{"step": "000-one-shot-path"}],
            "expected_text": [
                "/yoke",
                "0.1.1",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 0.0,
            "step_delay": 0.5,
            "notes": "Grounded from one-shot shell command after PATH repair.",
        }
    if scenario_id == "STATE-009":
        return {
            "command": _state_reinstall_command(base_url),
            "execution_mode": "ssh-command",
            "actions": [{"step": "000-reset-reinstall"}],
            "expected_text": [
                "Setting up Yoke",
                "Yoke v",
                "0.1.1",
            ],
            "post_checks": ["secret_free", "no_text:Traceback"],
            "start_delay": 0.0,
            "step_delay": 0.5,
            "notes": "Grounded from removing product tool state and reinstalling from stage.",
        }
    return None


def _auth_token_file_actions(
    *,
    env_keys: Sequence[str],
    token_path: str,
) -> list[dict[str, object]]:
    return [
        {"step": "000-path-all-clear"},
        {"step": "010-destination-picker", "keys": ["Enter"]},
        {"step": "020-env-select", "keys": ["Enter"]},
        {"step": "030-token-method", "keys": list(env_keys)},
        {"step": "040-token-file-input", "keys": ["Down", "Enter"]},
        {"step": "050-yoke-token-verified", "keys": [token_path, "Enter"]},
    ]


def _auth_custom_token_file_actions(
    *,
    api_url: str,
    token_path: str,
) -> list[dict[str, object]]:
    return [
        {"step": "000-path-all-clear"},
        {"step": "010-destination-picker", "keys": ["Enter"]},
        {"step": "020-server-url-input", "keys": ["Up", "Enter"]},
        {"step": "030-token-method", "keys": [api_url, "Enter"]},
        {"step": "040-token-file-input", "keys": ["Down", "Enter"]},
        {"step": "050-yoke-token-result", "keys": [token_path, "Enter"]},
    ]


def _auth_token_paste_actions(
    *,
    env_keys: Sequence[str],
    token_path: str,
) -> list[dict[str, object]]:
    return [
        {"step": "000-path-all-clear"},
        {"step": "010-destination-picker", "keys": ["Enter"]},
        {"step": "020-env-select", "keys": ["Enter"]},
        {"step": "030-token-method", "keys": list(env_keys)},
        {"step": "040-token-paste-input", "keys": ["Enter"]},
        {
            "step": "050-yoke-token-verified",
            "keys": [f"paste_file:{token_path}", "Enter"],
        },
    ]


def _auth_stored_token_actions() -> list[dict[str, object]]:
    return [
        {"step": "000-path-all-clear"},
        {"step": "010-stored-token-result", "keys": ["Enter"]},
    ]


def _auth_success_expected_text(
    *,
    env_label: str,
    token_prompt: str,
) -> list[str]:
    return [
        "Where should this Yoke live?",
        "Connect to Yoke.",
        env_label,
        "Read it from a file",
        "Point at your token file.",
        token_prompt,
        "Yoke token connected.",
        "Success! You've authenticated with Yoke.",
        "Actor:",
    ]


def _stage_stage_yoke_token_files() -> list[dict[str, object]]:
    return [
        {
            "source_path": REMOTE_STAGE_TOKEN_PATH,
            "remote_path": REMOTE_STAGE_TOKEN_PATH,
        }
    ]


def _github_stage_token_prefix_actions() -> list[dict[str, object]]:
    return [
        {"step": "000-path-all-clear"},
        {"step": "010-destination-picker", "keys": ["Enter"]},
        {"step": "020-env-select", "keys": ["Enter"]},
        {"step": "030-token-method", "keys": ["Down", "Enter"]},
        {"step": "040-yoke-token-file-input", "keys": ["Down", "Enter"]},
        {
            "step": "050-yoke-token-verified",
            "keys": [
                REMOTE_STAGE_TOKEN_PATH,
                "Enter",
            ],
        },
    ]


def _github_picker_actions(
    *, stored_api_error: bool = False
) -> list[dict[str, object]]:
    actions = [
        *_github_stage_token_prefix_actions(),
        {"step": "050-github-picker", "keys": ["Enter"]},
    ]
    if stored_api_error:
        actions.extend(
            [
                {"step": "060-github-picker", "keys": ["Down", "Enter"]},
            ]
        )
    return actions


def _github_skip_actions() -> list[dict[str, object]]:
    return [
        *_github_picker_actions(),
        {"step": "060-github-skip-option", "keys": ["Down"]},
        {"step": "061-project-mode", "keys": ["Enter"]},
    ]




def _project_source_project_mode_actions() -> list[dict[str, object]]:
    return _github_skip_actions()


def _project_source_machine_only_actions() -> list[dict[str, object]]:
    return [
        *_project_source_project_mode_actions(),
        {
            "step": "070-finish-review",
            "keys": ["Down", "Down", "Down", "Down", "Enter"],
        },
    ]


def _project_source_create_folder_actions(path: str) -> list[dict[str, object]]:
    return [
        *_project_source_project_mode_actions(),
        {"step": "070-create-folder-input", "keys": ["Down", "Down", "Enter"]},
        {"step": "080-project-slug-input", "keys": [path, "Enter"]},
    ]


def _project_source_existing_folder_actions(path: str) -> list[dict[str, object]]:
    return [
        *_project_source_project_mode_actions(),
        {"step": "070-existing-folder-input", "keys": ["Enter"]},
        {"step": "080-project-slug-input", "keys": [path, "Enter"]},
    ]


def _project_source_create_existing_redirect_actions(
    path: str,
) -> list[dict[str, object]]:
    return [
        *_project_source_project_mode_actions(),
        {"step": "070-create-folder-input", "keys": ["Down", "Down", "Enter"]},
        {"step": "080-existing-folder-redirect", "keys": [path, "Enter"]},
    ]


def _project_source_clone_actions(
    *,
    remote_url: str,
    clone_path: str,
) -> list[dict[str, object]]:
    return [
        *_project_source_project_mode_actions(),
        {"step": "070-clone-url-input", "keys": ["Down", "Enter"]},
        {"step": "080-clone-folder-input", "keys": [remote_url, "Enter"]},
        {"step": "090-clone-outcome", "keys": [clone_path, "Enter"]},
    ]


def _project_source_clone_url_error_actions(
    remote_url: str,
) -> list[dict[str, object]]:
    return [
        *_project_source_project_mode_actions(),
        {"step": "070-clone-url-input", "keys": ["Down", "Enter"]},
        {"step": "080-clone-url-error", "keys": [remote_url, "Enter"]},
    ]


def _project_source_clone_conflict_actions(
    *,
    remote_url: str,
    clone_path: str,
) -> list[dict[str, object]]:
    return [
        *_project_source_project_mode_actions(),
        {"step": "070-clone-url-input", "keys": ["Down", "Enter"]},
        {"step": "080-clone-folder-input", "keys": [remote_url, "Enter"]},
        {"step": "090-clone-folder-error", "keys": [clone_path, "Enter"]},
    ]



def _project_source_git_required_actions() -> list[dict[str, object]]:
    return [
        *_project_source_project_mode_actions(),
        {"step": "070-git-required", "keys": ["Enter"]},
    ]


def _project_source_git_install_actions() -> list[dict[str, object]]:
    return [
        *_project_source_git_required_actions(),
        {"step": "080-git-install-returned", "keys": ["Enter"]},
    ]


def _project_source_dev_mode_actions() -> list[dict[str, object]]:
    return [
        {"step": "000-path-all-clear"},
        {"step": "010-yoke-stored-token-result", "keys": ["Enter"]},
        {"step": "020-github-picker", "keys": ["Enter"]},
        {"step": "030-github-skip-option", "keys": ["Down"]},
        {"step": "031-project-mode", "keys": ["Enter"]},
        {
            "step": "040-source-dev-option",
            "keys": ["Down", "Down", "Down"],
        },
        {
            "step": "041-source-dev-mode",
            "keys": ["Enter"],
        },
    ]


def _project_source_dev_checkout_actions(path: str) -> list[dict[str, object]]:
    return [
        *_project_source_dev_mode_actions(),
        {"step": "050-yoke-checkout-input", "keys": [path, "Enter"]},
    ]


def _project_meta_existing_folder_actions(path: str) -> list[dict[str, object]]:
    return [
        *_project_source_project_mode_actions(),
        {"step": "070-existing-folder-input", "keys": ["Enter"]},
        {"step": "080-project-slug-input", "keys": [path, "Enter"]},
    ]


def _project_meta_create_folder_actions(
    path: str,
    *,
    settled: bool = False,
) -> list[dict[str, object]]:
    actions = [
        *_project_source_project_mode_actions(),
        {"step": "070-create-folder-option", "keys": ["Down", "Down"]},
        {"step": "080-create-folder-input", "keys": ["Enter"]},
    ]
    if settled:
        actions.append({"step": "090-create-folder-input-ready"})
    actions.append(
        {
            "step": "100-project-slug-input" if settled else "090-project-slug-input",
            "keys": [path, "Enter"],
        }
    )
    return actions


def _project_meta_metadata_prefix_actions(path: str) -> list[dict[str, object]]:
    return [
        *_project_meta_existing_folder_actions(path),
        {"step": "090-project-name-input", "keys": ["Enter"]},
        {"step": "100-publish-prompt", "keys": ["Enter"]},
        {"step": "110-publish-decline-option", "keys": ["Down"]},
        {"step": "120-default-branch-input", "keys": ["Enter"]},
    ]


def _project_meta_review_actions(path: str) -> list[dict[str, object]]:
    return [
        *_project_meta_metadata_prefix_actions(path),
        {"step": "130-prefix-input", "keys": ["Enter"]},
        {"step": "140-prefix-input", "keys": ["META", "Enter"]},
        *_project_meta_board_art_actions(first_step=150),
    ]


def _project_meta_board_art_actions(*, first_step: int) -> list[dict[str, object]]:
    return [
        {"step": f"{first_step:03d}-board-art-intro", "keys": ["Enter"]},
        {"step": f"{first_step + 10:03d}-board-art-map", "keys": ["Enter"]},
        {"step": f"{first_step + 20:03d}-board-art-style", "keys": ["Enter"]},
        {"step": f"{first_step + 30:03d}-board-art-preview", "keys": ["Enter"]},
        {
            "step": f"{first_step + 40:03d}-board-art-save",
            "keys": ["Enter"],
        },
        {
            "step": f"{first_step + 50:03d}-board-art-continue-option",
            "keys": ["Down"],
        },
        {
            "step": f"{first_step + 60:03d}-review-from-board-art",
            "keys": ["Enter"],
        },
    ]


def _project_meta_fake_yoke_prefix_actions(api_url: str) -> list[dict[str, object]]:
    del api_url
    return [
        {"step": "000-path-all-clear"},
        {"step": "010-yoke-stored-token-result", "keys": ["Enter"]},
        {"step": "020-github-picker", "keys": ["Enter"]},
        {"step": "030-github-skip-option", "keys": ["Down"]},
        {"step": "031-project-mode", "keys": ["Enter"]},
    ]



def _project_meta_apply_failure_actions(path: str) -> list[dict[str, object]]:
    api_url = f"http://127.0.0.1:{PROJECT_META_FAKE_YOKE_API_PORT}"
    return [
        *_project_meta_fake_yoke_prefix_actions(api_url),
        {"step": "040-existing-folder-input", "keys": ["Enter"]},
        {"step": "050-project-slug-input", "keys": [path, "Enter"]},
        {"step": "060-project-name-input", "keys": ["Enter"]},
        {"step": "070-name-input", "keys": ["Enter"]},
        {"step": "080-publish-decline-option", "keys": ["Down"]},
        {"step": "090-default-branch-input", "keys": ["Enter"]},
        {"step": "100-prefix-input", "keys": ["Enter"]},
        {"step": "110-prefix-input", "keys": ["META", "Enter"]},
        *_project_meta_board_art_actions(first_step=120),
        {"step": "190-apply-failure", "keys": ["Enter"]},
    ]


def _project_publish_no_publish_actions(path: str) -> list[dict[str, object]]:
    return [
        *_project_meta_create_folder_actions(path),
        {"step": "090-project-slug-input", "keys": ["Enter"]},
        {"step": "100-project-name-input", "keys": ["Enter"]},
        {"step": "110-publish-prompt", "keys": ["Enter"]},
        {"step": "120-publish-decline-option", "keys": ["Down"]},
        {"step": "130-default-branch-input", "keys": ["Enter"]},
        {"step": "140-prefix-input", "keys": ["PUB", "Enter"]},
        *_project_meta_board_art_actions(first_step=150),
    ]



def _project_apply_interactive_local_actions(
    path: str,
    *,
    api_url: str,
) -> list[dict[str, object]]:
    return [
        *_project_meta_fake_yoke_prefix_actions(api_url),
        {"step": "080-existing-folder-input", "keys": ["Enter"]},
        {"step": "090-project-slug-input", "keys": [path, "Enter"]},
        {"step": "100-project-name-input", "keys": ["Enter"]},
        {"step": "110-name-input", "keys": ["Enter"]},
        {"step": "120-publish-decline", "keys": ["Down", "Enter"]},
        {"step": "130-default-branch-input", "keys": ["Enter"]},
        {"step": "140-prefix-input", "keys": ["APL", "Enter"]},
        *_project_meta_board_art_actions(first_step=150),
        {"step": "220-apply", "keys": ["Enter"]},
    ]


def _prepare_missing_token_onboard_command(token_path: str) -> str:
    return f"rm -f {shlex.quote(token_path)}; {_path_ready_onboard_command()}"


def _prepare_empty_token_onboard_command(token_path: str) -> str:
    quoted = shlex.quote(token_path)
    return f": > {quoted} && chmod 600 {quoted} && {_path_ready_onboard_command()}"


def _prepare_invalid_token_onboard_command(token_path: str) -> str:
    return _prepare_token_onboard_command(
        token_path=token_path,
        token_value="not-a-real-yoke-token",
    )


def _prepare_token_onboard_command(
    *,
    token_path: str,
    token_value: str,
) -> str:
    quoted_path = shlex.quote(token_path)
    quoted_token = shlex.quote(token_value)
    return (
        f"printf '%s\\n' {quoted_token} > {quoted_path} && "
        f"chmod 600 {quoted_path} && {_path_ready_onboard_command()}"
    )


def _clear_yoke_auth_state_command() -> str:
    return 'rm -f "$HOME/.yoke/config.json"; rm -rf "$HOME/.yoke/secrets"; '


def _prepare_invalid_stored_yoke_token_onboard_command() -> str:
    return (
        "stored_token=\"$HOME/.yoke/secrets/stage.token\"; "
        "stored_token_backup=\"/tmp/yoke-stored-stage-token.backup\"; "
        "cp \"$stored_token\" \"$stored_token_backup\" && "
        "restore_stored_token() { "
        "cp \"$stored_token_backup\" \"$stored_token\" >/dev/null 2>&1 || true; "
        "rm -f \"$stored_token_backup\"; "
        "}; "
        "trap restore_stored_token EXIT HUP INT TERM; "
        "printf '%s\\n' not-a-real-yoke-token "
        "> \"$stored_token\" && "
        "chmod 600 \"$stored_token\" && "
        f"{_path_ready_onboard_command()}"
    )


def _restore_stored_yoke_token_onboard_command() -> str:
    return (
        "mkdir -p \"$HOME/.yoke/secrets\" && "
        f"cp {shlex.quote(REMOTE_STAGE_TOKEN_PATH)} "
        "\"$HOME/.yoke/secrets/stage.token\" && "
        "chmod 600 \"$HOME/.yoke/secrets/stage.token\" && "
        f"{_path_ready_onboard_command()}"
    )


def _fake_yoke_api_onboard_command(
    *,
    port: int,
    payload: Mapping[str, object],
    stored_config: bool = False,
) -> str:
    server = _fake_yoke_api_server_command(port=port, payload=payload)
    api_url = f"http://127.0.0.1:{port}"
    token_setup = _prepare_token_command(
        token_path=REMOTE_FAKE_YOKE_TOKEN_PATH,
        token_value=AUTH_FAKE_TOKEN_VALUE,
    )
    setup_commands = [token_setup]
    if stored_config:
        setup_commands.append(
            _machine_yoke_config_command(
                api_url=api_url,
                token_path=REMOTE_FAKE_YOKE_TOKEN_PATH,
            )
        )
    return (
        f"{' && '.join(setup_commands)}; "
        f"{server} >/tmp/yoke-fake-api-{port}.log 2>&1 & "
        "fake_pid=$!; "
        "trap 'kill \"$fake_pid\" >/dev/null 2>&1 || true' EXIT; "
        f"sleep 1; {_path_ready_onboard_command(log_name='fake-yoke-api')}"
    )



def _machine_yoke_config_command(*, api_url: str, token_path: str) -> str:
    script = (
        "import json,pathlib,sys\n"
        "path=pathlib.Path.home()/'.yoke'/'config.json'\n"
        "path.parent.mkdir(parents=True,exist_ok=True)\n"
        "payload={}\n"
        "if path.is_file():\n"
        "    try:\n"
        "        loaded=json.loads(path.read_text(encoding='utf-8'))\n"
        "        payload=loaded if isinstance(loaded,dict) else {}\n"
        "    except ValueError:\n"
        "        payload={}\n"
        "payload['schema_version']=1\n"
        "payload['active_env']='stage'\n"
        "payload.setdefault('temp_root','~/.yoke/tmp')\n"
        "payload.setdefault('cache_dir','~/.yoke/cache')\n"
        "connections=payload.setdefault('connections',{})\n"
        "connections['stage']={\n"
        "    'transport':'https',\n"
        "    'prod':False,\n"
        "    'api_url':sys.argv[1],\n"
        "    'credential_source':{'kind':'token_file','path':sys.argv[2]},\n"
        "}\n"
        "payload.pop('projects',None)\n"
        "payload.pop('github',None)\n"
        "path.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\\n',encoding='utf-8')\n"
        "path.chmod(0o600)\n"
    )
    return " ".join(
        [
            "python3",
            "-c",
            shlex.quote(script),
            shlex.quote(api_url),
            shlex.quote(token_path),
        ]
    )


def _terminal_onboard_command(
    *,
    cols: int | None = None,
    rows: int | None = None,
    env: Mapping[str, str] | None = None,
    post_install: bool = False,
) -> str:
    parts: list[str] = []
    if cols is not None and rows is not None:
        parts.append(
            f"tmux resize-window -x {int(cols)} -y {int(rows)} >/dev/null 2>&1 || true"
        )
    parts.append(_onboard_command(post_install=post_install, env=env))
    return "; ".join(parts)


def _state_stored_project_prefix_actions() -> list[dict[str, object]]:
    return [
        {"step": "000-path-all-clear"},
        {"step": "010-yoke-stored-token-result", "keys": ["Enter"]},
        {"step": "020-github-prompt", "keys": ["Enter"]},
        {"step": "030-github-skip", "keys": ["Down", "Enter"]},
    ]


def _state_project_onboard_command(
    *,
    base_url: str,
    port: int,
    projects: Sequence[tuple[str, int]],
    function_errors: Mapping[str, object] | None = None,
) -> str:
    api_url = f"http://127.0.0.1:{port}"
    server = _fake_yoke_api_server_command(
        port=port,
        payload=_fake_state_yoke_payload(
            project_id=projects[0][1],
            function_errors=function_errors,
        ),
    )
    setup_parts = [
        _state_refresh_command(base_url, log_name=f"state-project-{port}"),
        _cleanup_state_project_paths(project for project, _project_id in projects),
        _prepare_token_command(
            token_path=REMOTE_FAKE_YOKE_TOKEN_PATH,
            token_value=AUTH_FAKE_TOKEN_VALUE,
        ),
        _machine_yoke_config_command(
            api_url=api_url,
            token_path=REMOTE_FAKE_YOKE_TOKEN_PATH,
        ),
        *(
            _state_project_register_command(path=path, project_id=project_id)
            for path, project_id in projects
        ),
        (
            f"{server} >/tmp/yoke-state-fake-api-{port}.log 2>&1 & "
            "fake_pid=$!; "
            "trap 'kill \"$fake_pid\" >/dev/null 2>&1 || true' EXIT; "
            "sleep 1"
        ),
        _onboard_command(),
    ]
    return "; ".join(setup_parts)


def _cleanup_state_project_paths(paths: Sequence[str]) -> str:
    return "rm -rf " + " ".join(shlex.quote(path) for path in paths)


def _state_project_register_command(*, path: str, project_id: int) -> str:
    quoted_path = shlex.quote(path)
    yoke_bin = '"$HOME/.local/bin/yoke"'
    log_path = shlex.quote(f"/tmp/yoke-state-project-register-{int(project_id)}.json")
    return (
        f"mkdir -p {quoted_path} && "
        f"{yoke_bin} project register {quoted_path} "
        f'--project-id {int(project_id)} --config "$HOME/.yoke/config.json" '
        f">{log_path} 2>&1"
    )


def _state_env_switch_command(base_url: str) -> str:
    script = (
        "import json,pathlib\n"
        "home=pathlib.Path.home()\n"
        "config=home/'.yoke'/'config.json'\n"
        "config.parent.mkdir(parents=True,exist_ok=True)\n"
        "secrets=home/'.yoke'/'secrets'\n"
        "secrets.mkdir(parents=True,exist_ok=True)\n"
        "stage=secrets/'stage.token'\n"
        "prod=secrets/'prod.token'\n"
        "stage.write_text('fake-stage-token\\n',encoding='utf-8')\n"
        "prod.write_text('fake-prod-token\\n',encoding='utf-8')\n"
        "stage.chmod(0o600)\n"
        "prod.chmod(0o600)\n"
        "payload={\n"
        "  'schema_version':1,\n"
        "  'active_env':'stage',\n"
        "  'temp_root':'~/.yoke/tmp',\n"
        "  'cache_dir':'~/.yoke/cache',\n"
        "  'connections':{\n"
        "    'stage':{'transport':'https','prod':False,'api_url':'" + HOSTED_STAGE_URL + "','credential_source':{'kind':'token_file','path':str(stage)}},\n"
        "    'prod':{'transport':'https','prod':True,'api_url':'" + HOSTED_PROD_URL + "','credential_source':{'kind':'token_file','path':str(prod)}},\n"
        "  },\n"
        "}\n"
        "config.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\\n',encoding='utf-8')\n"
        "config.chmod(0o600)\n"
    )
    yoke_bin = '"$HOME/.local/bin/yoke"'
    return (
        f"{_state_refresh_command(base_url, log_name='state-env-switch')}; "
        "python3 -c "
        f"{shlex.quote(script)} && "
        f"{yoke_bin} status --json && "
        f"YOKE_ENV=prod {yoke_bin} status --json"
    )


def _state_one_shot_path_command(base_url: str) -> str:
    yoke_bin = '"$HOME/.local/bin/yoke"'
    return (
        f"{_state_refresh_command(base_url, log_name='state-one-shot-path')}; "
        f"{yoke_bin} path fix >/tmp/yoke-state-path-fix.txt && "
        "sh -lc 'command -v yoke; yoke --version'"
    )


def _state_reinstall_command(base_url: str) -> str:
    quoted_base = shlex.quote(base_url.rstrip("/"))
    return (
        'rm -rf "$HOME/.local/share/uv/tools/yoke-cli" '
        '"$HOME/.local/bin/yoke"; '
        f"curl -fsSL {quoted_base}/install -o /tmp/yoke-state-install && "
        f"YOKE_INSTALL_BASE_URL={quoted_base} YOKE_CHANNEL=latest "
        "YOKE_INSTALL_YES=1 YOKE_NO_ONBOARD=1 "
        "sh /tmp/yoke-state-install --yes --no-onboard && "
        '"$HOME/.local/bin/yoke" --version'
    )


def _project_source_onboard_command(
    *,
    existing_checkout: bool = False,
    conflict_checkout: bool = False,
    remote_branches: Mapping[str, str] | None = None,
) -> str:
    return (
        f"{_project_source_setup_command(existing_checkout=existing_checkout, conflict_checkout=conflict_checkout, remote_branches=remote_branches)}; "
        f"{_path_ready_onboard_command(log_name='project-source')}"
    )



def _project_meta_onboard_command(*, path: str = PROJECT_META_CHECKOUT_PATH) -> str:
    return f"{_project_meta_setup_command(path=path)}; {_onboard_command()}"



def _project_meta_board_data_failure_onboard_command() -> str:
    return (
        f"{_project_meta_setup_command(path=PROJECT_META_BOARD_DATA_FAIL_PATH)}; "
        f"{_fake_yoke_api_onboard_command(port=PROJECT_META_FAKE_YOKE_API_PORT, payload=_fake_project_meta_board_data_failure_payload(), stored_config=True)}"
    )


def _project_publish_stage_onboard_command(path: str) -> str:
    return f"{_project_meta_setup_command(path=path)}; {_onboard_command()}"



def _project_apply_clone_review_command() -> str:
    args = [
        "onboard",
        "--non-interactive",
        "--quick",
        "--json",
        "--env",
        "stage",
        "--api-url",
        "http://127.0.0.1:9",
        "--token-file",
        REMOTE_FAKE_YOKE_TOKEN_PATH,
        "--skip-identity-check",
        "--project-mode",
        "clone-remote",
        "--remote-url",
        PROJECT_SOURCE_MAIN_REMOTE_URL,
        "--checkout",
        APPLY_CLONE_PATH,
        "--project-slug",
        "apply-clone",
        "--project-name",
        "Apply Clone",
        "--github-repo",
        "recipe/main-source",
        "--default-branch",
        "main",
        "--public-item-prefix",
        "APC",
        "--github-adoption",
        "backlog-only",
    ]
    return " && ".join(
        [
            _project_source_setup_command(remote_branches={"main-source": "main"}),
            _prepare_token_command(
                token_path=REMOTE_FAKE_YOKE_TOKEN_PATH,
                token_value=AUTH_FAKE_TOKEN_VALUE,
            ),
            _yoke_command(args),
        ]
    )


def _project_apply_machine_config_failure_command() -> str:
    args = [
        "onboard",
        "--non-interactive",
        "--quick",
        "--json",
        "--config",
        "/dev/null/config.json",
        "--env",
        "stage",
        "--api-url",
        "http://127.0.0.1:9",
        "--token-file",
        REMOTE_FAKE_YOKE_TOKEN_PATH,
        "--yes",
        "--skip-identity-check",
    ]
    return " && ".join(
        [
            _prepare_token_command(
                token_path=REMOTE_FAKE_YOKE_TOKEN_PATH,
                token_value=AUTH_FAKE_TOKEN_VALUE,
            ),
            _yoke_command(args),
        ]
    )



def _project_apply_project_create_failure_command() -> str:
    return _project_apply_fake_yoke_local_apply_command(
        path=APPLY_PROJECT_DENIED_PATH,
        port=APPLY_PROJECT_DENIED_YOKE_API_PORT,
        payload=_fake_apply_yoke_payload(
            function_errors={
                "projects.get": {
                    "code": "not_found",
                    "message": "project not found",
                },
                "projects.create": {
                    "code": "permission_denied",
                    "message": "permission denied for org acme",
                },
            }
        ),
        slug="apply-project-denied",
        github_repo="owner/apply-project-denied",
        github_adoption="backlog-only",
        log_name="project-denied",
    )


def _project_apply_clone_conflict_failure_command() -> str:
    args = [
        "onboard",
        "--non-interactive",
        "--quick",
        "--json",
        "--env",
        "stage",
        "--api-url",
        "http://127.0.0.1:9",
        "--token-file",
        REMOTE_FAKE_YOKE_TOKEN_PATH,
        "--yes",
        "--skip-identity-check",
        "--project-mode",
        "clone-remote",
        "--remote-url",
        PROJECT_SOURCE_MAIN_REMOTE_URL,
        "--checkout",
        APPLY_CLONE_CONFLICT_PATH,
        "--project-slug",
        "apply-clone-conflict",
        "--project-name",
        "Apply Clone Conflict",
        "--github-repo",
        "recipe/main-source",
        "--default-branch",
        "main",
        "--public-item-prefix",
        "ACC",
        "--github-adoption",
        "backlog-only",
    ]
    return " && ".join(
        [
            _project_source_setup_command(remote_branches={"main-source": "main"}),
            _project_apply_conflict_checkout_command(APPLY_CLONE_CONFLICT_PATH),
            _prepare_token_command(
                token_path=REMOTE_FAKE_YOKE_TOKEN_PATH,
                token_value=AUTH_FAKE_TOKEN_VALUE,
            ),
            _yoke_command(args),
        ]
    )


def _project_apply_success_command(
    *,
    path: str,
    port: int,
    slug: str,
) -> str:
    return _project_apply_fake_yoke_local_apply_command(
        path=path,
        port=port,
        payload=_fake_apply_yoke_payload(),
        slug=slug,
        github_repo=f"owner/{slug}",
        github_adoption="backlog-only",
        log_name=slug,
    )


def _project_apply_resume_success_command() -> str:
    yoke_api_url = f"http://127.0.0.1:{APPLY_RESUME_YOKE_API_PORT}"
    yoke_server = _fake_yoke_api_server_command(
        port=APPLY_RESUME_YOKE_API_PORT,
        payload=_fake_apply_yoke_payload(),
    )
    setup = " && ".join(
        [
            _project_meta_setup_command(path=APPLY_RESUME_PATH),
            _prepare_token_command(
                token_path=REMOTE_FAKE_YOKE_TOKEN_PATH,
                token_value=AUTH_FAKE_TOKEN_VALUE,
            ),
            _project_apply_seed_resume_report_command(
                api_url=yoke_api_url,
                path=APPLY_RESUME_PATH,
            ),
        ]
    )
    args = [
        "onboard",
        "--resume",
        "run-apply-resume",
        "--yes",
        "--non-interactive",
        "--json",
        "--skip-identity-check",
    ]
    return (
        f"{setup}; "
        f"{yoke_server} >/tmp/yoke-apply-resume-api.log 2>&1 & "
        "apply_resume_pid=$!; "
        "trap 'kill \"$apply_resume_pid\" >/dev/null 2>&1 || true' EXIT; "
        f"sleep 1; {_yoke_command(args)}"
    )


def _project_apply_interactive_fake_yoke_command(
    *,
    path: str,
    port: int,
    payload: Mapping[str, object],
    log_name: str,
    base_url: str | None = None,
) -> str:
    payload = _payload_with_board_data(payload, path=path)
    yoke_server = _fake_yoke_api_server_command(port=port, payload=payload)
    api_url = f"http://127.0.0.1:{port}"
    setup_commands: list[str] = []
    if base_url:
        setup_commands.append(
            _refresh_installed_yoke_command(base_url, log_name=f"apply-{log_name}")
        )
    setup_commands.extend(
        [
            _project_meta_setup_command(path=path),
            _prepare_token_command(
                token_path=REMOTE_FAKE_YOKE_TOKEN_PATH,
                token_value=AUTH_FAKE_TOKEN_VALUE,
            ),
            _machine_yoke_config_command(
                api_url=api_url,
                token_path=REMOTE_FAKE_YOKE_TOKEN_PATH,
            ),
        ]
    )
    setup = " && ".join(setup_commands)
    pid_name = f"apply_{log_name.replace('-', '_')}_pid"
    return (
        f"{setup}; "
        f"{yoke_server} >/tmp/yoke-apply-{shlex.quote(log_name)}-api.log 2>&1 & "
        f"{pid_name}=$!; "
        f"trap 'kill \"${pid_name}\" >/dev/null 2>&1 || true' EXIT; "
        f"sleep 1; {_onboard_command()}"
    )


def _project_apply_fake_yoke_local_apply_command(
    *,
    path: str,
    port: int,
    payload: Mapping[str, object],
    slug: str,
    github_repo: str,
    github_adoption: str,
    log_name: str,
) -> str:
    payload = _payload_with_board_data(payload, path=path)
    yoke_server = _fake_yoke_api_server_command(port=port, payload=payload)
    commands = [
        _project_meta_setup_command(path=path),
        _prepare_token_command(
            token_path=REMOTE_FAKE_YOKE_TOKEN_PATH,
            token_value=AUTH_FAKE_TOKEN_VALUE,
        ),
    ]
    args = [
        "onboard",
        "--non-interactive",
        "--quick",
        "--json",
        "--env",
        "stage",
        "--api-url",
        f"http://127.0.0.1:{port}",
        "--token-file",
        REMOTE_FAKE_YOKE_TOKEN_PATH,
        "--yes",
        "--skip-identity-check",
        "--project-mode",
        "local-checkout",
        "--checkout",
        path,
        "--project-slug",
        slug,
        "--project-name",
        slug.replace("-", " ").title(),
        "--github-repo",
        github_repo,
        "--default-branch",
        "main",
        "--public-item-prefix",
        "APL",
        "--github-adoption",
        github_adoption,
    ]
    setup = " && ".join(commands)
    pid_name = f"apply_{log_name.replace('-', '_')}_pid"
    return (
        f"{setup}; "
        f"{yoke_server} >/tmp/yoke-apply-{shlex.quote(log_name)}-api.log 2>&1 & "
        f"{pid_name}=$!; "
        f"trap 'kill \"${pid_name}\" >/dev/null 2>&1 || true' EXIT; "
        f"sleep 1; {_yoke_command(args)}"
    )


def _project_apply_conflict_checkout_command(path: str) -> str:
    quoted = shlex.quote(path)
    return f"mkdir -p {quoted} && printf '%s\\n' conflict > {quoted}/README.md"


def _project_apply_seed_resume_report_command(*, api_url: str, path: str) -> str:
    script = (
        "import json,pathlib,time\n"
        "home=pathlib.Path.home()/'.yoke'\n"
        "report_dir=home/'onboarding-runs'/'apply-reports'\n"
        "report_dir.mkdir(parents=True, exist_ok=True)\n"
        "run_id='run-apply-resume'\n"
        "config_path=str(home/'config.json')\n"
        f"checkout={path!r}\n"
        f"api_url={api_url!r}\n"
        "payload={\n"
        "  'schema':'yoke.onboard.apply-report',\n"
        "  'schema_version':1,\n"
        "  'run_id':run_id,\n"
        "  'created_at':'2026-07-04T00:00:00Z',\n"
        "  'updated_at':'2026-07-04T00:00:00Z',\n"
        "  'package_version':'recipe',\n"
        "  'config_path':config_path,\n"
        "  'env':'stage',\n"
        "  'api_url':api_url,\n"
        "  'checkout_path':checkout,\n"
        "  'source_repo':'',\n"
        "  'target_github_repo':'owner/apply-resume',\n"
        "  'credential_sources':{'yoke':{'kind':'file','path':'/tmp/yoke-fake-api.token'},'github_app':{'machine':{'kind':''},'project':{'adoption':'backlog-only','repo':'owner/apply-resume'}}},\n"
        "  'input_snapshot':{\n"
        "    'config_path':config_path,\n"
        "    'env_name':'stage',\n"
        "    'api_url':api_url,\n"
        "    'mode':'quick',\n"
        "    'check_identity':False,\n"
        "    'credential_sources':{'yoke':{'kind':'file','path':'/tmp/yoke-fake-api.token'},'github_app':{'machine':{'kind':''},'project':{'adoption':'backlog-only','repo':'owner/apply-resume'}}},\n"
        "    'machine_github':{'choice':'skip','api_url':'','authorization_source':{'kind':''}},\n"
        "    'project':{'mode':'local-checkout','remote_url':'','checkout':checkout,'slug':'apply-resume','name':'Apply Resume','org':'','github_repo':'owner/apply-resume','default_branch':'main','default_branch_source':'','public_item_prefix':'APL','existing_project_id':None,'existing_project_match_source':'','existing_project_local_source':'','github_adoption':'backlog-only','github_binding':{'adoption':'backlog-only','repo':'owner/apply-resume'},'keep_existing_remote':False,'publish':None,'clone':None},\n"
        "    'checkout_provenance':{'path':checkout,'project_mode':'local-checkout','existed_before_apply':True,'created_by_run':False,'safe_to_remove_on_start_over':False},\n"
        "  },\n"
        "  'steps':[\n"
        "    {'step_id':'00-create-or-validate-dir','action':'create-or-validate-dir','target':str(home),'label':'Create or validate Yoke home','status':'done','started_at':None,'finished_at':None,'error':None},\n"
        "    {'step_id':'01-project-onboard-local-checkout','action':'project-onboard-local-checkout','target':checkout,'label':'Use the local checkout','status':'failed','started_at':None,'finished_at':None,'error':'transient failure'},\n"
        "  ],\n"
        "  'final_status':'failed',\n"
        "  'failed_step':'01-project-onboard-local-checkout',\n"
        "  'error':'transient failure',\n"
        "  'resume_command':'yoke onboard --resume '+run_id,\n"
        "  'start_over_hint':'Re-run to redo setup: yoke onboard',\n"
        "  'secret_free':True,\n"
        "}\n"
        "path=report_dir/(run_id+'.json')\n"
        "path.write_text(json.dumps(payload, indent=2, sort_keys=True)+'\\n', encoding='utf-8')\n"
        "path.chmod(0o600)\n"
    )
    return " ".join(["python3", "-c", shlex.quote(script)])


def _yoke_command(args: Sequence[str]) -> str:
    yoke_bin = '"$HOME/.local/bin/yoke"'
    return " ".join([yoke_bin, *(shlex.quote(value) for value in args)])


def _project_source_dev_post_apply_command(
    *,
    yoke_port: int = PROJECT_SOURCE_DEV_FRESH_YOKE_API_PORT,
) -> str:
    yoke_api_url = f"http://127.0.0.1:{yoke_port}"
    yoke_server = _fake_yoke_api_server_command(
        port=yoke_port,
        payload=_fake_source_dev_yoke_payload(access=True),
    )
    args = [
        "onboard",
        "--non-interactive",
        "--quick",
        "--json",
        "--env",
        "stage",
        "--api-url",
        yoke_api_url,
        "--token-file",
        REMOTE_FAKE_YOKE_TOKEN_PATH,
        "--yes",
        "--skip-identity-check",
        "--project-mode",
        "source-dev-admin",
        "--checkout",
        PROJECT_SOURCE_DEV_FRESH_PATH,
        "--project-slug",
        "yoke",
        "--project-name",
        "Yoke",
        "--default-branch",
        "main",
        "--public-item-prefix",
        "YOK",
        "--github-adoption",
        "backlog-only",
    ]
    commands = [
        _project_source_dev_setup_command(),
        "command -v git >/dev/null || sudo dnf install -y git",
        _project_source_dev_seed_remote_command(),
        _project_source_dev_git_config_command(PROJECT_SOURCE_DEV_GIT_CONFIG_PATH),
        _prepare_token_command(
            token_path=REMOTE_FAKE_YOKE_TOKEN_PATH,
            token_value=AUTH_FAKE_TOKEN_VALUE,
        ),
        _machine_yoke_config_command(
            api_url=yoke_api_url,
            token_path=REMOTE_FAKE_YOKE_TOKEN_PATH,
        ),
    ]
    setup = " && ".join(commands)
    apply_command = (
        f"GIT_CONFIG_GLOBAL={shlex.quote(PROJECT_SOURCE_DEV_GIT_CONFIG_PATH)} "
        f"{_yoke_command(args)} > "
        f"{shlex.quote(PROJECT_SOURCE_DEV_APPLY_REPORT_PATH)}"
    )
    probe = _project_source_dev_post_apply_probe_command(
        PROJECT_SOURCE_DEV_FRESH_PATH,
        PROJECT_SOURCE_DEV_APPLY_REPORT_PATH,
    )
    return (
        f"{setup}; "
        f"{yoke_server} >/tmp/yoke-source-dev-api-{yoke_port}.log 2>&1 & "
        "source_dev_yoke_pid=$!; "
        'trap \'kill "$source_dev_yoke_pid" >/dev/null 2>&1 || true\' EXIT; '
        f"sleep 1; {apply_command} && {probe}"
    )


def _project_source_dev_seed_remote_command() -> str:
    script = (
        "import pathlib,subprocess,sys\n"
        "root=pathlib.Path(sys.argv[1])\n"
        "remote=pathlib.Path(sys.argv[2])\n"
        "source_link_module = r'''\n"
        "import json\n"
        "import os\n"
        "from pathlib import Path\n"
        "\n"
        "DEV_SYMLINKS = (\n"
        "    ('.claude/agents', '../runtime/harness/claude/agents'),\n"
        "    ('.claude/rules', '../runtime/harness/claude/rules'),\n"
        "    ('.claude/settings.json', '../runtime/harness/claude/settings.json'),\n"
        "    ('.claude/skills/yoke', '../../.agents/skills/yoke'),\n"
        "    ('.codex/agents', '../runtime/harness/codex/agents'),\n"
        "    ('.codex/hooks.json', '../runtime/harness/codex/hooks.json'),\n"
        "    (\n"
        "        'runtime/harness/claude/agents/references/yoke-tester-browser.md',\n"
        "        '../../../../agents/tester-browser.md',\n"
        "    ),\n"
        ")\n"
        "\n"
        "def _ensure_link(root, rel, target, actions, warnings):\n"
        "    path = root / rel\n"
        "    if path.is_symlink():\n"
        "        if os.readlink(path) == target:\n"
        "            actions.append(f'Exists: {rel} -> {target}')\n"
        "        else:\n"
        "            warnings.append(f'{rel} points at {os.readlink(path)}')\n"
        "        return\n"
        "    if path.exists():\n"
        "        warnings.append(f'{rel} exists and is not a symlink')\n"
        "        return\n"
        "    path.parent.mkdir(parents=True, exist_ok=True)\n"
        "    path.symlink_to(target)\n"
        "    actions.append(f'Created: {rel} -> {target}')\n"
        "\n"
        "def _write_hook(root, name, marker, command):\n"
        "    hook = root / '.git' / 'hooks' / name\n"
        "    if not hook.parent.is_dir():\n"
        "        return False\n"
        "    hook.write_text(\n"
        "        '#!/bin/sh\\n'\n"
        "        f'# {marker} hook installed by `yoke project install`\\n'\n"
        "        f'exec {command} \"$@\"\\n',\n"
        "        encoding='utf-8',\n"
        "    )\n"
        "    hook.chmod(0o755)\n"
        "    return True\n"
        "\n"
        "def install_source_link(repo_root, operation='install'):\n"
        "    root = Path(repo_root)\n"
        "    actions = []\n"
        "    warnings = []\n"
        "    for rel, target in DEV_SYMLINKS:\n"
        "        _ensure_link(root, rel, target, actions, warnings)\n"
        "    hooks = [\n"
        "        _write_hook(root, 'pre-commit', 'yoke-pre-commit', 'yoke git pre-commit'),\n"
        "        _write_hook(root, 'post-commit', 'yoke-post-commit', 'yoke git post-commit'),\n"
        "    ]\n"
        "    manifest = {\n"
        "        'manifest_schema': 1,\n"
        "        'yoke_version': 'source-dev-recipe',\n"
        "        'mode': 'source-link',\n"
        "        'symlinks': dict(DEV_SYMLINKS),\n"
        "        'git_hooks': ['pre-commit', 'post-commit'],\n"
        "        'contract_files': {},\n"
        "    }\n"
        "    manifest_path = root / '.yoke' / 'install-manifest.json'\n"
        "    manifest_path.parent.mkdir(parents=True, exist_ok=True)\n"
        "    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\\n', encoding='utf-8')\n"
        "    return {\n"
        "        'operation': operation,\n"
        "        'mode': 'source-link',\n"
        "        'repo_root': str(root),\n"
        "        'yoke_version': manifest['yoke_version'],\n"
        "        'source': 'in-checkout',\n"
        "        'symlinks_created': len(actions),\n"
        "        'symlinks_ok': 0,\n"
        "        'hooks_installed_or_updated': sum(1 for item in hooks if item),\n"
        "        'actions': actions,\n"
        "        'contract_files_written': 0,\n"
        "        'contract_files_existing': 0,\n"
        "        'contract_files_adopted': 0,\n"
        "        'manifest': str(manifest_path),\n"
        "        'machine_config_newly_registered': False,\n"
        "        'warnings': warnings,\n"
        "    }\n"
        "'''\n"
        "root.mkdir(parents=True,exist_ok=True)\n"
        "for package in ('yoke-contracts','yoke-core','yoke-cli','yoke-harness'):\n"
        "    package_root=root/'packages'/package\n"
        "    (package_root/'src').mkdir(parents=True,exist_ok=True)\n"
        "    (package_root/'pyproject.toml').write_text('[project]\\nname = \"' + package + '\"\\n',encoding='utf-8')\n"
        "    (package_root/'src'/'.gitkeep').write_text('',encoding='utf-8')\n"
        "module_root=root/'packages'/'yoke-core'/'src'/'yoke_core'\n"
        "(module_root/'domain').mkdir(parents=True,exist_ok=True)\n"
        "(module_root/'__init__.py').write_text('',encoding='utf-8')\n"
        "(module_root/'domain'/'__init__.py').write_text('',encoding='utf-8')\n"
        "(module_root/'domain'/'project_install_source_link.py').write_text(source_link_module,encoding='utf-8')\n"
        "for rel in ('runtime/harness/claude/agents','runtime/harness/claude/agents/references','runtime/harness/codex'):\n"
        "    folder=root/rel\n"
        "    folder.mkdir(parents=True,exist_ok=True)\n"
        "    (folder/'.gitkeep').write_text('',encoding='utf-8')\n"
        "(root/'.agents'/'skills'/'yoke').mkdir(parents=True,exist_ok=True)\n"
        "(root/'.agents'/'skills'/'yoke'/'SKILL.md').write_text('# Yoke skill\\n',encoding='utf-8')\n"
        "(root/'.agents'/'tester-browser.md').write_text('# Tester browser\\n',encoding='utf-8')\n"
        "(root/'pyproject.toml').write_text('[project]\\nname = \"yoke\"\\n',encoding='utf-8')\n"
        "subprocess.run(['git','-C',str(root),'init','-q','-b','main'],check=True)\n"
        "subprocess.run(['git','-C',str(root),'add','.'],check=True)\n"
        "subprocess.run(['git','-C',str(root),'-c','user.email=recipe@example.invalid','-c','user.name=Recipe','commit','-q','-m','init'],check=True)\n"
        "remote.parent.mkdir(parents=True,exist_ok=True)\n"
        "subprocess.run(['git','clone','--bare','-q',str(root),str(remote)],check=True)\n"
    )
    return " ".join(
        [
            "python3",
            "-c",
            shlex.quote(script),
            shlex.quote(PROJECT_SOURCE_DEV_SEED_PATH),
            shlex.quote(PROJECT_SOURCE_DEV_REMOTE_PATH),
        ]
    )


def _project_source_dev_git_config_command(config_path: str) -> str:
    quoted_config = shlex.quote(config_path)
    rewrite_key = f"url.{PROJECT_SOURCE_DEV_REMOTE_URL}.insteadOf"
    return " && ".join(
        [
            f"rm -f {quoted_config}",
            (
                f"git config --file {quoted_config} "
                "protocol.file.allow always"
            ),
            (
                f"git config --file {quoted_config} "
                f"{shlex.quote(rewrite_key)} "
                "https://github.com/upyoke/yoke.git"
            ),
        ]
    )


def _project_source_dev_post_apply_probe_command(
    checkout: str,
    report_path: str,
) -> str:
    script = (
        "import json,pathlib,subprocess,sys\n"
        "root=pathlib.Path(sys.argv[1])\n"
        "report_path=pathlib.Path(sys.argv[2])\n"
        "def require(ok,message):\n"
        "    if not ok:\n"
        "        raise SystemExit(message)\n"
        "report=json.loads(report_path.read_text(encoding='utf-8'))\n"
        "require(report.get('applied') is True,'onboard report was not applied')\n"
        "require((root/'pyproject.toml').is_file(),'missing pyproject.toml')\n"
        "require((root/'packages').is_dir(),'missing packages directory')\n"
        "require((root/'runtime').is_dir(),'missing runtime directory')\n"
        f"print({PROJECT_SOURCE_DEV_CHECKOUT_OK!r})\n"
        "inside=subprocess.check_output(['git','-C',str(root),'rev-parse','--is-inside-work-tree'],text=True).strip()\n"
        "require(inside == 'true','checkout is not a git work tree')\n"
        "head=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()\n"
        "require(len(head) >= 7,'git history is missing')\n"
        "origin=subprocess.check_output(['git','-C',str(root),'remote','get-url','origin'],text=True).strip()\n"
        "require(origin == 'https://github.com/upyoke/yoke.git','unexpected origin: '+origin)\n"
        f"print({PROJECT_SOURCE_DEV_GIT_OK!r})\n"
        "links=(\n"
        "    '.claude/agents',\n"
        "    '.claude/rules',\n"
        "    '.claude/settings.json',\n"
        "    '.claude/skills/yoke',\n"
        "    '.codex/agents',\n"
        "    '.codex/hooks.json',\n"
        "    'runtime/harness/claude/agents/references/yoke-tester-browser.md',\n"
        ")\n"
        "for rel in links:\n"
        "    require((root/rel).is_symlink(),'missing source-link symlink: '+rel)\n"
        f"print({PROJECT_SOURCE_DEV_LINKS_OK!r})\n"
        "manifest=json.loads((root/'.yoke'/'install-manifest.json').read_text(encoding='utf-8'))\n"
        "require(manifest.get('mode') == 'source-link','manifest mode is not source-link')\n"
        "manifest_links=manifest.get('symlinks') or {}\n"
        "for rel in links:\n"
        "    require(rel in manifest_links,'manifest missing symlink: '+rel)\n"
        f"print({PROJECT_SOURCE_DEV_MANIFEST_OK!r})\n"
        "for hook, marker in (('pre-commit','yoke-pre-commit'),('post-commit','yoke-post-commit')):\n"
        "    text=(root/'.git'/'hooks'/hook).read_text(encoding='utf-8')\n"
        "    require(marker in text,'missing hook marker: '+hook)\n"
        f"print({PROJECT_SOURCE_DEV_HOOKS_OK!r})\n"
        f"print({PROJECT_SOURCE_DEV_POST_APPLY_OK!r})\n"
    )
    return " ".join(
        [
            "python3",
            "-c",
            shlex.quote(script),
            shlex.quote(checkout),
            shlex.quote(report_path),
        ]
    )


def _project_source_dev_onboard_command(
    *,
    yoke_port: int = PROJECT_SOURCE_DEV_YOKE_API_PORT,
    yoke_payload: Mapping[str, object] | None = None,
    existing_dev_checkout: bool = False,
    conflict_dev_checkout: bool = False,
) -> str:
    yoke_api_url = f"http://127.0.0.1:{yoke_port}"
    yoke_server = _fake_yoke_api_server_command(
        port=yoke_port,
        payload=yoke_payload or _fake_source_dev_yoke_payload(access=True),
    )
    commands = [
        _project_source_dev_setup_command(
            existing_dev_checkout=existing_dev_checkout,
            conflict_dev_checkout=conflict_dev_checkout,
        ),
        _prepare_token_command(
            token_path=REMOTE_FAKE_YOKE_TOKEN_PATH,
            token_value=AUTH_FAKE_TOKEN_VALUE,
        ),
        _machine_yoke_config_command(
            api_url=yoke_api_url,
            token_path=REMOTE_FAKE_YOKE_TOKEN_PATH,
        ),
    ]
    setup = " && ".join(commands)
    return (
        f"{setup}; "
        f"{yoke_server} >/tmp/yoke-source-dev-api-{yoke_port}.log 2>&1 & "
        "source_dev_yoke_pid=$!; "
        'trap \'kill "$source_dev_yoke_pid" >/dev/null 2>&1 || true\' EXIT; '
        f"sleep 1; {_onboard_command()}"
    )


def _project_source_setup_command(
    *,
    existing_checkout: bool = False,
    conflict_checkout: bool = False,
    remote_branches: Mapping[str, str] | None = None,
) -> str:
    commands = [_project_source_cleanup_command()]
    if existing_checkout:
        commands.append(_project_source_existing_checkout_command())
    if conflict_checkout:
        commands.append(_project_source_conflict_checkout_command())
    for name, branch in sorted(dict(remote_branches or {}).items()):
        commands.append(_project_source_bare_remote_command(name=name, branch=branch))
    return " && ".join(commands)


def _project_source_dev_setup_command(
    *,
    existing_dev_checkout: bool = False,
    conflict_dev_checkout: bool = False,
) -> str:
    commands = [_project_source_cleanup_command()]
    if existing_dev_checkout:
        commands.append(_project_source_dev_existing_checkout_command())
    if conflict_dev_checkout:
        commands.append(_project_source_dev_conflict_checkout_command())
    return " && ".join(commands)


def _project_meta_setup_command(*, path: str = PROJECT_META_CHECKOUT_PATH) -> str:
    return " && ".join(
        [
            _project_source_cleanup_command(),
            _project_meta_checkout_command(path),
        ]
    )


def _project_source_cleanup_command() -> str:
    paths = [
        PROJECT_SOURCE_NEW_PATH,
        PROJECT_SOURCE_EXISTING_PATH,
        PROJECT_SOURCE_CONFLICT_PATH,
        PROJECT_SOURCE_CLONE_MAIN_PATH,
        PROJECT_SOURCE_CLONE_MASTER_PATH,
        PROJECT_SOURCE_DEV_FRESH_PATH,
        PROJECT_SOURCE_DEV_EXISTING_PATH,
        PROJECT_SOURCE_DEV_CONFLICT_PATH,
        PROJECT_SOURCE_DEV_DEFAULT_PATH,
        PROJECT_SOURCE_DEV_PUSH_PATH,
        PROJECT_META_CHECKOUT_PATH,
        PROJECT_META_CREATE_PATH,
        PROJECT_META_BOARD_DATA_FAIL_PATH,
        PROJECT_PUBLISH_LOCAL_PATH,
        APPLY_CREATE_PATH,
        APPLY_CLONE_PATH,
        APPLY_PROJECT_DENIED_PATH,
        APPLY_CLONE_CONFLICT_PATH,
        APPLY_BOARD_FAIL_PATH,
        APPLY_RESUME_PATH,
        APPLY_REPORT_AUDIT_PATH,
        APPLY_CTRL_C_PATH,
        "/tmp/yoke-project-source-seeds",
        "/tmp/yoke-project-source-remotes",
        "/tmp/yoke-project-source-dev-remotes",
    ]
    return "rm -rf " + " ".join(shlex.quote(path) for path in paths)


def _project_source_existing_checkout_command() -> str:
    path = shlex.quote(PROJECT_SOURCE_EXISTING_PATH)
    return (
        f"mkdir -p {path} && "
        f"git -C {path} init -q && "
        f"printf '%s\\n' project-source > {path}/README.md && "
        f"git -C {path} add README.md && "
        f"git -C {path} -c user.email=recipe@example.invalid "
        "-c user.name=Recipe commit -q -m init"
    )


def _project_source_conflict_checkout_command() -> str:
    path = shlex.quote(PROJECT_SOURCE_CONFLICT_PATH)
    return f"mkdir -p {path} && printf '%s\\n' occupied > {path}/README.md"


def _project_source_dev_existing_checkout_command() -> str:
    path = shlex.quote(PROJECT_SOURCE_DEV_EXISTING_PATH)
    origin = "https://github.com/upyoke/yoke.git"
    return (
        f"mkdir -p {path}/runtime/harness && "
        f"git -C {path} init -q -b main && "
        f"printf '%s\\n' '[project]' 'name = \"yoke\"' > {path}/pyproject.toml && "
        f"printf '%s\\n' source-dev > {path}/runtime/harness/README.md && "
        f"git -C {path} remote add origin {shlex.quote(origin)} && "
        f"git -C {path} add pyproject.toml runtime/harness/README.md && "
        f"git -C {path} -c user.email=recipe@example.invalid "
        "-c user.name=Recipe commit -q -m init"
    )


def _project_source_dev_conflict_checkout_command() -> str:
    path = shlex.quote(PROJECT_SOURCE_DEV_CONFLICT_PATH)
    return f"mkdir -p {path} && printf '%s\\n' 'not yoke' > {path}/README.md"


def _project_meta_checkout_command(path: str) -> str:
    quoted = shlex.quote(path)
    return (
        f"mkdir -p {quoted} && "
        f"git -C {quoted} init -q -b main && "
        f"printf '%s\\n' project-meta > {quoted}/README.md && "
        f"git -C {quoted} add README.md && "
        f"git -C {quoted} -c user.email=recipe@example.invalid "
        "-c user.name=Recipe commit -q -m init"
    )


def _project_source_bare_remote_command(*, name: str, branch: str) -> str:
    remote_path = _project_source_remote_path_for(name)
    seed_path = f"/tmp/yoke-project-source-seeds/{name}"
    quoted_seed = shlex.quote(seed_path)
    quoted_remote = shlex.quote(remote_path)
    quoted_branch = shlex.quote(branch)
    quoted_parent = shlex.quote(str(Path(remote_path).parent))
    return (
        f"mkdir -p {quoted_seed} {quoted_parent} && "
        f"git -C {quoted_seed} init -q -b {quoted_branch} && "
        f"printf '%s\\n' {shlex.quote(name)} > {quoted_seed}/README.md && "
        f"git -C {quoted_seed} add README.md && "
        f"git -C {quoted_seed} -c user.email=recipe@example.invalid "
        "-c user.name=Recipe commit -q -m init && "
        f"git clone --bare -q {quoted_seed} {quoted_remote}"
    )


def _project_source_remote_path_for(name: str) -> str:
    if name == "main-source":
        return PROJECT_SOURCE_MAIN_REMOTE_PATH
    if name == "master-source":
        return PROJECT_SOURCE_MASTER_REMOTE_PATH
    raise ValueError(f"unsupported project source remote: {name}")


def _prepare_token_command(*, token_path: str, token_value: str) -> str:
    quoted_path = shlex.quote(token_path)
    quoted_token = shlex.quote(token_value)
    return f"printf '%s\\n' {quoted_token} > {quoted_path} && chmod 600 {quoted_path}"


def _fake_yoke_api_server_command(
    *,
    port: int,
    payload: Mapping[str, object],
) -> str:
    script = (
        "import hashlib,http.server,json,socketserver,sys,time\n"
        "payload=json.loads(sys.argv[1])\n"
        "port=int(sys.argv[2])\n"
        "function_rows=payload.get('function_rows') or []\n"
        "function_errors=payload.get('function_errors') or {}\n"
        "function_delays=payload.get('function_delays') or {}\n"
        "board_data=payload.get('board_data') or {}\n"
        "board_data_by_scope=payload.get('board_data_by_scope') or {}\n"
        "project_template=payload.get('project') or {'id': 91, 'slug': 'recipe-meta', 'name': 'Recipe Meta', 'github_repo': 'recipe/meta', 'default_branch': 'main', 'public_item_prefix': 'REC'}\n"
        "def project_from_request(request_payload):\n"
        "    project=dict(project_template)\n"
        "    for key in ('slug','name','github_repo','default_branch','public_item_prefix'):\n"
        "        value=request_payload.get(key)\n"
        "        if value:\n"
        "            project[key]=value\n"
        "    project.setdefault('id', 91)\n"
        "    project.setdefault('slug', request_payload.get('slug') or 'recipe-meta')\n"
        "    project.setdefault('name', request_payload.get('name') or 'Recipe Meta')\n"
        "    project.setdefault('default_branch', request_payload.get('default_branch') or 'main')\n"
        "    project.setdefault('public_item_prefix', request_payload.get('public_item_prefix') or 'REC')\n"
        "    return project\n"
        "def install_bundle(project):\n"
        "    strategy_body='# Mission\\n\\nOperate this project through Yoke.\\n'\n"
        "    digest=hashlib.sha256(strategy_body.encode('utf-8')).hexdigest()\n"
        "    strategy='<!-- YOKE:STRATEGY-DOC slug=MISSION updated_at=2026-06-16T00:00:00Z content_sha256=' + digest + ' The Yoke DB is authoritative for this doc: edit the file, then write back with `yoke strategy ingest MISSION`. -->\\n' + strategy_body\n"
        "    bundle={'bundle_schema':1,'yoke_version':'9.9.9','project_id':int(project.get('id') or 91),'project_slug':project.get('slug') or 'recipe-meta','files':[{'path':'.codex/skills/yoke/onboard-project/SKILL.md','content':'# onboard-project\\n'}],'project_contract_files':[{'path':'.yoke/lint-config','content':'lint_main_commit=deny\\n','install_policy':'seed_if_missing','category':'project_policy'}],'strategy_files':[{'path':'.yoke/strategy/MISSION.md','content':strategy,'install_policy':'db_render'}],'hooks':{}}\n"
        "    if payload.get('install_bundle_board_art_conflict'):\n"
        "        bundle['project_contract_files'].append({'path':'.yoke/board-art/sentinel','content':'conflict\\n','install_policy':'seed_if_missing','category':'project_policy'})\n"
        "    return bundle\n"
        "class Handler(http.server.BaseHTTPRequestHandler):\n"
        "    def _send(self,status,payload_obj):\n"
        "        body=json.dumps(payload_obj).encode('utf-8')\n"
        "        self.send_response(status)\n"
        "        self.send_header('Content-Type','application/json')\n"
        "        self.send_header('Content-Length',str(len(body)))\n"
        "        self.end_headers()\n"
        "        self.wfile.write(body)\n"
        "    def do_GET(self):\n"
        "        if self.path.startswith('/v1/projects/') and self.path.endswith('/install-bundle'):\n"
        "            self._send(200, install_bundle(project_template)); return\n"
        "        self._send(200, payload)\n"
        "    def do_POST(self):\n"
        "        length=int(self.headers.get('Content-Length','0') or '0')\n"
        "        raw=self.rfile.read(length).decode('utf-8')\n"
        "        try:\n"
        "            request=json.loads(raw) if raw else {}\n"
        "        except ValueError:\n"
        "            request={}\n"
        "        function=str(request.get('function') or '')\n"
        "        response={'success': True, 'function': function, 'version': request.get('version') or 'v1', 'request_id': request.get('request_id'), 'result': {}, 'warnings': [], 'event_ids': []}\n"
        "        if function in function_delays:\n"
        "            try:\n"
        "                time.sleep(float(function_delays.get(function) or 0))\n"
        "            except Exception:\n"
        "                pass\n"
        "        if function in function_errors:\n"
        "            error=function_errors.get(function) or {}\n"
        "            self._send(200, {'success': False, 'function': function, 'version': request.get('version') or 'v1', 'request_id': request.get('request_id'), 'result': {}, 'warnings': [], 'event_ids': [], 'error': {'code': error.get('code') or 'error', 'message': error.get('message') or function}}); return\n"
        "        if function == 'projects.list':\n"
        "            response['result']={'rows': function_rows}\n"
        "            self._send(200, response); return\n"
        "        if function == 'projects.get':\n"
        "            response['result']={'row': project_template, 'project': project_template}\n"
        "            self._send(200, response); return\n"
        "        if function == 'projects.resolve_by_github_repo':\n"
        "            response['result']={'row': project_template}\n"
        "            self._send(200, response); return\n"
        "        if function == 'projects.create':\n"
        "            payload_obj=request.get('payload') or {}\n"
        "            response['result']={'project': project_from_request(payload_obj)}\n"
        "            self._send(200, response); return\n"
        "        if function == 'projects.capability_secret.set':\n"
        "            payload_obj=request.get('payload') or {}\n"
        "            response['result']={'project': payload_obj.get('project'), 'cap_type': payload_obj.get('cap_type'), 'key': payload_obj.get('key'), 'source': payload_obj.get('source') or 'literal', 'stored': True}\n"
        "            self._send(200, response); return\n"
        "        if function == 'onboard.checklist.run':\n"
        "            payload_obj=request.get('payload') or {}\n"
        "            response['result']={'schema_version': 1, 'operation': function, 'run_id': payload_obj.get('run_id') or 'run-handoff', 'resumed': False, 'branch': payload_obj.get('branch'), 'project_id': payload_obj.get('project_id'), 'checkout_path': payload_obj.get('checkout_path'), 'github_repo': payload_obj.get('github_repo'), 'status': 'open', 'rows': [], 'summary': {'status': 'open'}}\n"
        "            self._send(200, response); return\n"
        "        if function == 'project.snapshot.sync':\n"
        "            response['result']={'snapshots': [{'status': 'created', 'ref': 'HEAD', 'commit_sha': 'abc123', 'snapshot_id': 99}], 'warnings': []}\n"
        "            self._send(200, response); return\n"
        "        if function == 'board.data.get':\n"
        "            payload_obj=request.get('payload') or {}\n"
        "            scope=str(payload_obj.get('scope') or '')\n"
        "            response['result']=board_data_by_scope.get(scope) or board_data\n"
        "            self._send(200, response); return\n"
        "        self._send(200, {'success': False, 'function': function, 'version': request.get('version') or 'v1', 'request_id': request.get('request_id'), 'result': {}, 'warnings': [], 'event_ids': [], 'error': {'code': 'unsupported_fake_function', 'message': function}})\n"
        "    def log_message(self,*args):\n"
        "        return\n"
        "class ReuseServer(socketserver.TCPServer):\n"
        "    allow_reuse_address=True\n"
        "with ReuseServer(('127.0.0.1', port), Handler) as httpd:\n"
        "    httpd.serve_forever()\n"
    )
    return " ".join(
        [
            "python3",
            "-c",
            shlex.quote(script),
            shlex.quote(json_helper.dumps_compact(dict(payload))),
            shlex.quote(str(port)),
        ]
    )



def _fake_success_identity_payload() -> dict[str, object]:
    return {
        "checked": True,
        "ok": True,
        "status": "verified",
        "source": "identity",
        "actor": {"label": "recipe actor"},
        "orgs": [{"name": "recipe-org", "roles": ["owner"]}],
        "projects": [{"name": "recipe-project", "roles": ["admin"]}],
    }


def _fake_state_yoke_payload(
    *,
    project_id: int,
    function_errors: Mapping[str, object] | None = None,
) -> dict[str, object]:
    project = {
        "id": int(project_id),
        "slug": "state-project-one",
        "name": "State Project One",
        "github_repo": "state/project-one",
        "default_branch": "main",
        "public_item_prefix": "STA",
    }
    return {
        "checked": True,
        "ok": True,
        "status": "verified",
        "source": "identity",
        "actor": {"label": "stored-state recipe actor"},
        "orgs": [{"name": "recipe-org", "roles": ["owner"]}],
        "projects": [{"name": project["name"], "roles": ["admin"]}],
        "project": project,
        "function_rows": [project],
        "function_errors": dict(function_errors or {}),
    }


def _fake_no_access_identity_payload() -> dict[str, object]:
    return {
        "checked": True,
        "ok": True,
        "status": "verified",
        "source": "identity",
        "actor": {"label": "no-access actor"},
        "orgs": [],
        "projects": [],
    }


def _fake_many_access_identity_payload() -> dict[str, object]:
    return {
        "checked": True,
        "ok": True,
        "status": "verified",
        "source": "identity",
        "actor": {"label": "many-access actor"},
        "orgs": [
            {"name": "o1", "roles": ["owner"]},
            {"name": "o2", "roles": ["viewer"]},
            {"name": "o3", "roles": ["operator"]},
            {"name": "o4", "roles": ["viewer"]},
            {"name": "o5", "roles": ["viewer"]},
            {"name": "o6", "roles": ["viewer"]},
        ],
        "projects": [
            {"name": "p1", "roles": ["admin"]},
            {"name": "p2", "roles": ["viewer"]},
            {"name": "p3", "roles": ["operator"]},
            {"name": "p4", "roles": ["viewer"]},
            {"name": "p5", "roles": ["viewer"]},
            {"name": "p6", "roles": ["viewer"]},
        ],
    }


def _fake_source_dev_yoke_payload(*, access: bool) -> dict[str, object]:
    project = (
        {"id": 1, "slug": "yoke", "name": "Yoke", "roles": ["admin"]}
        if access
        else {"id": 2, "slug": "other", "name": "Other project", "roles": ["viewer"]}
    )
    rows = [{"id": 1, "slug": "yoke", "name": "Yoke"}] if access else []
    return {
        "checked": True,
        "ok": True,
        "status": "verified",
        "source": "identity",
        "actor": {"label": "source-dev recipe actor"},
        "orgs": [{"name": "recipe-org", "roles": ["owner"]}],
        "projects": [project],
        "function_rows": rows,
    }


def _fake_project_meta_board_data_failure_payload() -> dict[str, object]:
    return {
        "checked": True,
        "ok": True,
        "status": "verified",
        "source": "identity",
        "actor": {"label": "project-meta recipe actor"},
        "orgs": [{"name": "recipe-org", "roles": ["owner"]}],
        "projects": [],
        "function_errors": {
            "board.data.get": {
                "code": "board_data_unavailable",
                "message": "board data unavailable for recipe",
            },
        },
    }


def _fake_publish_yoke_payload() -> dict[str, object]:
    return {
        "checked": True,
        "ok": True,
        "status": "verified",
        "source": "identity",
        "actor": {"label": "project-publish recipe actor"},
        "orgs": [{"name": "recipe-org", "roles": ["owner"]}],
        "projects": [],
    }


def _fake_apply_yoke_payload(
    *,
    function_errors: Mapping[str, object] | None = None,
    function_delays: Mapping[str, object] | None = None,
    board_art_conflict: bool = False,
) -> dict[str, object]:
    return {
        "checked": True,
        "ok": True,
        "status": "verified",
        "source": "identity",
        "actor": {"label": "apply recipe actor"},
        "orgs": [{"name": "recipe-org", "roles": ["owner"]}],
        "projects": [],
        "project": {
            "id": 91,
            "slug": "apply-recipe",
            "name": "Apply Recipe",
            "github_repo": "owner/apply-recipe",
            "default_branch": "main",
            "public_item_prefix": "APL",
        },
        "function_errors": dict(function_errors or {}),
        "function_delays": dict(function_delays or {}),
        "install_bundle_board_art_conflict": board_art_conflict,
    }


class _EmptyBoardDataDB:
    def query(self, sql, params=None):  # noqa: ANN001, ANN201
        del sql, params
        return []

    def query_quiet(self, sql, params=None):  # noqa: ANN001, ANN201
        del sql, params
        return []

    def scalar(self, sql, params=None):  # noqa: ANN001, ANN201
        del sql, params
        return 0


def _payload_with_board_data(
    payload: Mapping[str, object],
    *,
    path: str,
) -> dict[str, object]:
    enriched = dict(payload)
    project = enriched.get("project")
    project_id = 91
    if isinstance(project, Mapping):
        project_id = int(project.get("id") or project_id)
    scopes = ("all", "yoke", str(project_id))
    board_data_by_scope = {
        scope: _empty_board_data_payload(repo_root=path, scope=scope)
        for scope in scopes
    }
    enriched["board_data_by_scope"] = board_data_by_scope
    if "board_data" not in enriched:
        enriched["board_data"] = board_data_by_scope[str(project_id)]
    return enriched


def _empty_board_data_payload(
    *,
    repo_root: str,
    scope: str = "yoke",
) -> dict[str, object]:
    from yoke_contracts.board.config import parse_config
    from yoke_core.board.data import collect_board_data

    config = parse_config(None, repo_root=repo_root)
    return collect_board_data(
        _EmptyBoardDataDB(),
        scope=scope,
        config=config,
        repo_root=repo_root,
        vision_entries=[],
    )



def _path_fix_expected_text() -> list[str]:
    return [
        "Add Yoke to your PATH.",
        "Added Yoke to your PATH.",
        "Wrote the managed block",
        "Checked a fresh login shell:",
        "Your next terminal will find Yoke.",
    ]


def _plain_glyph_post_checks() -> list[str]:
    unsafe = "☀✓✔✗●○◐⊘›•→▌─│┃━═—–…↵↑↓·"
    return ["secret_free", *(f"no_text:{glyph}" for glyph in unsafe)]


def _local_prod_token_path() -> str:
    configured = os.environ.get(PROD_TOKEN_FILE_ENV, "~/.yoke/secrets/prod.token")
    return str(Path(configured).expanduser())


def _install_env_prefix(
    base_url: str,
    *,
    env: Mapping[str, str] | None = None,
) -> str:
    command_env = {
        "YOKE_INSTALL_BASE_URL": base_url.rstrip("/"),
        "YOKE_CHANNEL": "latest",
        **dict(env or {}),
    }
    return " ".join(
        f"{key}={shlex.quote(value)}" for key, value in sorted(command_env.items())
    )


def _launch_command_hint(scenario: harness.Scenario, base_url: str) -> str:
    profile = scenario.host_profile
    if profile.startswith("bare") or scenario.scenario_id.startswith("INSTALL-"):
        return (
            f"curl -fsSL {base_url}/install -o /tmp/yoke-install && "
            f"YOKE_INSTALL_BASE_URL={base_url} YOKE_CHANNEL=latest "
            "sh /tmp/yoke-install"
        )
    return "TERM=xterm-256color yoke onboard"


def _load_optional_recipe(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    payload = json_helper.load_path(path)
    if not isinstance(payload, dict):
        raise ValueError(f"recipe root must be a JSON object: {path}")
    return payload


def _load_recipe(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise ValueError(f"recipe JSON is missing: {path}")
    return _load_optional_recipe(path)


def _assigned_host_entries(host_plan: Mapping[str, object]) -> list[dict[str, object]]:
    return [item for item in host_plan.get("assigned", []) if isinstance(item, dict)]


def _recipe_compile_blocker(
    recipe: Mapping[str, object],
    *,
    recipe_path: Path,
    assignment_id: str,
    scenario_id: str,
) -> dict[str, object] | None:
    if recipe.get("status") != READY_RECIPE_STATUS:
        return {
            "assignment_id": assignment_id,
            "scenario_id": scenario_id,
            "recipe_path": str(recipe_path),
            "reason": str(
                recipe.get("blocked_reason")
                or "exact key/action recipe is not authored"
            ),
        }
    if str(recipe.get("scenario_id") or scenario_id) != scenario_id:
        return {
            "assignment_id": assignment_id,
            "scenario_id": scenario_id,
            "recipe_path": str(recipe_path),
            "reason": "recipe scenario_id does not match assignment scenario",
        }
    if not str(recipe.get("command") or "").strip():
        return {
            "assignment_id": assignment_id,
            "scenario_id": scenario_id,
            "recipe_path": str(recipe_path),
            "reason": "ready recipe is missing command",
        }
    try:
        _actions_from_spec(recipe.get("actions", []))
        stage_files = _stage_files_from_spec(recipe.get("stage_files", []))
        _validate_local_stage_sources(stage_files)
    except ValueError as exc:
        return {
            "assignment_id": assignment_id,
            "scenario_id": scenario_id,
            "recipe_path": str(recipe_path),
            "reason": str(exc),
        }
    return None


def _validate_local_stage_sources(stage_files: Sequence[Mapping[str, object]]) -> None:
    for item in stage_files:
        source_path = str(item.get("source_path") or "").strip()
        if not source_path:
            continue
        path = Path(source_path).expanduser()
        if not path.is_file():
            raise ValueError(f"stage source_path is not readable: {path}")


def _run_from_recipe(
    recipe: Mapping[str, object],
    *,
    assignment_id: str,
    scenario_id: str,
    host_id: str,
    host_profile: str,
) -> dict[str, object]:
    run: dict[str, object] = {
        "assignment_id": assignment_id,
        "scenario_id": scenario_id,
        "host_id": host_id,
        "command": str(recipe["command"]),
        "actions": _json_actions(recipe.get("actions", [])),
        "expected_text": [str(value) for value in recipe.get("expected_text", [])],
        "post_checks": [str(value) for value in recipe.get("post_checks", [])],
        "stage_files": _stage_files_from_spec(recipe.get("stage_files", [])),
        "execution_mode": str(recipe.get("execution_mode") or "tmux"),
        "expected_return_codes": [
            int(value) for value in recipe.get("expected_return_codes", [0])
        ],
        "pane": str(recipe.get("pane") or DEFAULT_PANE),
        "start_delay": float(recipe.get("start_delay", 3.0)),
        "step_delay": float(recipe.get("step_delay", 0.5)),
        "max_wall_seconds": float(
            recipe.get("max_wall_seconds", scenario_runner.DEFAULT_MAX_WALL_SECONDS)
        ),
    }
    reset_profile = str(recipe.get("reset_profile") or _reset_profile_for(host_profile))
    if reset_profile:
        run["reset_profile"] = reset_profile
    return run


def _json_actions(raw_actions: object) -> list[dict[str, object]]:
    actions = _actions_from_spec(raw_actions)
    serialized = []
    for action in actions:
        item: dict[str, object] = {
            "step": action.step,
            "keys": list(action.keys),
        }
        if not action.capture:
            item["capture"] = False
        serialized.append(item)
    return serialized


def _stage_files_from_spec(raw_stage_files: object) -> list[dict[str, object]]:
    if raw_stage_files in (None, ""):
        return []
    if not isinstance(raw_stage_files, list):
        raise ValueError("stage_files must be a list")
    stage_files = []
    for raw in raw_stage_files:
        if not isinstance(raw, dict):
            raise ValueError("stage_files entries must be objects")
        remote_path = str(raw.get("remote_path") or "").strip()
        source_path = str(raw.get("source_path") or "").strip()
        source_url = str(raw.get("source_url") or "").strip()
        if not remote_path:
            raise ValueError("stage_files entries need remote_path")
        if bool(source_path) == bool(source_url):
            raise ValueError(
                "stage_files entries need exactly one of source_path or source_url"
            )
        item: dict[str, object] = {"remote_path": remote_path}
        if source_path:
            item["source_path"] = source_path
        if source_url:
            item["source_url"] = source_url
        stage_files.append(item)
    return stage_files


def _reset_profile_for(host_profile: str) -> str:
    if host_profile in fleet.RESETTABLE_PROFILES:
        return host_profile
    return ""


def _write_run_specs(
    *,
    campaign_root: Path,
    ledger_path: str,
    spec_dir: Path,
    runs: Sequence[dict[str, object]],
    runs_per_spec: int,
) -> list[Path]:
    spec_dir.mkdir(parents=True, exist_ok=True)
    for stale_path in spec_dir.glob("run-spec-*.json"):
        stale_path.unlink()
    paths = []
    for index, offset in enumerate(range(0, len(runs), runs_per_spec), start=1):
        chunk = runs[offset : offset + runs_per_spec]
        path = spec_dir / f"run-spec-{index:03d}.json"
        json_helper.dump_path(
            path,
            {
                "campaign_root": str(campaign_root),
                "ledger": ledger_path,
                "runs": list(chunk),
            },
        )
        paths.append(path)
    return paths


def _load_run_spec(path: Path) -> dict[str, object]:
    payload = json_helper.load_path(path)
    if not isinstance(payload, dict):
        raise ValueError(f"run spec root must be a JSON object: {path}")
    return payload


def _load_spec_paths(
    spec_dir: Path,
    *,
    max_specs: int | None,
) -> list[Path]:
    paths = sorted(spec_dir.glob("*.json"))
    if max_specs is not None:
        if max_specs < 1:
            raise ValueError("max_specs must be at least 1")
        paths = paths[:max_specs]
    if not paths:
        raise ValueError(f"no run spec JSON files found under {spec_dir}")
    return paths


def _spec_runs(spec: Mapping[str, object]) -> list[dict[str, object]]:
    runs = [item for item in spec.get("runs", []) if isinstance(item, dict)]
    if not runs:
        raise ValueError("run spec must contain at least one run")
    normalized = []
    for item in runs:
        assignment_id = str(item.get("assignment_id") or "")
        scenario_id = str(item.get("scenario_id") or "")
        host_id = str(item.get("host_id") or "")
        command = str(item.get("command") or "")
        if not assignment_id or not scenario_id or not host_id or not command:
            raise ValueError(
                "each run needs assignment_id, scenario_id, host_id, and command"
            )
        normalized.append(
            {
                **item,
                "assignment_id": assignment_id,
                "scenario_id": scenario_id,
                "host_id": host_id,
                "command": command,
                "actions": _actions_from_spec(item.get("actions", [])),
                "expected_text": [
                    str(value) for value in item.get("expected_text", [])
                ],
                "stage_files": _stage_files_from_spec(item.get("stage_files", [])),
                "post_checks": [str(value) for value in item.get("post_checks", [])],
                "execution_mode": str(item.get("execution_mode") or "tmux"),
                "expected_return_codes": [
                    int(value) for value in item.get("expected_return_codes", [0])
                ],
                "pane": str(item.get("pane") or DEFAULT_PANE),
                "start_delay": float(item.get("start_delay", 3.0)),
                "step_delay": float(item.get("step_delay", 0.5)),
                "max_wall_seconds": float(
                    item.get(
                        "max_wall_seconds",
                        scenario_runner.DEFAULT_MAX_WALL_SECONDS,
                    )
                ),
            }
        )
    return normalized


def _actions_from_spec(raw_actions: object) -> list[scenario_runner.ScenarioAction]:
    if not isinstance(raw_actions, list) or not raw_actions:
        raise ValueError("each run needs at least one action")
    actions = []
    for raw in raw_actions:
        if isinstance(raw, str):
            actions.append(scenario_runner.parse_action(raw))
            continue
        if isinstance(raw, dict):
            step = str(raw.get("step") or "")
            keys = tuple(str(key) for key in raw.get("keys", []))
            capture = bool(raw.get("capture", True))
            if not step:
                raise ValueError("action step is required")
            actions.append(scenario_runner.ScenarioAction(step, keys, capture))
            continue
        raise ValueError("actions must be strings or objects")
    return actions


def _run_one(
    item: Mapping[str, object],
    *,
    campaign_root: Path,
    ledger_path: Path,
    runner: scenario_runner.capture_tool.CommandRunner,
    sleeper,  # noqa: ANN001
) -> dict[str, object]:
    try:
        reset_profile = str(item.get("reset_profile") or "")
        if reset_profile:
            fleet.reset_fleet_host(
                ledger_path=ledger_path,
                host_id=str(item["host_id"]),
                target_profile=reset_profile,
                runner=runner,
            )
        result = scenario_runner.run_remote_sequence(
            ledger_path=ledger_path,
            campaign_root=campaign_root,
            assignment_id=str(item["assignment_id"]),
            scenario_id=str(item["scenario_id"]),
            command=str(item["command"]),
            actions=item["actions"],  # type: ignore[arg-type]
            expected_text=item["expected_text"],  # type: ignore[arg-type]
            post_checks=item["post_checks"],  # type: ignore[arg-type]
            stage_files=item["stage_files"],  # type: ignore[arg-type]
            execution_mode=str(item["execution_mode"]),
            expected_return_codes=item["expected_return_codes"],  # type: ignore[arg-type]
            host_id=str(item["host_id"]),
            pane=str(item["pane"]),
            start_delay=float(item["start_delay"]),
            step_delay=float(item["step_delay"]),
            max_wall_seconds=float(item["max_wall_seconds"]),
            runner=runner,
            sleeper=sleeper,
        )
        return asdict(result)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "assignment_id": str(item.get("assignment_id") or ""),
            "scenario_id": str(item.get("scenario_id") or ""),
            "host_id": str(item.get("host_id") or ""),
            "overall_result": "fail",
            "failure": str(exc),
        }


def _write_summary(campaign_root: Path, payload: Mapping[str, object]) -> Path:
    path = campaign_root / "summaries" / f"coordinator-{_summary_stamp()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    json_helper.dump_path(path, dict(payload))
    return path


def _write_wave_summary(campaign_root: Path, payload: Mapping[str, object]) -> Path:
    path = campaign_root / "summaries" / f"coordinator-waves-{_summary_stamp()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    json_helper.dump_path(path, dict(payload))
    return path


def _campaign_root_from_batch_results(
    results: Sequence[Mapping[str, object]],
) -> Path | None:
    for result in results:
        root = str(result.get("campaign_root") or "").strip()
        if root:
            return Path(root)
    return None


def _campaign_root_from_spec_dir(spec_dir: Path) -> Path | None:
    if spec_dir.name == DEFAULT_RUN_SPECS_DIR:
        return spec_dir.parent
    return None


def _summary_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


if __name__ == "__main__":
    raise SystemExit(main())
