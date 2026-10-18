"""Scripted campaign cases prove sessions outside a project keep org scope."""

import itertools
import json
import os
import subprocess
import sys
import tempfile
from subprocess import CompletedProcess

import pytest

from runtime.api.domain.test_qa_release_channel_target import _target
from yoke_core.domain.installer_campaign_execution_target import (
    installer_campaign_cases_for_target,
)
from yoke_core.domain.installer_campaign_session_scope_cases import (
    SESSION_SCOPE_SCRIPT,
)

KEYS = (
    "outside-project-sessions",
    "outside-project-reinstall",
    "outside-project-first-work",
)
FOLDER_REFUSAL = (
    "CLAIM_FOLDER_MISMATCH: No local checkout is mapped to project scope-proof for "
    "SCP-1 (Scope proof). Recovery: run `yoke project register CHECKOUT "
    "--project-id 7`, then open a session there; sessions never switch projects."
)


def test_campaign_exports_the_session_scope_cases_in_order():
    cases = installer_campaign_cases_for_target(
        _target("prod"), primary_machine="primary-test", joining_machine="joining-test"
    )
    keyed = {case["case_key"]: case for case in cases}
    assert [keyed[key]["position"] for key in KEYS] == [26, 27, 28]
    assert [case["position"] for case in cases] == list(range(1, len(cases) + 1))
    reinstall = keyed["outside-project-reinstall"]["entry_surface"]
    before = reinstall.index("{yoke_bin} reinstall-before")
    install = reinstall.index("/bin/sh", before)
    assert install < reinstall.index("{yoke_bin} reinstall-after")
    for key in KEYS:
        assert keyed[key]["method_config"]["machine"] == "primary-test"
    # The host adapter expands braces inside entry_surface, scripts included.
    assert "{" not in SESSION_SCOPE_SCRIPT and "}" not in SESSION_SCOPE_SCRIPT


class FakeCli:
    """The installed CLI's session, claim and project answers for one host."""

    def __init__(
        self,
        tmp_path,
        *,
        outside_claim_refuses=True,
        folder_refusal_names_folder=True,
        worker_claim=(0, ""),
    ):
        self.folders = itertools.count()
        self.tmp_path = tmp_path
        self.scopes = {}
        self.checkout = None
        self.outside_claim_refuses = outside_claim_refuses
        self.folder_refusal_names_folder = folder_refusal_names_folder
        self.worker_claim = worker_claim
        self.calls = []

    def mkdtemp(self, prefix=""):
        folder = self.tmp_path / f"{prefix}{next(self.folders)}"
        folder.mkdir()
        if prefix.startswith("scope-proof"):
            self.checkout = os.path.realpath(folder)
        return str(folder)

    def run(self, argv, *, cwd, env, **_kwargs):
        session = env.get("YOKE_SESSION_ID", "")
        command = argv[1:4]
        self.calls.append(command)
        if command[:2] == ["sessions", "begin"]:
            in_project = str(cwd) == self.checkout
            self.scopes.setdefault(session, (7, None) if in_project else (None, 1))
            return self._ok({})
        if command[:2] == ["sessions", "identity"]:
            project, org = self.scopes[session]
            kind = "project" if project is not None else "org"
            return self._ok({"project_id": project, "org_id": org, "scope_kind": kind})
        if command[:2] == ["sessions", "list"]:
            return self._ok({"sessions": [{"session_id": sid} for sid in self.scopes]})
        if command[:2] in (
            ["projects", "create"],
            ["project", "register"],
            ["sessions", "end-if-empty"],
        ):
            return self._ok({})
        if command[:2] == ["items", "create"]:
            return self._ok({"public_ref": "SCP-1"})
        assert command == ["claims", "work", "acquire"]
        if self.scopes[session][0] == 7:
            code, refusal = self.worker_claim
            return self._refused(argv, refusal) if code else self._ok({})
        if str(cwd) != self.checkout:
            if not self.outside_claim_refuses:
                return self._ok({})
            return CompletedProcess(argv, 1, stdout="", stderr=FOLDER_REFUSAL)
        folder = self.checkout if self.folder_refusal_names_folder else "elsewhere"
        return self._refused(
            argv,
            "SESSION_MACHINE_SCOPE_WORK_REFUSED",
            f"Open a session in {folder} (project scope-proof) to work on "
            "SCP-1 (Scope proof); sessions never switch projects.",
        )

    @staticmethod
    def _refused(argv, code, message="refused"):
        body = {"success": False, "error": {"code": code, "message": message}}
        return CompletedProcess(argv, 1, stdout=json.dumps(body), stderr="")

    @staticmethod
    def _ok(result):
        body = json.dumps({"success": True, "result": result})
        return CompletedProcess([], 0, stdout=body, stderr="")


@pytest.fixture
def cli(tmp_path, monkeypatch):
    def install(**options):
        fake = FakeCli(tmp_path, **options)
        monkeypatch.setattr(subprocess, "run", fake.run)
        monkeypatch.setattr(tempfile, "mkdtemp", fake.mkdtemp)
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
        return fake

    return install


def _probe(monkeypatch, mode):
    monkeypatch.setattr(sys, "argv", ["probe", "fixture-yoke", mode])
    exec(compile(SESSION_SCOPE_SCRIPT, "session-scope-probe", "exec"), {})


def test_every_harness_session_outside_a_project_belongs_to_the_org(
    cli, monkeypatch, capsys
):
    fake = cli()
    _probe(monkeypatch, "harnesses")
    assert len(fake.scopes) == 3
    assert set(fake.scopes.values()) == {(None, 1)}
    assert "on every harness" in capsys.readouterr().out


def test_reinstall_keeps_the_saved_session_in_its_org(cli, monkeypatch, capsys):
    fake = cli()
    _probe(monkeypatch, "reinstall-before")
    _probe(monkeypatch, "reinstall-after")
    assert len(fake.scopes) == 1
    assert "reinstallation kept" in capsys.readouterr().out


def test_first_work_refuses_outside_then_admits_a_folder_session(
    cli, monkeypatch, capsys
):
    fake = cli()
    _probe(monkeypatch, "first-work")
    assert fake.calls.count(["claims", "work", "acquire"]) == 3
    assert sorted(fake.scopes.values(), key=str) == [(7, None), (None, 1)]
    assert "admission and claimed the item" in capsys.readouterr().out


def test_first_work_accepts_a_named_model_admission_refusal(cli, monkeypatch, capsys):
    cli(worker_claim=(1, "SESSION_BELOW_INTERN"))
    _probe(monkeypatch, "first-work")
    assert "refused only by SESSION_BELOW_INTERN" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("options", "reason"),
    [
        ({"outside_claim_refuses": False}, "first_work_refusal_missing:"),
        ({"folder_refusal_names_folder": False}, "first_work_scope_refusal_missing:"),
        ({"worker_claim": (1, "")}, "first_work_recovery_failed: an unnamed"),
        (
            {"worker_claim": (1, "SESSION_PROJECT_MISMATCH")},
            "first_work_recovery_failed: SESSION_PROJECT_MISMATCH",
        ),
    ],
)
def test_first_work_fails_closed_without_each_positive_fact(
    cli, monkeypatch, options, reason
):
    cli(**options)
    with pytest.raises(SystemExit) as caught:
        _probe(monkeypatch, "first-work")
    assert str(caught.value).startswith(reason)


def test_outside_session_without_org_scope_kind_fails_closed(cli, monkeypatch):
    fake = cli()
    real_run = fake.run

    def project_scope_identity(argv, **kwargs):
        result = real_run(argv, **kwargs)
        if argv[1:3] == ["sessions", "identity"]:
            body = json.loads(result.stdout)
            body["result"]["scope_kind"] = "project"
            result.stdout = json.dumps(body)
        return result

    monkeypatch.setattr(subprocess, "run", project_scope_identity)
    with pytest.raises(SystemExit) as caught:
        _probe(monkeypatch, "first-work")
    assert str(caught.value).startswith("session_scope_not_org:")
