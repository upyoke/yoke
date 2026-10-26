"""Public CLI usage covers real parser actions and command paths."""

import re


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
