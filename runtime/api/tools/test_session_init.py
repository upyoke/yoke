"""Tests for ``yoke_core.tools.session_init``.

Covers the resolver helpers (executor, provider, session-id, lane,
model) under varied env-var combinations plus a smoke run of ``main``
against a temporary git workspace with ``--skip-begin`` so the
session-begin side-effect is bypassed.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.tools import python_interpreter_probe, session_init
from runtime.api.test_constants import TEST_MODEL_ID


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Strip the env vars session_init reads so each test starts clean."""
    for key in (
        "YOKE_EXECUTOR", "YOKE_PROVIDER", "YOKE_SESSION_ID",
        "CLAUDE_SESSION_ID", "CLAUDE_CODE_ENTRYPOINT",
        "CODEX_THREAD_ID", "CODEX_MODEL", "CODEX_ORIGINATOR",
        "CODEX_INTERNAL_ORIGINATOR_OVERRIDE",
    ):
        monkeypatch.delenv(key, raising=False)


class TestResolveExecutor:
    def test_explicit_yoke_executor_wins(self, monkeypatch):
        monkeypatch.setenv("YOKE_EXECUTOR", "custom-harness")
        assert session_init._resolve_executor() == "custom-harness"

    def test_codex_thread_id_implies_codex(self, monkeypatch):
        monkeypatch.setenv("CODEX_THREAD_ID", "abc123")
        assert session_init._resolve_executor() == "codex"

    def test_claude_code_entrypoint_surfaces_through(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "claude-desktop")
        assert session_init._resolve_executor() == "claude-desktop"

    def test_default_is_claude_code(self):
        assert session_init._resolve_executor() == "claude-code"


class TestResolveProvider:
    def test_explicit_yoke_provider_wins(self, monkeypatch):
        monkeypatch.setenv("YOKE_PROVIDER", "custom-provider")
        assert session_init._resolve_provider("claude-code") == "custom-provider"

    def test_codex_executor_defaults_openai(self):
        assert session_init._resolve_provider("codex") == "openai"

    def test_other_executor_defaults_anthropic(self):
        assert session_init._resolve_provider("claude-code") == "anthropic"


class TestResolveSessionId:
    def test_explicit_yoke_session_id_wins(self, monkeypatch):
        monkeypatch.setenv("YOKE_SESSION_ID", "explicit-id")
        assert session_init._resolve_session_id("claude-code") == "explicit-id"

    def test_claude_session_id_used(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_SESSION_ID", "claude-id-1")
        assert session_init._resolve_session_id("claude-code") == "claude-id-1"

    def test_codex_thread_id_used(self, monkeypatch):
        monkeypatch.setenv("CODEX_THREAD_ID", "codex-thread-x")
        assert session_init._resolve_session_id("codex") == "codex-thread-x"

    def test_fallback_generates_id(self):
        sid = session_init._resolve_session_id("claude-code")
        assert sid.startswith("claude-code-")
        assert len(sid) > len("claude-code-")


class TestReadMaxChainSteps:
    def test_returns_default_when_config_missing(self, tmp_path):
        assert session_init._read_max_chain_steps(str(tmp_path)) == "3"

    def test_reads_value_from_config(self, tmp_path):
        config_dir = tmp_path / "data"
        config_dir.mkdir()
        (config_dir / "config").write_text(
            "monitor_hint_color=C5DEF5\nmax_chain_steps=7\nother=x\n",
            encoding="utf-8",
        )
        assert session_init._read_max_chain_steps(str(tmp_path)) == "7"

    def test_ignores_empty_value(self, tmp_path):
        config_dir = tmp_path / "data"
        config_dir.mkdir()
        (config_dir / "config").write_text("max_chain_steps=\n", encoding="utf-8")
        assert session_init._read_max_chain_steps(str(tmp_path)) == "3"


def _seed_harness_sessions(session_id: str, model: str):
    """Return a zero-arg ``init_test_db`` schema applier that builds a
    minimal ``harness_sessions`` table with one row keyed by *session_id*.

    Used by the model-resolver tests to exercise the DB-lookup path of
    ``session_init._resolve_model`` without standing up the real schema.
    The applier resolves its connection through the backend factory so the
    same body builds on SQLite (the per-test file) and Postgres (the
    repointed per-test DSN)."""
    from yoke_core.domain import db_backend

    def _apply() -> None:
        conn = db_backend.connect()
        try:
            conn.execute(
                "CREATE TABLE harness_sessions "
                "(session_id TEXT PRIMARY KEY, model TEXT)"
            )
            conn.execute(
                "INSERT INTO harness_sessions (session_id, model) VALUES (%s, %s)",
                (session_id, model),
            )
            conn.commit()
        finally:
            conn.close()

    return _apply


class TestResolveModel:
    """DB-lookup-by-session-id with ``detect_model`` fallback. SessionStart
    is the canonical writer of ``harness_sessions.model`` — this resolver
    is the reader path that ``session_init`` and ``service_client
    session-offer`` both consume so the LLM agent never has to substitute
    a model identifier into a command line."""

    def test_returns_stored_model_when_row_present(self, tmp_path, monkeypatch):
        with init_test_db(
            tmp_path,
            apply_schema=_seed_harness_sessions(
                "sess-stored", "claude-opus-4-7[1m]",
            ),
        ) as db_path:
            monkeypatch.setattr(
                session_init, "resolve_db_path", lambda: str(db_path),
            )
            assert session_init._resolve_model("sess-stored", "claude-code") == (
                "claude-opus-4-7[1m]"
            )

    def test_falls_back_to_detect_model_when_no_row(
        self, tmp_path, monkeypatch,
    ):
        with init_test_db(
            tmp_path,
            apply_schema=_seed_harness_sessions("sess-other", "ignored"),
        ) as db_path:
            monkeypatch.setattr(
                session_init, "resolve_db_path", lambda: str(db_path),
            )
            with mock.patch.object(
                session_init, "detect_model", return_value="detected-cold",
            ) as detect:
                resolved = session_init._resolve_model("sess-missing", "claude-code")
            assert resolved == "detected-cold"
            detect.assert_called_once_with("claude-code")

    @pytest.mark.parametrize("stored_model", ["unknown", "<synthetic>"])
    def test_falls_back_when_stored_value_is_placeholder(
        self, tmp_path, monkeypatch, stored_model,
    ):
        with init_test_db(
            tmp_path,
            apply_schema=_seed_harness_sessions("sess-unknown", stored_model),
        ) as db_path:
            monkeypatch.setattr(
                session_init, "resolve_db_path", lambda: str(db_path),
            )
            with mock.patch.object(
                session_init, "detect_model", return_value="detected-real",
            ):
                assert session_init._resolve_model(
                    "sess-unknown", "claude-code",
                ) == "detected-real"

    def test_falls_back_when_db_unavailable(self, tmp_path, monkeypatch):
        # Point resolver at a non-existent DB; connect() will succeed at
        # opening an empty SQLite file, but the SELECT will fail because
        # the table does not exist. Resolver should swallow the error
        # and fall through to detect_model().
        monkeypatch.setattr(
            session_init, "resolve_db_path",
            lambda: str(tmp_path / "no_table.db"),
        )
        with mock.patch.object(
            session_init, "detect_model", return_value="detected-empty",
        ):
            assert session_init._resolve_model(
                "sess-any", "claude-code",
            ) == "detected-empty"


class TestMainSmoke:
    def test_main_emits_expected_keys_in_git_workspace(
        self, tmp_path, monkeypatch, capsys,
    ):
        # Build a minimal git workspace.
        workspace = tmp_path / "ws"
        workspace.mkdir()
        subprocess.run(
            ["git", "init", "-q"], cwd=str(workspace), check=True,
        )
        (workspace / "data").mkdir()
        (workspace / "data" / "config").write_text(
            "max_chain_steps=5\n", encoding="utf-8",
        )
        monkeypatch.chdir(workspace)
        monkeypatch.setenv("YOKE_SESSION_ID", "test-session-123")
        # Stub the DB-backed model resolver so this smoke test stays
        # hermetic. The dedicated TestResolveModel suite covers the real
        # lookup path.
        monkeypatch.setattr(
            session_init, "_resolve_model",
            lambda session_id, executor: TEST_MODEL_ID,
        )
        rc = session_init.main(["--skip-begin"])
        assert rc == 0
        out = capsys.readouterr().out
        # Stable key order; every key present.
        for key in (
            "SESSION_ID=test-session-123",
            "WORKSPACE=",
            "LANE=",
            "EXECUTOR=claude-code",
            "PROVIDER=anthropic",
            f"MODEL={TEST_MODEL_ID}",
            "MAX_CHAIN_STEPS=5",
        ):
            assert key in out, f"missing key in output: {key!r}\n--- out ---\n{out}"

    def test_main_errors_outside_git(self, tmp_path, monkeypatch, capsys):
        # No git init — _resolve_workspace returns None, main should fail.
        non_git = tmp_path / "no_git"
        non_git.mkdir()
        monkeypatch.chdir(non_git)
        rc = session_init.main(["--skip-begin"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "not inside a git repository" in err

    def test_main_rejects_legacy_model_flag(self, tmp_path, monkeypatch, capsys):
        """``--model`` was removed; passing it must be rejected
        rather than silently accepted (so we don't accumulate stale callers
        substituting model values from outside the canonical resolver)."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        subprocess.run(
            ["git", "init", "-q"], cwd=str(workspace), check=True,
        )
        monkeypatch.chdir(workspace)
        with pytest.raises(SystemExit):
            session_init.main(["--model", "ignored", "--skip-begin"])


class TestInterpreterAdvisory:
    """AC-1/AC-3/AC-7: ``session_init`` invokes the interpreter probe and
    routes any advisory to stderr only — stdout stays machine-parseable
    ``KEY=VALUE`` lines."""

    def _bootstrap_workspace(self, tmp_path, monkeypatch):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        subprocess.run(
            ["git", "init", "-q"], cwd=str(workspace), check=True,
        )
        monkeypatch.chdir(workspace)
        monkeypatch.setenv("YOKE_SESSION_ID", "advisory-test")
        monkeypatch.setattr(
            session_init, "_resolve_model",
            lambda session_id, executor: TEST_MODEL_ID,
        )

    def test_advisory_routed_to_stderr_not_stdout(
        self, tmp_path, monkeypatch, capsys,
    ):
        """A confirmed missing-dep advisory MUST appear on stderr; stdout
        must still contain only ``KEY=VALUE`` lines so ``/yoke do``'s
        loop init parses cleanly."""
        self._bootstrap_workspace(tmp_path, monkeypatch)
        bad_result = python_interpreter_probe.ProbeResult(
            ok=False, resolved_python="/usr/bin/python3",
            missing_module=python_interpreter_probe.SENTINEL_MODULE,
            override_used=False,
        )
        monkeypatch.setattr(
            python_interpreter_probe, "probe", lambda: bad_result,
        )
        rc = session_init.main(["--skip-begin"])
        assert rc == 0
        captured = capsys.readouterr()
        # Stdout contract: every non-empty line is KEY=VALUE.
        for line in captured.out.splitlines():
            if not line.strip():
                continue
            assert "=" in line, f"non-KEY=VALUE line on stdout: {line!r}"
        # Stderr carries the advisory body.
        assert python_interpreter_probe.SENTINEL_MODULE in captured.err
        assert "/usr/bin/python3" in captured.err

    def test_no_advisory_when_probe_passes(
        self, tmp_path, monkeypatch, capsys,
    ):
        """AC-3: when the resolved python3 has pydantic, stderr must be
        clean of any interpreter advisory text."""
        self._bootstrap_workspace(tmp_path, monkeypatch)
        ok_result = python_interpreter_probe.ProbeResult(
            ok=True, resolved_python="/opt/homebrew/bin/python3",
            missing_module=None, override_used=False,
        )
        monkeypatch.setattr(
            python_interpreter_probe, "probe", lambda: ok_result,
        )
        rc = session_init.main(["--skip-begin"])
        assert rc == 0
        err = capsys.readouterr().err
        # The advisory's signature phrase must be absent.
        assert "Yoke interpreter check" not in err

    def test_probe_exception_does_not_break_session_init(
        self, tmp_path, monkeypatch, capsys,
    ):
        """The advisory emitter must swallow probe exceptions so a broken
        probe never blocks a working session."""
        self._bootstrap_workspace(tmp_path, monkeypatch)

        def _boom():
            raise RuntimeError("probe is wedged")

        monkeypatch.setattr(python_interpreter_probe, "probe", _boom)
        rc = session_init.main(["--skip-begin"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "SESSION_ID=advisory-test" in out
