"""The standalone merge boundary run from a machine with a remote plane.

Every case here describes the same machine: the control plane is reached
over https, so the client holds no database and no GitHub App private key.
Surfaces written when that machine *was* the universe keep rediscovering
this the hard way — by minting credentials that only exist server-side, by
naming a different local universe in a recovery recipe, or by refusing a
merge because the deployed engine is one release behind the branch being
merged.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
    TargetRef,
)
from yoke_contracts.machine_config.schema import ENV_OVERRIDE
from yoke_core.domain import control_plane_function_degradation as degradation
from yoke_core.engines import merge_worktree_tests, merge_worktree_tests_ci

_PAIRED_CONFIG = {
    "connections": {
        "prod": {"transport": "https"},
        "prod-db-admin": {"transport": "local-postgres", "prod": True},
        "local": {"transport": "local-postgres"},
    }
}


def _ok(payload: dict) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True, function="f", version="v1", result=payload,
    )


def _err(code: str, message: str = "", hint: str = "") -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function="f",
        version="v1",
        error=FunctionError(code=code, message=message, recovery_hint=hint),
    )


def _bind_connection(monkeypatch, *, active: str, config=None) -> None:
    monkeypatch.setattr(
        "yoke_cli.config.machine_config.load_config",
        lambda *a, **k: config if config is not None else _PAIRED_CONFIG,
    )
    monkeypatch.setattr(
        "yoke_cli.config.machine_config.active_env", lambda *a, **k: active,
    )


def _target() -> TargetRef:
    return TargetRef(kind="item", item_id=7)


class TestRegistrySkewDegradation:
    """A client ahead of its server still has to be able to merge."""

    def test_retries_in_process_against_the_paired_admin_connection(
        self, monkeypatch,
    ) -> None:
        _bind_connection(monkeypatch, active="prod")
        monkeypatch.delenv(ENV_OVERRIDE, raising=False)
        calls: list[dict] = []
        announced: list[str] = []

        def _dispatch(**kwargs):
            kwargs["env_at_call"] = os.environ.get(ENV_OVERRIDE)
            calls.append(kwargs)
            if kwargs.get("local_only"):
                return _ok({"scope": "full", "command": "pytest"})
            return _err("function_version_skew", "server registry is older")

        result = degradation.dispatch_through_paired_admin_on_skew(
            function_id="merge.tests.post_rebase_requirement",
            target=_target(),
            payload={"transition_id": "release"},
            announce=announced.append,
            dispatch=_dispatch,
        )

        assert result.success
        assert len(calls) == 2
        # The retry runs in-process against the env that serves the same
        # universe the relay was already answering for.
        assert calls[1]["local_only"] is True
        assert calls[1]["env_at_call"] == "prod-db-admin"
        assert announced and "prod-db-admin" in announced[0]
        assert "[degraded]" in announced[0]
        # The pinned env is scoped to the retry.
        assert ENV_OVERRIDE not in os.environ

    def test_restores_a_preexisting_env_selection(self, monkeypatch) -> None:
        _bind_connection(monkeypatch, active="prod")
        monkeypatch.setenv(ENV_OVERRIDE, "prod")

        degradation.dispatch_through_paired_admin_on_skew(
            function_id="f",
            target=_target(),
            announce=lambda _m: None,
            dispatch=lambda **kwargs: (
                _ok({}) if kwargs.get("local_only") else _err("function_version_skew")
            ),
        )

        assert os.environ[ENV_OVERRIDE] == "prod"

    def test_without_a_paired_connection_the_server_answer_stands(
        self, monkeypatch,
    ) -> None:
        """No same-universe database means nothing honest to degrade to."""
        _bind_connection(
            monkeypatch,
            active="prod",
            config={"connections": {"prod": {"transport": "https"}}},
        )
        calls: list[dict] = []
        announced: list[str] = []

        result = degradation.dispatch_through_paired_admin_on_skew(
            function_id="f",
            target=_target(),
            announce=announced.append,
            dispatch=lambda **kwargs: calls.append(kwargs)
            or _err("function_version_skew", "unserved", hint="wait for deploy"),
        )

        assert not result.success
        assert result.error is not None
        assert "wait for deploy" in (result.error.recovery_hint or "")
        assert len(calls) == 1
        assert announced == []

    def test_an_ordinary_failure_is_never_retried_locally(
        self, monkeypatch,
    ) -> None:
        _bind_connection(monkeypatch, active="prod")
        calls: list[dict] = []

        result = degradation.dispatch_through_paired_admin_on_skew(
            function_id="f",
            target=_target(),
            announce=lambda _m: None,
            dispatch=lambda **kwargs: calls.append(kwargs)
            or _err("claim_required", "acquire a work claim"),
        )

        assert not result.success
        assert len(calls) == 1


class TestVerificationResolution:
    """What the tests phase does with the answers it gets."""

    def _ctx(self, tmp_path):
        return SimpleNamespace(
            project="yoke",
            item_id="7",
            epic_id=None,
            worktree_path=str(tmp_path),
            args=SimpleNamespace(
                branch="PRJ-7", standalone=True, item_id=7,
                local_verification=False,
            ),
        )

    def test_an_unserved_function_reports_its_recovery_not_just_a_code(
        self, monkeypatch, tmp_path,
    ) -> None:
        """A merge blocked by skew must say what would unblock it."""
        monkeypatch.setattr(
            merge_worktree_tests,
            "_post_rebase_transition_candidates",
            lambda _item_id: ["release"],
        )
        monkeypatch.setattr(
            merge_worktree_tests,
            "_resolve_requirement",
            lambda _item, _transition: _err(
                "function_version_skew",
                "the active HTTPS env does not serve that function",
                hint="rerun with `yoke --env prod-db-admin ...`",
            ),
        )

        with pytest.raises(RuntimeError) as excinfo:
            merge_worktree_tests._registered_verification_command(
                self._ctx(tmp_path)
            )

        message = str(excinfo.value)
        assert "function_version_skew" in message
        assert "prod-db-admin" in message

    def test_covering_qa_evidence_skips_ci_dispatch_entirely(
        self, monkeypatch, tmp_path,
    ) -> None:
        """A verdict on this exact tree is the verification; nothing runs."""
        printed: list[str] = []
        monkeypatch.setattr(
            merge_worktree_tests,
            "_parent",
            lambda: SimpleNamespace(_print=lambda msg, **k: printed.append(msg)),
        )
        monkeypatch.setattr(
            merge_worktree_tests,
            "_registered_verification_command",
            lambda _ctx: ("full", "pytest", [{"run_id": 12, "head_sha": "a" * 40}]),
        )
        monkeypatch.setattr(
            "yoke_core.engines.merge_worktree_tree_coverage._tree_object_id",
            lambda _worktree, _rev: "same-tree",
        )

        def _never(*args, **kwargs):
            raise AssertionError("covered tree must not reach CI routing")

        monkeypatch.setattr(merge_worktree_tests_ci, "_should_route_ci", _never)
        monkeypatch.setattr(merge_worktree_tests_ci, "run_ci_verification", _never)
        monkeypatch.setattr(
            merge_worktree_tests, "_run_streaming", _never,
        )

        assert merge_worktree_tests.run_tests(self._ctx(tmp_path)) is None
        assert any("skipping registered verification" in line for line in printed)


class TestCandidateHeadBinding:
    """Which commit the recorded verdict is answerable for."""

    def _ctx(self, tmp_path):
        return SimpleNamespace(
            project="yoke",
            item_id="7",
            worktree_path=str(tmp_path),
            args=SimpleNamespace(branch="PRJ-7", local_verification=False),
        )

    def test_a_plane_without_the_field_binds_to_the_published_candidate(
        self, monkeypatch, tmp_path,
    ) -> None:
        """An older control plane degrades by name, not by refusing."""
        printed: list[str] = []
        monkeypatch.setattr(
            merge_worktree_tests_ci,
            "_parent",
            lambda: SimpleNamespace(_print=lambda msg, **k: printed.append(msg)),
        )
        monkeypatch.setattr(
            "yoke_core.domain.qa_case_ci_lane.run_head_sha",
            lambda **kwargs: "",
        )

        covered = merge_worktree_tests_ci._covered_head_sha(
            project="yoke",
            repo="acme/widgets",
            ci_run_id="55",
            candidate_sha="b" * 40,
            worktree=tmp_path,
        )

        assert covered == "b" * 40
        assert any("no head sha" in line for line in printed)

    def test_the_head_read_never_resolves_credentials_on_this_machine(
        self, monkeypatch, tmp_path,
    ) -> None:
        """App private keys live server-side; a client mint fails there."""

        def _forbidden(*args, **kwargs):
            raise AssertionError(
                "merge CI verification must not mint GitHub App credentials"
            )

        monkeypatch.setattr(
            "yoke_core.domain.project_github_auth.resolve_project_github_auth",
            _forbidden,
        )
        monkeypatch.setattr(
            merge_worktree_tests_ci,
            "_parent",
            lambda: SimpleNamespace(_print=lambda *a, **k: None),
        )
        monkeypatch.setattr(
            "yoke_core.domain.qa_case_ci_lane.run_head_sha",
            lambda **kwargs: "c" * 40,
        )
        monkeypatch.setattr(
            "yoke_core.engines.merge_worktree_tree_coverage._tree_object_id",
            lambda _worktree, _rev: "same-tree",
        )

        assert merge_worktree_tests_ci._covered_head_sha(
            project="yoke",
            repo="acme/widgets",
            ci_run_id="55",
            candidate_sha="b" * 40,
            worktree=tmp_path,
        ) == "c" * 40
