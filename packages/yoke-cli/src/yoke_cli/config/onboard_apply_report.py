"""Durable apply reports for ``yoke onboard`` runs."""

from __future__ import annotations

import os
import re
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from yoke_cli.config import onboard_apply_snapshot
from yoke_cli.config import onboard_checklist
from yoke_cli.config.onboard_plan_labels import friendly_line

SCHEMA_NAME = "yoke.onboard.apply-report"
SCHEMA_VERSION = 1
REPORTS_DIR_NAME = "apply-reports"

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"

# Re-entry command surfaced on the failure screen and shell summary.
RESUME_COMMAND = "yoke onboard"

_AUTH_HEADER_RE = re.compile(r"(Authorization:\s*)(Bearer|token)\s+[-._A-Za-z0-9]+",
                             re.IGNORECASE)
_TOKEN_ASSIGN_RE = re.compile(r"(\btoken\s*[=:]\s*)[^&\s,;]+", re.IGNORECASE)
_URL_USERINFO_RE = re.compile(
    r"\b([a-z][a-z0-9+.-]*://)([^@\s/]+)@([^/\s]+)",
    re.IGNORECASE,
)


class OnboardApplyReportError(RuntimeError):
    """The apply report could not be persisted."""


@dataclass(frozen=True)
class StepRef:
    """Stable apply step identity derived from the write plan."""

    step_id: str
    action: str
    target: str
    label: str


class ApplyReportWriter:
    """Atomic writer for the durable apply report."""

    def __init__(self, path: Path, payload: dict[str, Any]) -> None:
        self.path = path
        self.payload = payload
        self._steps = {
            str(step["step_id"]): step
            for step in payload.get("steps", [])
            if isinstance(step, dict)
        }

    @classmethod
    def start(cls, preview: Mapping[str, Any], kwargs: Mapping[str, Any]) -> "ApplyReportWriter":
        """Create the skeleton report before any apply-time mutation."""
        resume_payload = kwargs.get("resume_payload")
        run_id = str(kwargs.get("resume_run_id") or _new_run_id())
        path = run_report_path(run_id)
        steps = [
            {
                "step_id": step.step_id,
                "action": step.action,
                "target": step.target,
                "label": step.label,
                "status": STATUS_PENDING,
                "started_at": None,
                "finished_at": None,
                "error": None,
            }
            for step in steps_from_preview(preview)
        ]
        if isinstance(resume_payload, Mapping):
            steps = _merge_resume_steps(steps, resume_payload)
        payload: dict[str, Any] = {
            "schema": SCHEMA_NAME,
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "package_version": _package_version(),
            "config_path": str(kwargs.get("config_path") or preview.get("config_path") or ""),
            "env": str(kwargs.get("env_name") or ""),
            "api_url": str(kwargs.get("api_url") or ""),
            "checkout_path": str(kwargs.get("project_checkout") or ""),
            "source_repo": str(kwargs.get("project_remote_url") or ""),
            "target_github_repo": _target_github_repo(kwargs),
            "credential_sources": _credential_sources(kwargs),
            "input_snapshot": onboard_apply_snapshot.build(kwargs),
            "steps": steps,
            "final_status": None,
            "failed_step": None,
            "error": None,
            "resume_command": f"{RESUME_COMMAND} --resume {run_id}",
            "start_over_hint": _start_over_hint(kwargs),
            "secret_free": True,
        }
        writer = cls(path, payload)
        writer.write()
        return writer

    def step_started(self, action: str, target: str = "") -> None:
        self._set_status(action, target, STATUS_RUNNING)

    def step_done(self, action: str, target: str = "") -> None:
        self._set_status(action, target, STATUS_DONE)

    def step_skipped(self, action: str, target: str = "") -> None:
        self._set_status(action, target, STATUS_SKIPPED)

    def fail(self, error: BaseException, *, step_id: str | None = None) -> None:
        # The failure point is the last running step (build_report can mark a
        # coarse pair running together before a blocking call); earlier running
        # steps got far enough to hand off, so they are done — leave no step
        # orphaned at "running".
        selected = step_id or self._last_running_step_id() or self._first_pending_step_id()
        for sid, step in self._steps.items():
            if step.get("status") == STATUS_RUNNING and sid != selected:
                step["status"] = STATUS_DONE
                step["finished_at"] = _now_iso()
        if selected and selected in self._steps:
            step = self._steps[selected]
            step["status"] = STATUS_FAILED
            step["finished_at"] = _now_iso()
            step["error"] = sanitize_text(str(error))
            self.payload["failed_step"] = selected
        self.payload["final_status"] = "failed"
        self.payload["error"] = sanitize_text(str(error))
        self.payload["updated_at"] = _now_iso()
        self.write()

    def finish(self) -> None:
        for step in self._steps.values():
            if step.get("status") == STATUS_PENDING:
                step["status"] = STATUS_DONE
                step["finished_at"] = _now_iso()
        self.payload["final_status"] = "done"
        self.payload["updated_at"] = _now_iso()
        self.write()

    def summary(self) -> dict[str, Any]:
        return {
            "run_id": self.payload["run_id"],
            "path": str(self.path),
            "final_status": self.payload.get("final_status"),
            "failed_step": self.payload.get("failed_step"),
            "resume_command": self.payload.get("resume_command"),
        }

    def write(self) -> None:
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            tmp_path = self.path.with_name(self.path.name + ".tmp")
            serialized = json.dumps(self.payload, indent=2, sort_keys=True) + "\n"
            tmp_path.write_text(serialized, encoding="utf-8")
            tmp_path.chmod(0o600)
            os.replace(tmp_path, self.path)
        except OSError as exc:
            raise OnboardApplyReportError(
                f"couldn't create report directory at {self.path.parent}: {exc}"
            ) from exc

    def _set_status(self, action: str, target: str, status: str) -> None:
        step = self._find_step(action, target)
        if step is None:
            return
        step["status"] = status
        now = _now_iso()
        if status == STATUS_RUNNING:
            step["started_at"] = step.get("started_at") or now
        if status in (STATUS_DONE, STATUS_SKIPPED, STATUS_FAILED):
            step["finished_at"] = now
        self.payload["updated_at"] = now
        self.write()

    def _find_step(self, action: str, target: str) -> dict[str, Any] | None:
        for step in self._steps.values():
            if step.get("action") != action:
                continue
            if target and step.get("target") != target:
                continue
            return step
        return None

    def _last_running_step_id(self) -> str | None:
        last: str | None = None
        for step_id, step in self._steps.items():
            if step.get("status") == STATUS_RUNNING:
                last = step_id
        return last

    def _first_pending_step_id(self) -> str | None:
        for step_id, step in self._steps.items():
            if step.get("status") == STATUS_PENDING:
                return step_id
        return None


def fail_report_path(
    path: str | Path,
    error: BaseException,
    *,
    action: str | None = None,
) -> dict[str, Any]:
    """Mark an already-written apply report failed after a late apply step.

    The TUI board-art payoff runs after ``build_report`` returns, so failures
    there need to reopen the durable report and mark the corresponding step.
    """
    report_path = Path(path).expanduser()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    writer = ApplyReportWriter(report_path, payload)
    writer.fail(error, step_id=_step_id_for_action(payload, action))
    return writer.summary()


def _step_id_for_action(
    payload: Mapping[str, Any],
    action: str | None,
) -> str | None:
    if not action:
        return None
    for raw in payload.get("steps") or []:
        if not isinstance(raw, Mapping):
            continue
        if raw.get("action") == action:
            return str(raw.get("step_id") or "")
    return None


def run_report_path(run_id: str) -> Path:
    return onboard_checklist.runs_dir() / REPORTS_DIR_NAME / f"{run_id}.json"


def _new_run_id() -> str:
    return f"run-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _merge_resume_steps(
    steps: list[dict[str, Any]],
    resume_payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    prior = {
        str(step.get("step_id")): step
        for step in resume_payload.get("steps", [])
        if isinstance(step, Mapping)
    }
    for step in steps:
        old = prior.get(str(step.get("step_id")))
        if not isinstance(old, Mapping):
            continue
        if old.get("status") not in (STATUS_DONE, STATUS_SKIPPED):
            continue
        step["status"] = old.get("status")
        step["started_at"] = old.get("started_at")
        step["finished_at"] = old.get("finished_at")
    return steps


def steps_from_preview(preview: Mapping[str, Any]) -> list[StepRef]:
    plan = preview.get("plan") if isinstance(preview, Mapping) else {}
    plan = plan if isinstance(plan, Mapping) else {}
    project = plan.get("project") or {}
    project = project if isinstance(project, Mapping) else {}
    project_name = str(project.get("name") or "").strip()
    if project_name == "None":
        project_name = ""
    refs: list[StepRef] = []
    for index, raw in enumerate(plan.get("steps") or []):
        if not isinstance(raw, Mapping):
            continue
        action = str(raw.get("action") or "")
        if action == "stop-before-project-or-github":
            continue
        target = str(raw.get("target") or "")
        refs.append(StepRef(
            step_id=f"{index:02d}-{action}",
            action=action,
            target=target,
            label=friendly_line(action, target, project_name),
        ))
    return refs


def sanitize_text(value: str) -> str:
    redacted = _AUTH_HEADER_RE.sub(r"\1<redacted>", value)
    redacted = _TOKEN_ASSIGN_RE.sub(r"\1<redacted>", redacted)
    return _URL_USERINFO_RE.sub(_redact_url_userinfo, redacted)


def _redact_url_userinfo(match: re.Match[str]) -> str:
    scheme, userinfo, host = match.groups()
    username, separator, _secret = userinfo.partition(":")
    if separator:
        return f"{scheme}{username}:<redacted>@{host}"
    return f"{scheme}<redacted>@{host}"


def _package_version() -> str:
    try:
        return metadata.version("yoke-cli")
    except metadata.PackageNotFoundError:
        return "unknown"


def _target_github_repo(kwargs: Mapping[str, Any]) -> str:
    owner = str(kwargs.get("project_publish_owner") or "")
    name = str(kwargs.get("project_publish_repo_name") or "")
    repo = str(kwargs.get("project_github_repo") or "")
    if owner and name:
        return f"{owner}/{name}"
    publish = kwargs.get("project_publish")
    publish_owner = str(getattr(publish, "owner", "") or "")
    publish_name = str(getattr(publish, "name", "") or "")
    if publish_owner and publish_name:
        return f"{publish_owner}/{publish_name}"
    return repo


def _start_over_hint(kwargs: Mapping[str, Any]) -> str:
    """Truthful start-over guidance — no `--start-over` flag exists.

    A project run leaves a checkout behind; starting fresh means removing it and
    re-running. A machine-only run has nothing to remove.
    """
    checkout = str(kwargs.get("project_checkout") or "").strip()
    if checkout:
        return f"Remove {checkout} and re-run: {RESUME_COMMAND}"
    return f"Re-run to redo setup: {RESUME_COMMAND}"


def _credential_sources(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "yoke": {
            "kind": str(kwargs.get("token_source_kind") or "argument"),
            "path": str(kwargs.get("token_file") or ""),
        },
        "github_app": {
            "machine": _github_authorization_source(kwargs),
            "project": _github_binding(kwargs),
        },
    }


def _github_authorization_source(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    if str(kwargs.get("machine_github_choice") or "") == "connect":
        return {"kind": "github_app_user_authorization"}
    return {"kind": ""}


def _github_binding(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    adoption = str(kwargs.get("project_github_adoption") or "")
    repo = str(kwargs.get("project_github_repo") or "")
    status = str(kwargs.get("project_github_binding_status") or "")
    if not status:
        if adoption in {"skip", "backlog-only"} or not repo:
            status = "backlog_only"
        else:
            status = "pending_app_connection"
    return {
        "adoption": adoption,
        "repo": repo,
        "installation_id": str(kwargs.get("project_github_installation_id") or ""),
        "repository_id": str(kwargs.get("project_github_repository_id") or ""),
        "status": status,
        "permission_status": _mapping(kwargs.get("project_github_permission_status")),
        "automation": _mapping(kwargs.get("project_github_automation")),
    }


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


__all__ = [
    "ApplyReportWriter",
    "fail_report_path",
    "OnboardApplyReportError",
    "REPORTS_DIR_NAME",
    "SCHEMA_NAME",
    "SCHEMA_VERSION",
    "STATUS_DONE",
    "STATUS_FAILED",
    "STATUS_PENDING",
    "STATUS_RUNNING",
    "STATUS_SKIPPED",
    "StepRef",
    "run_report_path",
    "sanitize_text",
    "steps_from_preview",
]
