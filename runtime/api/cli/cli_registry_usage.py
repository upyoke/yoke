"""Usage comparisons shared by the registry contract audit."""

import argparse
import re

_FLAG = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]*)")
# The flag column of an options line: everything before the two-space gap
# that starts its help. Python 3.11 repeats the placeholder after each alias
# (``--item PREFIX-N, --candidate-item PREFIX-N``); 3.13 prints it once.
_OPTION = re.compile(r"\s{2}(-\S.*?)(?:\s{2,}|$)")


def _option_blocks(text: str) -> list[str]:
    """Lines of each argument group: a title line directly followed by options.

    Notes after the options may also hold indented flag recipes, but argparse
    never leaves a blank line between a group title and its first option.
    """
    lines = text.splitlines()
    blocks: list[str] = []
    for i, line in enumerate(lines[:-1]):
        if re.match(r"^\S.*:$", line) and lines[i + 1].startswith("  "):
            for option_line in lines[i + 1 :]:
                if not option_line.strip():
                    break
                blocks.append(option_line)
    return blocks


def _usage_drift(text: str) -> tuple[list[str], list[str]]:
    """Flags the options list has but the synopsis omits, and the reverse."""
    if "options:" not in text or "usage: yoke " not in text:
        return [], []
    head = text.split("options:", 1)[0]
    options = "\n".join(_option_blocks(text))
    usage = re.search(r"usage: (yoke .*?)(?:\n\s*\n|$)", head, re.S)
    if usage is None or "[options]" in usage.group(1):
        return [], []
    # Flags after a bare `--` pass through to another program, not this parser.
    own_usage = re.split(r"\s--(?:\s|$)", usage.group(1), maxsplit=1)[0]
    named = set(_FLAG.findall(own_usage)) - {"--help"}
    listed = {
        flag
        for line in options.splitlines()
        if (m := _OPTION.match(line))
        for flag in _FLAG.findall(m.group(1))
    } - {"--help"}
    return sorted(listed - named), sorted(named - listed)


def advertised_flags(usage):
    return set(
        re.findall(r"--[A-Za-z0-9][A-Za-z0-9-]*", re.sub(r"<[^<>]*>", " ", usage))
    )


def assert_adapter_usage(monkeypatch, adapter, routes) -> None:
    """Inspect real parsers and error recipes without executing commands."""
    import sys

    from yoke_cli.commands import _helpers

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

    for module in tuple(sys.modules.values()):
        if getattr(module, "__name__", "").startswith("yoke_cli.commands"):
            if getattr(module, "parse_or_usage_error", None) is original_parse:
                monkeypatch.setattr(module, "parse_or_usage_error", capture_error_usage)
    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", capture)
    monkeypatch.setattr(argparse.ArgumentParser, "parse_known_args", capture)
    commands = {"yoke " + " ".join(route) for route in routes}
    failures = []
    error_usages.clear()
    try:
        adapter(["--help"])
    except ParserCaptured as captured:
        parser = captured.parser
    else:
        # Delegated help has no argparse usage contract at this entrypoint.
        assert not error_usages, adapter
        return
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
            failures.append(f"{adapter.__name__}: missing={sorted(missing)}; {usage}")
    assert not failures, "\n".join(failures)
