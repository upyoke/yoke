"""Scripted campaign cases prove sessions outside a project keep org scope."""

import itertools
import json
import subprocess
import sys
import tempfile
import time
from subprocess import CompletedProcess

import pytest

from runtime.api.domain.test_qa_release_channel_target import _target
from yoke_core.domain.installer_campaign_execution_target import (
    installer_campaign_cases_for_target,
)
from yoke_core.domain.installer_campaign_session_scope_cases import (
    SESSION_SCOPE_SCRIPT,
)
from yoke_core.domain.session_probe import PROBE_MAX_LIFETIME_SECONDS

KEYS = (
    "outside-project-sessions",
    "outside-project-reinstall",
    "outside-project-first-work",
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
        assert keyed[key]["method_config"]["test_machine"] == "primary-test"
    # The host adapter expands braces inside entry_surface, scripts included.
    assert "{" not in SESSION_SCOPE_SCRIPT and "}" not in SESSION_SCOPE_SCRIPT


class FakeCli:
    """The installed CLI's session, claim and project answers for one host."""

    def __init__(self, tmp_path, *, claim=(0, ""), release_code=0):
        self.folders = itertools.count()
        self.tmp_path = tmp_path
        self.scopes = {}
        self.claim = claim
        self.release_code = release_code
        self.calls = []
        # Seconds on a fake clock; begun and ended sessions record their instants.
        self.now = 0.0
        self.begun = {}
        self.ended = {}

    def sleep(self, seconds):
        self.now += seconds

    def _listed(self, argv):
        """Apply the served --session filter and the probe-session exclusion."""
        state = argv[argv.index("--liveness") + 1]
        wanted = argv[argv.index("--session") + 1] if "--session" in argv else None
        rows = []
        for sid in self.scopes:
            ended = sid in self.ended
            probe = (
                ended
                and self.ended[sid] - self.begun[sid] <= PROBE_MAX_LIFETIME_SECONDS
            )
            if (state == "ended") != ended or probe or wanted not in (None, sid):
                continue
            rows.append({"session_id": sid})
        return rows

    def mkdtemp(self, prefix=""):
        folder = self.tmp_path / f"{prefix}{next(self.folders)}"
        folder.mkdir()
        return str(folder)

    def run(self, argv, *, cwd, env, **_kwargs):
        session = env.get("YOKE_SESSION_ID", "")
        args = argv[1:]
        command = args[:3]
        self.calls.append(command)
        # A JSON read without --full can come back as a saved-response pointer.
        assert "--json" not in argv or "--full" in argv
        if command[:2] == ["sessions", "begin"]:
            self.scopes.setdefault(session, (None, 1))
            self.begun.setdefault(session, self.now)
            return self._ok({})
        if command[:2] == ["sessions", "identity"]:
            project, org = self.scopes[session]
            kind = "project" if project is not None else "org"
            return self._ok({"project_id": project, "org_id": org, "scope_kind": kind})
        if command[:2] == ["sessions", "list"]:
            return self._ok({"sessions": self._listed(argv)})
        if command[:2] == ["sessions", "end-if-empty"]:
            self.ended.setdefault(session, self.now)
            return self._ok({})
        if command[:2] == ["projects", "create"]:
            return self._ok({})
        if command[:2] == ["items", "create"]:
            if args[2:6] != ["--title", "Scope proof", "--workflow", "task"]:
                return CompletedProcess(
                    argv, 2, stdout="", stderr=f"{ITEM_CREATE_REFUSAL} {args[2:4]}"
                )
            return self._ok({"public_ref": "SCP-1"})
        if command == ["claims", "work", "release"]:
            return CompletedProcess(argv, self.release_code, stdout="", stderr="")
        assert command == ["claims", "work", "acquire"]
        code, refusal = self.claim
        return self._refused(argv, refusal) if code else self._ok({})

    @staticmethod
    def _refused(argv, code, message="refused"):
        body = {"success": False, "error": {"code": code, "message": message}}
        return CompletedProcess(argv, 1, stdout=json.dumps(body), stderr="")

    @staticmethod
    def _ok(result):
        body = json.dumps({"success": True, "result": result})
        return CompletedProcess([], 0, stdout=body, stderr="")


ITEM_CREATE_REFUSAL = "yoke items create: error: unrecognized arguments:"


@pytest.fixture
def cli(tmp_path, monkeypatch):
    def install(**options):
        fake = FakeCli(tmp_path, **options)
        monkeypatch.setattr(subprocess, "run", fake.run)
        monkeypatch.setattr(time, "sleep", fake.sleep)
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
    # Each session outlives the probe window before it ends, so history keeps it.
    assert all(
        fake.ended[sid] - fake.begun[sid] > PROBE_MAX_LIFETIME_SECONDS
        for sid in fake.scopes
    )


def test_session_ended_inside_probe_window_is_hidden_from_history(cli, monkeypatch):
    fake = cli()
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    with pytest.raises(SystemExit, match="session_scope_history_hidden"):
        _probe(monkeypatch, "harnesses")
    assert fake.ended


def test_reinstall_keeps_the_saved_session_in_its_org(cli, monkeypatch, capsys):
    fake = cli()
    _probe(monkeypatch, "reinstall-before")
    _probe(monkeypatch, "reinstall-after")
    assert len(fake.scopes) == 1
    assert "reinstallation kept" in capsys.readouterr().out


def test_first_work_claims_and_releases_from_outside_the_project(
    cli, monkeypatch, capsys
):
    fake = cli()
    _probe(monkeypatch, "first-work")
    assert fake.calls.count(["claims", "work", "acquire"]) == 1
    assert fake.calls.count(["claims", "work", "release"]) == 1
    assert list(fake.scopes.values()) == [(None, 1)]
    output = capsys.readouterr().out
    assert "claim SCP-1 exit 0:" in output
    assert "claimed and released the item and kept its organization scope" in output


def test_first_work_accepts_a_named_model_admission_refusal(cli, monkeypatch, capsys):
    fake = cli(claim=(1, "SESSION_BELOW_INTERN"))
    _probe(monkeypatch, "first-work")
    assert "refused only by SESSION_BELOW_INTERN" in capsys.readouterr().out
    assert ["claims", "work", "release"] not in fake.calls


@pytest.mark.parametrize(
    ("options", "reason"),
    [
        ({"claim": (1, "")}, "first_work_claim_unnamed:"),
        ({"release_code": 1}, "first_work_release_failed:"),
    ],
)
def test_first_work_fails_closed_without_each_positive_fact(
    cli, monkeypatch, options, reason
):
    cli(**options)
    with pytest.raises(SystemExit) as caught:
        _probe(monkeypatch, "first-work")
    assert str(caught.value).startswith(reason)


def test_a_failed_item_create_prints_its_output_before_refusing(
    cli, monkeypatch, capsys
):
    fake = cli()
    real_run = fake.run

    def refused_create(argv, **kwargs):
        if argv[1:3] == ["items", "create"]:
            return CompletedProcess(
                argv, 2, stdout="partial", stderr=ITEM_CREATE_REFUSAL
            )
        return real_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", refused_create)
    with pytest.raises(SystemExit) as caught:
        _probe(monkeypatch, "first-work")
    assert str(caught.value).startswith("first_work_fixture_item_failed:")
    output = capsys.readouterr().out
    assert f"items create exit 2:\npartial\n{ITEM_CREATE_REFUSAL}" in output


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
