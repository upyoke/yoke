"""Done-means readiness rejects guard-blocked python3 -c prescriptions."""

from __future__ import annotations

from yoke_core.domain.idea_readiness_check_done_means import (
    CODE,
    verify_done_means_agent_shape,
)


def test_fenced_python_c_import_is_blocked():
    spec = (
        "## Done\n\n"
        "```bash\n"
        "yoke dev run -- python3 -c 'from yoke_core.domain.foo import bar'\n"
        "```\n"
    )
    issues = verify_done_means_agent_shape(spec)
    assert len(issues) == 1
    assert issues[0].code == CODE


def test_backticked_python_c_import_is_blocked():
    spec = "Verify with `python3 -c \"import yoke_core\"` after the change."
    issues = verify_done_means_agent_shape(spec)
    assert len(issues) == 1
    assert issues[0].code == CODE


def test_prose_mention_without_command_span_is_allowed():
    spec = (
        "Field-notes recorded that a python3 -c import of yoke_core "
        "was denied. Do not add a lint allowance."
    )
    assert verify_done_means_agent_shape(spec) == []


def test_permitted_yoke_subcommand_is_allowed():
    spec = (
        "## Done\n\n"
        "```bash\n"
        "yoke watch pytest -- runtime/api/domain/test_foo.py\n"
        "```\n"
    )
    assert verify_done_means_agent_shape(spec) == []
