"""Pure-function coverage for the lane-main-write command classifier.

The guard's integration tests own the deny/allow verdict; this sibling
module owns the classifier's own token walk so the integration file
stays under the repo's file-line cap.

Both cases here turn on the same fact: an operator written flush
against the token before it must still end that invocation. Tokenizing
the whole body with ``shlex`` alone glues the operator onto the
preceding word, so a compound reads as a single invocation and the
classifier answers for the leading command instead of for every
command the body actually runs.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.lint_lane_main_write_classify import (
    is_yoke_adapter_command,
)


@pytest.mark.parametrize("command", [
    "yoke items get YOK-1",
    "yoke items get YOK-1; yoke items get YOK-2",
    "yoke items get YOK-1 ; yoke items get YOK-2",
    "yoke items get YOK-1 && yoke lifecycle transition YOK-1 --to done",
])
def test_every_segment_is_a_yoke_adapter(command):
    assert is_yoke_adapter_command(command)


@pytest.mark.parametrize("command", [
    "yoke items get YOK-1; rm -rf /tmp/scratch",
    "yoke items get YOK-1 ; rm -rf /tmp/scratch",
    "yoke items get YOK-1 && git commit -am wip",
    "rm -rf /tmp/scratch; yoke items get YOK-1",
])
def test_a_non_adapter_segment_disqualifies_the_command(command):
    assert not is_yoke_adapter_command(command)


def test_empty_command_is_not_an_adapter_command():
    assert not is_yoke_adapter_command("")
    assert not is_yoke_adapter_command("   ")
