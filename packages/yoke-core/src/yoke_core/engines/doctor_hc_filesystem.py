"""Filesystem checks for paths, scratch, config, size, and test commands."""

from __future__ import annotations

import re
from pathlib import Path
from typing import List

from yoke_core.domain.strategy_docs_paths import strategy_view_path

from yoke_core.domain import machine_config
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.scratch_auto_prune import prune_stale_scratch

import yoke_core.engines.doctor_report as _base

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)


def hc_path_confabulation(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-path-confabulation: Path confabulation detection."""
    issues: List[str] = []
    repo_root = _base._resolve_repo_root()
    if repo_root:
        # Check filesystem for confabulated directories
        if Path(repo_root, "ouraboros").is_dir():
            issues.append("- Confabulated directory found: ouraboros/ (should be ouroboros/)")
        if Path(repo_root, "runtime", "runtime").is_dir():
            issues.append("- Confabulated directory found: runtime/runtime/ (prefix doubling)")

    # Scan ouroboros_entries DB
    if _base._table_exists(conn, "ouroboros_entries"):
        if _base._column_exists(conn, "ouroboros_entries", "reviewed_at") and \
           _base._column_exists(conn, "ouroboros_entries", "archived_at"):
            rows = query_rows(
                conn,
                "SELECT id, body FROM ouroboros_entries "
                "WHERE reviewed_at IS NULL AND archived_at IS NULL",
            )
        else:
            rows = query_rows(conn, "SELECT id, body FROM ouroboros_entries")
        confab_re = re.compile(r"ouraboros|yoke/yoke/|runtime/runtime/")
        for row in rows:
            body = row["body"] or ""
            if "<!-- not-confabulated -->" in body:
                continue
            for line in body.splitlines():
                if confab_re.search(line) and "<!-- not-confabulated -->" not in line:
                    issues.append(f"- Confabulated path in ouroboros_entries[{row['id']}]")
                    break

    # Scan working note files
    if repo_root:
        for note_path in [
            Path(repo_root, "ouroboros", "patterns.md"),
            strategy_view_path(repo_root, "PAD"),
        ]:
            if not note_path.is_file():
                continue
            try:
                content = note_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            confab_re = re.compile(r"ouraboros|yoke/yoke/|runtime/runtime/")
            for i, line in enumerate(content.splitlines(), 1):
                if confab_re.search(line) and "<!-- not-confabulated -->" not in line:
                    issues.append(
                        f"- Confabulated path in {note_path.name}:{i}"
                    )
                    break

    if issues:
        rec.record("HC-path-confabulation", "Path confabulation", "WARN", "\n".join(issues))
    else:
        rec.record("HC-path-confabulation", "Path confabulation", "PASS", "")



def hc_orphaned_temp_files(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """Scan global scratch while protecting current and active sessions."""
    outcome = prune_stale_scratch(conn, fix=args.fix)
    result = (
        "FAIL"
        if outcome.failure_count
        else "WARN"
        if outcome.stale_count
        else "PASS"
    )
    rec.record(
        "HC-orphaned-temp-files",
        "Orphaned temp files",
        result,
        "\n".join(outcome.issues),
    )


def hc_config_validation(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-config-validation: Machine config validation."""
    config_path = machine_config.config_path()

    issues: List[str] = []
    if not config_path.is_file():
        issues.append(f"- machine config not found: {config_path}")
    else:
        try:
            payload = machine_config.load_config(config_path)
        except machine_config.MachineConfigError as exc:
            issues.append(f"- machine config invalid: {exc}")
        else:
            settings = payload.get("settings", {})
            if settings is not None and not isinstance(settings, dict):
                issues.append("- machine config settings must be an object")
            projects = payload.get("projects", [])
            if projects is not None and not isinstance(projects, (list, dict)):
                issues.append("- machine config projects must be a list of entries")
            # Deploy preflights resolve project checkouts from these entries,
            # so a dead path (for example a since-removed worktree) silently
            # breaks every run that consults the project repository.
            entries = projects if isinstance(projects, list) else []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                checkout = entry.get("checkout")
                if not isinstance(checkout, str) or not checkout:
                    continue
                if not (Path(checkout).expanduser() / ".git").exists():
                    issues.append(
                        "- projects entry (project_id="
                        f"{entry.get('project_id')} env={entry.get('env')}) "
                        f"checkout missing or not a git checkout: {checkout} "
                        "— repair or remove this entry; deploy preflights "
                        "resolve project checkouts from it"
                    )

    if issues:
        rec.record("HC-config-validation", "Machine config validation", "WARN", "\n".join(issues))
    else:
        rec.record("HC-config-validation", "Machine config validation", "PASS", "")



def hc_size_bloat(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-size-bloat: Size/bloat monitor."""
    repo_root = _base._resolve_repo_root()
    if not repo_root:
        rec.record("HC-size-bloat", "Size/bloat monitor", "PASS", "")
        return

    data_root = Path(repo_root) / "data"
    issues: List[str] = []

    # Check DB file size
    db_path = data_root / "yoke.db"
    if db_path.is_file():
        size_mb = db_path.stat().st_size / (1024 * 1024)
        if size_mb > 100:
            issues.append(f"- yoke.db is {size_mb:.1f}MB (>100MB threshold)")
        elif size_mb > 50:
            issues.append(f"- yoke.db is {size_mb:.1f}MB (>50MB warning)")

    # Check .git size
    git_dir = Path(repo_root) / ".git"
    if git_dir.is_dir():
        try:
            r = _base._run(["du", "-sk", str(git_dir)], timeout=10)
            if r.returncode == 0 and r.stdout.strip():
                size_kb = int(r.stdout.split()[0])
                if size_kb > 500000:  # 500MB
                    issues.append(f"- .git directory is {size_kb // 1024}MB (>500MB)")
        except Exception:
            pass

    if issues:
        rec.record("HC-size-bloat", "Size/bloat monitor", "WARN", "\n".join(issues))
    else:
        rec.record("HC-size-bloat", "Size/bloat monitor", "PASS", "")



def hc_test_command_validity(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-test-command-validity: Test command validity for projects.

    delegates to ``yoke_core.domain.projects._validate_test_command``
    so the doctor warning matches the CLI validator shipped to agents and
    dispatch surfaces.  A configured but unresolvable command now produces an
    actionable WARN instead of a silent PASS.
    """
    if not _base._table_exists(conn, "projects"):
        rec.record("HC-test-command-validity", "Test command validity", "PASS", "")
        return

    # Imported lazily to avoid a hard import cycle between doctor.py and
    # projects.py during module import.
    from yoke_core.domain import command_definitions as _cmd_defs
    from yoke_core.domain.projects import _validate_test_command
    from yoke_core.domain.project_checkout_locations import checkout_for_project_id

    rows = query_rows(
        conn,
        "SELECT id, slug FROM projects ORDER BY id",
    )

    issues: List[str] = []
    for row in rows:
        project_id = row["id"]
        project_slug = row["slug"]
        checkout = checkout_for_project_id(int(project_id))
        repo_path = str(checkout) if checkout is not None else ""

        commands = _cmd_defs.list_commands(project_id, db_path=args.db_path)
        if not commands:
            # Nothing configured — nothing to validate.
            continue

        if not repo_path:
            for scope in commands:
                issues.append(
                    f"{project_slug}.{scope}: no machine-local checkout mapping"
                )
            continue

        if not Path(repo_path).is_dir():
            for scope in commands:
                issues.append(
                    f"{project_slug}.{scope}: mapped checkout not a directory: {repo_path}"
                )
            continue

        for scope, command in commands.items():
            result = _validate_test_command(scope, command, repo_path)
            if result.status == "invalid":
                issues.append(f"{project_slug}.{scope}: {result.detail}")

    if issues:
        rec.record(
            "HC-test-command-validity",
            "Test command validity",
            "WARN",
            "\n".join(issues),
        )
    else:
        rec.record("HC-test-command-validity", "Test command validity", "PASS", "")
