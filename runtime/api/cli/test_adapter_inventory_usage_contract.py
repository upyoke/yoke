"""Public CLI usage is the contract for structured adapter recipes."""

from __future__ import annotations

import re

from yoke_cli.commands.adapters.qa import (
    USAGE_BY_FUNCTION_ID as qa_write_usage,
)
from yoke_cli.commands.adapters.item_worktrees import (
    ITEM_WORKTREES_GET_USAGE,
    ITEM_WORKTREES_LIST_USAGE,
    ITEM_WORKTREES_PATH_RECORD_USAGE,
    ITEM_WORKTREES_RELEASE_USAGE,
)
from yoke_cli.commands.adapters.item_worktree_create import (
    ITEM_WORKTREES_CREATE_USAGE,
)
from yoke_cli.commands.adapters.qa_crud import QA_REQUIREMENT_ADD_USAGE
from yoke_cli.commands.adapters.qa_crud_batch import (
    QA_REQUIREMENT_ADD_BATCH_USAGE,
)
from yoke_cli.commands.adapters.qa_read import (
    QA_GATE_SUMMARY_USAGE,
    QA_REQUIREMENT_GET_USAGE,
    QA_REQUIREMENT_LIST_USAGE,
    QA_RUN_GET_USAGE,
    QA_RUN_LIST_USAGE,
)
from yoke_cli.commands.adapters.workflow_execution_instructions import (
    USAGE_BY_FUNCTION_ID as execution_instruction_usage,
)
from yoke_cli.commands.adapters.workflow_mechanics import (
    USAGE_BY_FUNCTION_ID as mechanics_usage,
)
from yoke_cli.commands.adapters.workflows_read import (
    WORKFLOWS_DEFINITION_GET_USAGE,
    WORKFLOWS_ITEM_GET_USAGE,
    WORKFLOWS_ITEM_MIGRATE_USAGE,
)
from yoke_cli.commands.adapters.workflows_item_posture import (
    WORKFLOWS_ITEM_POSTURE_AMEND_HELP,
    WORKFLOWS_ITEM_POSTURE_AMEND_USAGE,
)
from yoke_cli.commands.adapters.workflows_canon_help import (
    USAGE_BY_FUNCTION_ID as canon_usage,
)
from yoke_cli.commands.adapters.workflows_publication import (
    WORKFLOWS_VERSION_PUBLISH_USAGE,
)
from yoke_cli.commands.adapters.workflows_versions import (
    WORKFLOWS_CURRENT_SET_USAGE,
    WORKFLOWS_POLICY_DEFAULTS_PUBLISH_USAGE,
    WORKFLOWS_VERSION_GET_USAGE,
    WORKFLOWS_VERSION_LIST_USAGE,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_qa import (
    QA_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_items import (
    ITEMS_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_workflows import (
    WORKFLOW_ADAPTERS,
)
from yoke_core.domain.qa_method_definitions import BUILTIN_QA_METHODS


def test_workflow_inventory_matches_public_cli_usage() -> None:
    expected = {
        "workflows.version.publish": WORKFLOWS_VERSION_PUBLISH_USAGE,
        "workflows.definition.get": WORKFLOWS_DEFINITION_GET_USAGE,
        "workflows.version.get": WORKFLOWS_VERSION_GET_USAGE,
        "workflows.version.list": WORKFLOWS_VERSION_LIST_USAGE,
        "workflows.item.get": WORKFLOWS_ITEM_GET_USAGE,
        "workflows.current.set": WORKFLOWS_CURRENT_SET_USAGE,
        "workflows.policy_defaults.publish": (WORKFLOWS_POLICY_DEFAULTS_PUBLISH_USAGE),
        "workflows.item.migrate": WORKFLOWS_ITEM_MIGRATE_USAGE,
        "workflows.item_posture.amend": WORKFLOWS_ITEM_POSTURE_AMEND_USAGE,
        **mechanics_usage,
        **canon_usage,
        **execution_instruction_usage,
    }
    actual = {entry.function_id: entry.cli_invocation for entry in WORKFLOW_ADAPTERS}
    assert actual == expected


def test_converted_qa_inventory_matches_public_cli_usage() -> None:
    expected = {
        **qa_write_usage,
        "qa.requirement.list": QA_REQUIREMENT_LIST_USAGE,
        "qa.requirement.get": QA_REQUIREMENT_GET_USAGE,
        "qa.requirement.add": QA_REQUIREMENT_ADD_USAGE,
        "qa.requirement.add_batch": QA_REQUIREMENT_ADD_BATCH_USAGE,
        "qa.run.list": QA_RUN_LIST_USAGE,
        "qa.run.get": QA_RUN_GET_USAGE,
        "qa.gate_summary.run": QA_GATE_SUMMARY_USAGE,
    }
    actual = {
        entry.function_id: entry.cli_invocation
        for entry in QA_ADAPTERS
        if entry.function_id in expected
    }
    assert actual == expected


def test_item_worktree_inventory_matches_public_cli_usage() -> None:
    expected = {
        "item_worktrees.create": ITEM_WORKTREES_CREATE_USAGE,
        "item_worktrees.get": ITEM_WORKTREES_GET_USAGE,
        "item_worktrees.list": ITEM_WORKTREES_LIST_USAGE,
        "item_worktrees.path_record": ITEM_WORKTREES_PATH_RECORD_USAGE,
        "item_worktrees.release": ITEM_WORKTREES_RELEASE_USAGE,
    }
    actual = {
        entry.function_id: entry.cli_invocation
        for entry in ITEMS_ADAPTERS
        if entry.function_id in expected
    }
    assert actual == expected


def test_item_posture_amend_help_names_a_registered_verification_method() -> None:
    registered = {str(method["id"]) for method in BUILTIN_QA_METHODS}
    named = re.findall(
        r"--verification-method\s+(\S+)",
        WORKFLOWS_ITEM_POSTURE_AMEND_HELP,
    )
    assert named
    assert all(method_id in registered for method_id in named)
    assert "implementation_review" not in WORKFLOWS_ITEM_POSTURE_AMEND_HELP


def test_every_yoke_inventory_recipe_matches_its_cli_usage() -> None:
    """A ``yoke ...`` recipe in any inventory equals the CLI's own usage line.

    Legacy ``python3 -m ...`` rows stay: a lint maps those old module
    invocations to the command that replaced them.
    """
    from yoke_cli.commands.adapters.usage import ADAPTER_USAGE
    from yoke_core.api.service_client_structured_api_adapter_inventory import (
        all_adapter_entries,
    )

    stale = {
        entry.function_id: (entry.cli_invocation, ADAPTER_USAGE[entry.function_id])
        for entry in all_adapter_entries()
        if entry.function_id in ADAPTER_USAGE
        and entry.cli_invocation.startswith("yoke ")
        and entry.cli_invocation != ADAPTER_USAGE[entry.function_id]
    }
    assert not stale, stale


def test_every_adapter_usage_covers_its_parser(monkeypatch) -> None:
    """Inspect real parsers and error recipes without executing commands."""
    import argparse
    import sys

    from yoke_cli.commands import _helpers
    from yoke_cli.commands.command_tree import command_routes

    class ParserCaptured(BaseException):
        def __init__(self, parser):
            self.parser = parser

    def capture(parser, *args, **kwargs):
        raise ParserCaptured(parser)

    original_parse = _helpers.parse_or_usage_error
    error_usages = set()

    def capture_error_usage(parser, args, usage):
        error_usages.add(usage)
        return original_parse(parser, args, usage)

    routes = command_routes()
    for module in tuple(sys.modules.values()):
        if getattr(module, "__name__", "").startswith("yoke_cli.commands"):
            if getattr(module, "parse_or_usage_error", None) is original_parse:
                monkeypatch.setattr(module, "parse_or_usage_error", capture_error_usage)
    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", capture)
    monkeypatch.setattr(argparse.ArgumentParser, "parse_known_args", capture)
    commands = {"yoke " + " ".join(route) for route in routes}
    adapters = {
        adapter
        for _, adapter in routes.values()
        if adapter.__module__.startswith("yoke_cli.commands.adapters.")
    }
    failures = []
    for adapter in sorted(adapters, key=lambda adapter: adapter.__name__):
        error_usages.clear()
        try:
            adapter(["--help"])
        except ParserCaptured as captured:
            parser = captured.parser
        else:
            # Delegated help has no argparse usage contract at this entrypoint.
            assert not error_usages, adapter
            continue
        usages = error_usages | ({parser.usage} if parser.usage is not None else set())
        flags = {
            option
            for action in parser._actions
            if action.help != argparse.SUPPRESS
            and not isinstance(action, argparse._HelpAction)
            for option in action.option_strings
        }
        accepted_commands = {
            "yoke " + " ".join(route)
            for route, (_, candidate) in routes.items()
            if candidate is adapter
        }
        if parser.prog in commands:
            accepted_commands.add(parser.prog)
        for usage in sorted(usages):
            missing = flags - set(re.findall(r"(?<![\w-])--?[\w-]+", usage))
            prefix = re.match(r"yoke(?: [a-z][a-z0-9-]*)*", usage)
            named_command = prefix.group() if prefix else ""
            if missing or named_command not in accepted_commands:
                failures.append(
                    f"{adapter.__name__}: missing={sorted(missing)}; {usage}"
                )
    assert not failures, "\n".join(failures)


def test_usage_audit_checks_shared_flags_hidden_flags_and_command_paths(monkeypatch):
    import argparse

    import pytest

    from yoke_cli.commands import _helpers, command_tree

    def adapter(args):
        parser = argparse.ArgumentParser(prog="yoke example run", usage=usage)
        parser.add_argument("-f", "--flag", help="Public option.")
        parser.add_argument("--internal", help=argparse.SUPPRESS)
        _helpers.add_session_arg(parser)
        return _helpers.parse_or_usage_error(parser, args, usage)

    adapter.__module__ = "yoke_cli.commands.adapters.example"
    monkeypatch.setattr(
        command_tree,
        "command_routes",
        lambda: {("example", "run"): (None, adapter)},
    )
    cases = [
        ("yoke example run [-f F] [--flag F] [--session-id S]", None),
        ("yoke example run [-f F] [--flag F]", "--session-id"),
        ("yoke example run [-f F] [--flagged F] [--session-id S]", "--flag"),
        ("yoke example retired [-f F] [--flag F] [--session-id S]", "retired"),
    ]
    for usage, expected in cases:
        with pytest.MonkeyPatch.context() as audit_patch:
            if expected is None:
                test_every_adapter_usage_covers_its_parser(audit_patch)
            else:
                with pytest.raises(AssertionError, match=expected):
                    test_every_adapter_usage_covers_its_parser(audit_patch)
