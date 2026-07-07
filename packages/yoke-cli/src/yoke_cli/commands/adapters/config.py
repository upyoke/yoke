"""Machine-config adapters for the ``yoke`` CLI."""

from __future__ import annotations

import argparse
from typing import List

from yoke_cli.commands._helpers import (
    attach_field_note_footer,
    parse_or_usage_error,
)
from yoke_cli.config import status as machine_config_status
from yoke_contracts.machine_config import schema as machine_config_contract


CONFIG_EXAMPLE_USAGE = "yoke config example"
STATUS_USAGE = "yoke status [--config PATH] [--repo-root PATH] [--env NAME] [--json]"


def config_example(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog=CONFIG_EXAMPLE_USAGE)
    attach_field_note_footer(parser)
    parsed = parse_or_usage_error(parser, args, CONFIG_EXAMPLE_USAGE)
    if parsed is None:
        return 2
    print(machine_config_contract.canonical_example_text(), end="")
    return 0


def status(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke status")
    parser.add_argument("--config", dest="config_path", default=None)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--env", dest="explicit_env", default=None)
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parse_or_usage_error(parser, args, STATUS_USAGE)
    if parsed is None:
        return 2
    report = machine_config_status.build_status(
        config_path=parsed.config_path,
        repo_root=parsed.repo_root,
        explicit_env=parsed.explicit_env,
    )
    if parsed.json_mode:
        print(machine_config_status.dumps_json(report), end="")
    else:
        print(machine_config_status.render_human(report), end="")
    return 0 if report.get("ok") else 1


__all__ = [
    "CONFIG_EXAMPLE_USAGE",
    "STATUS_USAGE",
    "config_example",
    "status",
]
