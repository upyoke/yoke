"""Tests for ``yoke_core.tools.watch_deploy``.

Covers the line classifier against representative deploy_pipeline output
fixtures (stage banners, CI-gate polling, approval halts, stage success
/ failure transitions, noise), exit-code passthrough, and the
nested-invocation rejection path.
"""

from __future__ import annotations

import os

import pytest

from yoke_core.tools import watch_deploy
from yoke_core.tools._watch_runner import filter_match
from yoke_core.tools._watch_throttle import LineClass


class TestDeployClassifier:
    @pytest.mark.parametrize(
        "line",
        [
            "--- Stage: prod-deploy (executor: github_actions) ---",
            "Awaiting human approval for stage 'prod-deploy'",
            # Terminal success line (deploy_pipeline prints it after the
            # last stage) and the already-done startup line.
            "Pipeline complete for run abc123",
            "Pipeline already complete for run abc123",
            "Auto-created run abc123 for YOK-42",
            (
                "Deployment authority: release_control_plane=prod "
                "target_env=stage flow=yoke-stage-release run=run-1"
            ),
            "  Stage 'ephemeral-verify' completed successfully",
            # Helper-resolved shape: ``RESULT_FILE=`` emissions land under
            # the project scratch root's ``storage/`` subtree so the
            # capture inherits the ``YOKE_SCRATCH_ROOT`` / machine config
            # override the rest of the watcher family uses.
            "RESULT_FILE=/var/folders/yoke-scratch/yoke/storage/deploy-results/run-abc.json",
            "YOKE_REPO_ROOT=/Users/operator/yoke",
        ],
    )
    def test_summary_lines_classify(self, line: str) -> None:
        cls = watch_deploy.classify_deploy_line(line)
        assert cls.cls is LineClass.SUMMARY

    @pytest.mark.parametrize(
        "line",
        [
            "Error: deployment run 'abc' not found",
            "Error: stage 'prod-deploy' failed (exit code: 1)",
            "ERROR: malformed deploy_key secret",
            "FAILED deploy script returned nonzero",
            "BLOCKED: Cannot deploy — main branch CI has failed.",
            "Warning: Legacy item-based pipeline invocation.",
            "fatal: unable to fetch refs",
            "  Stage 'prod-deploy' failed (exit code: 1)",
        ],
    )
    def test_urgent_lines_classify(self, line: str) -> None:
        cls = watch_deploy.classify_deploy_line(line)
        assert cls.cls is LineClass.URGENT

    @pytest.mark.parametrize(
        "line",
        [
            "  CI gate: checking deploy.yml on main for owner/repo...",
            "  Workflow status: in_progress (elapsed: 12s, next poll: 5s)",
            "  Workflow run ID: 1234567890",
            "  Found existing run 1234567890 for deploy.yml @ abcdef12",
            "  Existing run status: queued — attaching to it",
            "  Waiting for workflow run to appear... (attempt 2/6)",
            "  No existing run found, triggering workflow_dispatch...",
            "  Trigger failed, retrying find-run with backoff...",
            "  --fresh: skipping existing-run search, will trigger new run",
            (
                "  Stage inputs present: skipping SHA-only existing-run search, "
                "will trigger workflow_dispatch"
            ),
            "  Reconciled stage 'distribution-publish' from prior successful run 123",
            "Seeded deployment flow config converged: yoke-stage-release",
            "  Skipping ephemeral-verify: all member items already passed ephemeral QA during conduct",
            "  Run already completed successfully — skipping deploy trigger",
            "  Existing run 7777 has zero jobs — triggering fresh run",
            "  Existing run 7777 failed — treating as stale, auto-triggering fresh run",
            # core-container-deploy executor build/push milestones
            # (in-process emit; the longest-running stage work).
            "  [core-deploy] image absent; building 1.dkr.ecr/yoke-core:abc from abc",
            "  [core-deploy] image pushed: 1.dkr.ecr/yoke-core:abc",
            "  [core-deploy] image already in registry: 1.dkr.ecr/yoke-core:abc",
            "  [core-deploy] yoke/prod now running 1.dkr.ecr/yoke-core:abc",
        ],
    )
    def test_progress_lines_classify(self, line: str) -> None:
        cls = watch_deploy.classify_deploy_line(line)
        assert cls.cls is LineClass.PROGRESS

    def test_core_deploy_failure_classifies_urgent_not_progress(self) -> None:
        # CoreDeployError messages are re-printed with an ``ERROR:``
        # prefix; the URGENT check must win over the ``[core-deploy]``
        # progress token in the same line.
        line = "ERROR: [core-deploy] docker build failed: exit status 1"
        cls = watch_deploy.classify_deploy_line(line)
        assert cls.cls is LineClass.URGENT

    def test_mid_line_core_deploy_token_stays_noise(self) -> None:
        # ``[core-deploy]`` must lead the line (after indent) — a quoted
        # mention mid-line is not executor progress.
        line = "  deploy_log note: saw [core-deploy] earlier"
        cls = watch_deploy.classify_deploy_line(line)
        assert cls.cls is LineClass.NOISE

    @pytest.mark.parametrize(
        "line",
        [
            "  resolving DB path...",
            "irrelevant noise",
            "Deployment flow definition loaded",
            "",
        ],
    )
    def test_noise_lines_classify(self, line: str) -> None:
        cls = watch_deploy.classify_deploy_line(line)
        assert cls.cls is LineClass.NOISE

    def test_urgent_wins_over_summary_when_both_match(self) -> None:
        # A stage-failure banner that also mentions a stage name must
        # classify URGENT, not SUMMARY — failures must emit immediately.
        line = "  Stage 'prod-deploy' failed (exit code: 1)"
        cls = watch_deploy.classify_deploy_line(line)
        assert cls.cls is LineClass.URGENT


class TestUnionPattern:
    def test_summary_lines_match_union(self) -> None:
        for line in (
            "--- Stage: prod-deploy (executor: github_actions) ---",
            "Awaiting human approval for stage 'prod-deploy'",
            "  Stage 'ephemeral-verify' completed successfully",
            "Pipeline complete for run abc123",
            "RESULT_FILE=/tmp/x",
        ):
            assert filter_match(watch_deploy.DEPLOY_PROGRESS_PATTERN, line)

    def test_urgent_lines_match_union(self) -> None:
        for line in (
            "Error: deployment run not found",
            "Warning: legacy invocation",
            "fatal: bad ref",
            "  Stage 'prod-deploy' failed (exit code: 1)",
        ):
            assert filter_match(watch_deploy.DEPLOY_PROGRESS_PATTERN, line)

    def test_progress_lines_match_union(self) -> None:
        for line in (
            "  CI gate: checking deploy.yml on main for owner/repo...",
            "  Workflow status: in_progress (elapsed: 12s, next poll: 5s)",
            "  Workflow run ID: 1234567890",
            "  Existing run status: queued — attaching to it",
            "  [core-deploy] image pushed: 1.dkr.ecr/yoke-core:abc",
        ):
            assert filter_match(watch_deploy.DEPLOY_PROGRESS_PATTERN, line)

    def test_mid_line_error_does_not_match(self) -> None:
        # Stray ``Error:`` inside quoted text must not flip the line to
        # URGENT — the prefix rules anchor to line start.
        line = '  deploy_log message: "Error: was suppressed earlier"'
        assert not filter_match(watch_deploy.DEPLOY_PROGRESS_PATTERN, line)


class TestNestedDeployRejection:
    @pytest.mark.parametrize(
        "args",
        [
            ["python3", "-m", "yoke_core.domain.deploy_pipeline"],
            [
                "python3",
                "-m",
                "yoke_core.domain.deploy_pipeline",
                "abc123",
            ],
            ["python", "-m", "yoke_core.domain.deploy_pipeline"],
            ["/usr/bin/python3", "-m", "yoke_core.domain.deploy_pipeline"],
            ["sys.executable", "-m", "yoke_core.domain.deploy_pipeline"],
        ],
    )
    def test_nested_invocation_detected(self, args: list[str]) -> None:
        assert watch_deploy._is_nested_deploy_invocation(args)

    @pytest.mark.parametrize(
        "args",
        [
            ["abc123"],
            ["YOK-42"],
            ["--timeout", "30"],
            [],
            ["python3", "-m", "pytest"],
            ["python3", "-m", "yoke_core.engines.doctor"],
        ],
    )
    def test_non_nested_invocations_pass(self, args: list[str]) -> None:
        assert not watch_deploy._is_nested_deploy_invocation(args)


class TestDeployArgv:
    def test_argv_includes_module_prefix(self) -> None:
        import sys

        argv = watch_deploy._deploy_argv(["abc123"])
        assert argv[0] == sys.executable
        assert argv[1:4] == [
            "-m",
            "yoke_core.domain.deploy_pipeline",
            "abc123",
        ]

    def test_argv_with_no_args(self) -> None:
        import sys

        argv = watch_deploy._deploy_argv([])
        assert argv == [
            sys.executable,
            "-m",
            "yoke_core.domain.deploy_pipeline",
        ]


class TestStreamingPairOutput:
    def test_print_streaming_pair_emits_three_lines(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = watch_deploy.main(["--print-streaming-pair", "--", "abc123"])
        assert rc == 0
        out = capsys.readouterr().out
        # Three artifacts: background command, watch_tail line,
        # post-completion raw-inspection line.
        assert "yoke_core.tools.watch_deploy" in out
        assert "yoke_core.tools.watch_tail" in out
        # The deploy argument must reach the printed background command.
        assert "abc123" in out
        assert "tail -80" in out

    def test_print_streaming_pair_works_in_any_position(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = watch_deploy.main(["--", "abc123", "--print-streaming-pair"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "yoke_core.tools.watch_deploy" in out


class TestMainDispatch:
    def test_main_returns_watcher_exit_code(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        seen = {}

        def fake_run_watcher(**kwargs):
            seen.update(kwargs)
            return 2

        monkeypatch.setattr(
            watch_deploy._watch_runner, "run_watcher", fake_run_watcher
        )
        raw = tmp_path / "raw.log"
        progress = tmp_path / "progress.log"

        rc = watch_deploy.main(
            [
                "--raw-capture",
                str(raw),
                "--progress-capture",
                str(progress),
                "--",
                "run-123",
                "--timeout",
                "1",
            ]
        )

        assert rc == 2
        assert seen["raw_capture"] == raw
        assert seen["progress_capture"] == progress
        assert seen["kind"] == "deploy"
        assert seen["argv"][1:3] == [
            "-m",
            "yoke_core.domain.deploy_pipeline",
        ]
        assert seen["argv"][-3:] == ["run-123", "--timeout", "1"]


class TestNestedInvocationRejectionPath:
    def test_nested_invocation_returns_exit_code_two(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = watch_deploy.main(
            ["--", "python3", "-m", "yoke_core.domain.deploy_pipeline"]
        )
        assert rc == 2
        err = capsys.readouterr().err
        assert "watch_deploy expects bare deploy_pipeline args" in err


class TestProductSrc:
    """``--product-src`` runs deploy_pipeline from the pinned product code.

    A pinned checkout supplies both code and deploy build context.
    """

    def test_product_src_prepends_product_pythonpath(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        seen = {}
        monkeypatch.setattr(
            watch_deploy._watch_runner,
            "run_watcher",
            lambda **kwargs: seen.update(kwargs) or 0,
        )
        # Keep the test independent of a real product checkout.
        monkeypatch.setattr(
            watch_deploy._source_pythonpath,
            "import_origin_refusal",
            lambda root, **kwargs: None,
        )
        monkeypatch.setattr(
            watch_deploy, "prepare_product_deploy_args",
            lambda args, root: [*args, "--product-repo-path", str(root.resolve())],
        )
        product_root = tmp_path / "product"
        product_root.mkdir()

        rc = watch_deploy.main(
            [
                "--product-src",
                str(product_root),
                "--raw-capture",
                str(tmp_path / "raw.log"),
                "--progress-capture",
                str(tmp_path / "prog.log"),
                "--",
                "run-1",
                "--image-tag",
                "abc123",
            ]
        )

        assert rc == 0
        env = seen["env"]
        assert env is not None
        pythonpath = env["PYTHONPATH"].split(os.pathsep)
        core_src = str((product_root / "packages/yoke-core/src").resolve())
        assert core_src in pythonpath
        # The product source leads so it wins over any ambient checkout.
        assert pythonpath[0].startswith(str(product_root.resolve()))

    def test_absent_product_src_warns_and_inherits_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        seen = {}
        monkeypatch.setattr(
            watch_deploy._watch_runner,
            "run_watcher",
            lambda **kwargs: seen.update(kwargs) or 0,
        )

        rc = watch_deploy.main(
            [
                "--raw-capture",
                str(tmp_path / "raw.log"),
                "--progress-capture",
                str(tmp_path / "prog.log"),
                "--",
                "run-1",
            ]
        )

        assert rc == 0
        # None => run_watcher inherits the ambient process env.
        assert seen["env"] is None
        err = capsys.readouterr().err
        assert "--product-src" in err
        assert "stale logic" in err

    def test_product_src_import_refusal_returns_three(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # run_watcher must NOT be reached when the product checkout can't
        # import yoke_core — the deploy is refused before it starts.
        monkeypatch.setattr(
            watch_deploy._watch_runner,
            "run_watcher",
            lambda **kwargs: pytest.fail("run_watcher should not run"),
        )
        monkeypatch.setattr(
            watch_deploy._source_pythonpath,
            "import_origin_refusal",
            lambda root, **kwargs: "yoke_core import origin is outside checkout",
        )
        product_root = tmp_path / "product"
        product_root.mkdir()

        rc = watch_deploy.main(
            ["--product-src", str(product_root), "--", "run-1"]
        )

        assert rc == 3
        assert "watch_deploy --product-src" in capsys.readouterr().err
