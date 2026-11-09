"""Full shell calls retain real path names while dropping closing syntax."""

import pytest

from yoke_contracts.hook_runner.shell_parse import parse_shell
from yoke_core.domain.lint_session_cwd_target_extract import (
    extract_command_targets,
    extract_payload_write_targets,
)
from yoke_core.domain.lint_shell_target_tokens import (
    path_target_from_token,
    resolve_path_operands,
)


@pytest.mark.parametrize("command, expected", [
    ("(cd /a/b && yoke agents render --target-root /x/lane)", ["/a/b", "/x/lane"]),
    ("(yoke agents render --target-root=/p/q)", ["/p/q"]),
    ("(touch /p/q)", ["/p/q"]),
    ("echo $(touch /p/q)", ["/p/q"]),
    ("((touch /p/q))", ["/p/q"]),
    ("(git -C /p/q status)", ["/p/q"]),
    ("(touch /p/q); echo done &", ["/p/q"]),
    ("(touch /p/q(name))", ["/p/q(name)"]),
    ("touch '/p/q)'", ["/p/q)"]),
    ('yoke agents render --target-root="/p/q)"', ["/p/q)"]),
    ('(yoke agents render --target-root "/p/q)")', ["/p/q)"]),
    (r"touch /p/q\)", ["/p/q)"]),
    ("touch '/p/q;&'", ["/p/q;&"]),
    ("root='/p/q)'; touch $root", ["/p/q)"]),
])
def test_full_command_paths(command, expected):
    assert extract_command_targets(command) == expected


@pytest.mark.parametrize("command, expected", [
    ("touch /p/q)", ["/p/q"]),
    ("git -C /p/q) add notes", ["/p/q"]),
    ("echo ok >/p/q)", ["/p/q"]),
    ("touch '/p/q)'", ["/p/q)"]),
    ('git -C "/p/q)" add notes', ["/p/q)"]),
    ("echo ok > '/p/q)'", ["/p/q)"]),
    ("echo ok >'/p/q)'", ["/p/q)"]),
    ("echo ok >'/p/q;&'", ["/p/q;&"]),
])
def test_write_operands_share_normalization(command, expected):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    assert extract_payload_write_targets(payload) == expected


@pytest.mark.parametrize("token, expected", [
    ("/p/q);&", "/p/q"),
    ("/p/q(name))", "/p/q(name)"),
    ("/p/q(name)", "/p/q(name)"),
    ("file:///p/q)", "/p/q"),
    ("$root)", "/p/q)"),
])
def test_shared_resolvers_normalize_before_expansion(token, expected):
    bindings = {"root": "/p/q)"}
    assert path_target_from_token(token, bindings) == expected
    assert resolve_path_operands([token], bindings) == ([expected], False)


def test_shell_word_stays_an_argv_string_with_literal_suffix_preserved():
    segment = parse_shell('touch "/p/q)" /p/q)').segments[0]
    assert segment.argv == ("touch", "/p/q)", "/p/q)")
    assert resolve_path_operands(list(segment.argv[1:]), {}) == (
        ["/p/q)", "/p/q"], False,
    )
