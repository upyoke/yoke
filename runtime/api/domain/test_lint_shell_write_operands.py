"""Copy destinations and transparent source-runner write detection."""

import shlex

import pytest

from yoke_core.domain.lint_shell_write_operands import (
    copy_write_operands,
    source_run_argv,
)
from yoke_core.domain.lint_session_cwd_target_extract import resolve_shell_write_operands


@pytest.mark.parametrize("args", [
    "-t D s", "-tD s", "--target-directory D s",
    "--target-directory=D s", "-at D s", "-tDest s",
])
def test_explicit_target_directory(args):
    expected = "Dest" if args == "-tDest s" else "D"
    assert copy_write_operands(shlex.split(args)) == [expected]


@pytest.mark.parametrize("args", ["a b", "-D /tmp/a b", "-- a b"])
def test_last_positional_destination(args):
    assert copy_write_operands(shlex.split(args)) == ["b"]


@pytest.mark.parametrize("prefix", [
    "yoke dev run", "yoke --env prod dev run --lane L",
    "yoke dev run --allow-real-machine-home",
    "/bin/yoke --config config dev run",
])
def test_source_runner_exposes_local_argv(prefix):
    assert source_run_argv(shlex.split(prefix + " -- touch x")) == ["touch", "x"]


@pytest.mark.parametrize("command", ["yoke items get 1", "touch x", "yoke dev run"])
def test_other_commands_remain_unchanged(command):
    tokens = shlex.split(command)
    assert source_run_argv(tokens) == tokens


@pytest.mark.parametrize(("command", "target"), [
    ("cp -t D s", "D"), ("cp a b", "b"),
    ("yoke dev run -- touch x", "x"),
    ("env A=b yoke --env prod dev run -- env B=c touch x", "x"),
    ("cp -- -tD b", "b"),
])
def test_shared_write_operand_resolver(command, target):
    assert resolve_shell_write_operands(command) == ([target], False)
