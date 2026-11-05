"""One registry pass checks command help, usage and parser contracts."""

import argparse
import contextlib
import io
import json
import re
from pathlib import Path

import pytest

from runtime.api.cli.cli_registry_usage import (
    _usage_drift,
    advertised_flags,
    assert_adapter_usage,
)
from yoke_cli.commands import flag_adapters
from yoke_cli.commands.command_tree import (
    command_routes,
    discovery_routes,
    immediate_children,
)
from yoke_cli.commands.group_help import can_route_group
from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY, SUBCOMMAND_ALIAS_REGISTRY
from yoke_cli.main import main
from yoke_cli.transport.response_evidence import wrapped_lines


EXPECTED_DISPATCH = [
    (
        True,
        ("projects", "capability", "secret", "set"),
        "projects.capability_secret.set",
    ),
    (False, ("deployment-flows", "get"), "deployment_flows.get"),
    (False, ("deployment-flows", "list"), "deployment_flows.list"),
    (False, ("deployment-flows", "stages"), "deployment_flows.stages"),
    (False, ("deployment-runs", "add-item"), "deployment_runs.add_item"),
    (False, ("deployment-runs", "approve"), "deployment_runs.approve"),
    (False, ("deployment-runs", "create"), "deployment_runs.create"),
    (False, ("deployment-runs", "failure-trace"), "deployment_runs.failure_trace"),
    (False, ("deployment-runs", "find-by-item"), "deployment_runs.find_by_item"),
    (False, ("deployment-runs", "get"), "deployment_runs.get"),
    (False, ("deployment-runs", "list"), "deployment_runs.list"),
    (False, ("deployment-runs", "resolve-target"), "deployment_runs.resolve_target"),
    (False, ("deployment-runs", "stages"), "deployment_runs.stages"),
    (False, ("deployment-runs", "terminalize"), "deployment_runs.terminalize"),
    (False, ("deployment-runs", "update"), "deployment_runs.update"),
    (
        False,
        ("deployment-runs", "validate-composition"),
        "deployment_runs.validate_composition",
    ),
    (False, ("ephemeral-env", "update"), "ephemeral_env.update"),
    (False, ("github-actions", "failed-log"), "github_actions.failed_log"),
    (False, ("github-actions", "runners", "status"), "github_actions.runners.status"),
    (False, ("github-actions", "secret", "set"), "github_actions.secret.set"),
    (False, ("github-actions", "variable", "set"), "github_actions.variable.set"),
    (False, ("github-actions", "wait-run"), "github_actions.wait_run"),
    (False, ("identity", "link", "set"), "identity.link.set"),
    (False, ("item-worktrees", "get"), "item_worktrees.get"),
    (False, ("item-worktrees", "list"), "item_worktrees.list"),
    (False, ("item-worktrees", "path-record"), "item_worktrees.path_record"),
    (False, ("item-worktrees", "release"), "item_worktrees.release"),
    (False, ("organizations", "domain", "set"), "organizations.domain.set"),
    (False, ("organizations", "get"), "organizations.get"),
    (False, ("project", "snapshot", "sync"), "project.snapshot.sync"),
    (
        False,
        ("project-structure", "deploy-defaults", "get"),
        "project_structure.deploy_defaults.get",
    ),
    (False, ("projects", "capability-secret", "set"), "projects.capability_secret.set"),
    (False, ("projects", "checkout-context"), "projects.checkout_context.run"),
    (False, ("projects", "create"), "projects.create"),
    (False, ("projects", "list"), "projects.list"),
    (False, ("projects", "resolve-by-github-repo"), "projects.resolve_by_github_repo"),
    (False, ("projects", "update"), "projects.update"),
    (False, ("sessions", "list"), "sessions.list"),
    (False, ("strategy", "doc", "create"), "strategy.doc.create"),
    (False, ("strategy", "doc", "get"), "strategy.doc.get"),
    (False, ("strategy", "doc", "list"), "strategy.doc.list"),
    (False, ("strategy", "doc", "replace"), "strategy.doc.replace"),
    (False, ("strategy", "ingest"), "strategy.ingest.run"),
    (False, ("strategy", "render"), "strategy.render.run"),
    (False, ("strategy", "seed-defaults"), "strategy.seed_defaults.run"),
]


def test_expected_dispatch_mapping():
    for alias, tokens, function in EXPECTED_DISPATCH:
        registry = SUBCOMMAND_ALIAS_REGISTRY if alias else SUBCOMMAND_REGISTRY
        assert registry[tokens][0] == function, tokens


def test_registry_help_and_usage(monkeypatch, tmp_path):
    routes = command_routes()

    def deny(*args, **kwargs):
        raise AssertionError("Help attempted execution or network access")

    monkeypatch.setattr("subprocess.Popen", deny)
    monkeypatch.setattr("socket.socket.connect", deny)
    monkeypatch.setattr(Path, "write_text", deny)
    monkeypatch.setattr(
        "yoke_cli.commands.adapters.source_dev_run._source_runner", deny
    )
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", "/nonexistent/machine-config.json")
    discovery = discovery_routes()
    prefixes = {route[:n] for route in discovery for n in range(1, len(route))}
    evidence, checked_adapters = [], set()
    for route in sorted(set(routes) | discovery | prefixes | {()}):
        flags = ("--help", "-h", "help") if can_route_group(route) else ("--help", "-h")
        for flag in flags:
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    rc = main([*route, flag])
                except SystemExit as exc:
                    rc = exc.code if isinstance(exc.code, int) else 1
            text = out.getvalue() + err.getvalue()
            record = dict(
                route="yoke " + " ".join(route),
                flag=flag,
                exit=rc,
                lines=wrapped_lines(text),
                characters=len(text),
                advisory_lines=40
                if not route
                else 80
                if can_route_group(route)
                else 120,
            )
            evidence.append(record)
            assert rc == 0, (record, text)
            assert text.strip(), record
            assert record["lines"] <= 350, (record, text)
            for child in immediate_children(route):
                assert "yoke " + " ".join(child) in text, (record, child)
            assert "bad/missing flag" not in text
            if flag != "--help" or route not in routes:
                continue
            assert out.getvalue().strip(), (route, err.getvalue())
            assert _usage_drift(out.getvalue()) == ([], []), (route, text)
            function, adapter = routes[route]
            if route in SUBCOMMAND_REGISTRY:
                assert function in flag_adapters.ADAPTER_USAGE, function
                usage = flag_adapters.ADAPTER_USAGE[function]
                parser_flags = set(
                    re.findall(r"--[A-Za-z0-9][A-Za-z0-9-]*", out.getvalue())
                )
                assert not advertised_flags(usage) - parser_flags, (route, usage, text)
            if adapter not in checked_adapters and adapter.__module__.startswith(
                "yoke_cli.commands.adapters."
            ):
                with monkeypatch.context() as capture:
                    assert_adapter_usage(capture, adapter, routes)
                checked_adapters.add(adapter)
    for function, usage in flag_adapters.ADAPTER_USAGE.items():
        assert usage.startswith("yoke "), (function, usage)
    # Audit evidence is a fixture report, never a claim of live execution.
    with (tmp_path / "help-routes.json").open("w") as handle:
        json.dump(evidence, handle)
    print(
        f"Fixture help audit: {len(evidence)} spellings; max lines {max(row['lines'] for row in evidence)}; advisory overruns {sum(row['lines'] > row['advisory_lines'] or row['characters'] > row['advisory_lines'] * 60 for row in evidence)}"
    )
    for row in evidence:
        if (
            row["lines"] > row["advisory_lines"]
            or row["characters"] > row["advisory_lines"] * 60
        ):
            print("Advisory review:", row)


@pytest.mark.parametrize(
    "usage, expected",
    [
        ("yoke sample --extra", (["--visible"], ["--extra"])),
        ("yoke sample --visible", ([], [])),
    ],
)
def test_rendered_usage_drift_remains_detectable(usage, expected):
    parser = argparse.ArgumentParser(prog="yoke sample", usage=usage)
    parser.add_argument("--visible")
    assert _usage_drift(parser.format_help()) == expected


@pytest.mark.parametrize(
    "usage, error_usage",
    [
        ("yoke sample", "yoke sample --visible"),
        ("yoke retired --visible", "yoke sample --visible"),
        ("yoke sample --visible", "yoke retired --visible"),
    ],
)
def test_parser_or_error_recipe_drift_remains_detectable(
    monkeypatch, usage, error_usage
):
    from yoke_cli.commands import _helpers

    def adapter(args):
        parser = argparse.ArgumentParser(prog="yoke sample", usage=usage)
        parser.add_argument("--visible")
        return _helpers.parse_or_usage_error(parser, args, error_usage)

    with pytest.raises(AssertionError):
        assert_adapter_usage(monkeypatch, adapter, {("sample",): (None, adapter)})
