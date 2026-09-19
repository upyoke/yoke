"""Hosted-release workflow contract: the suites that read those files off disk.

WHY: a workflow file has no import edge to anything. The suites that assert
its shape find it by path and read it, so only a declared contract selects
them when it changes — and the declaration has to follow *reading*, not
mentioning. A suite that merely names a workflow inside a flow definition
never opens the file and cannot notice it changing; listing it would buy
runtime and no coverage.

The two consumer-compatibility suites earn their place the hard way. A shell
continuation left flush against the margin ended a step's YAML block scalar,
so the workflow stopped parsing before any step could run — and because
neither reader was declared here, the break surfaced in whichever unrelated
shard happened to load the file next, two rounds of red CI away from the
change that caused it.
"""

from __future__ import annotations


HOSTED_RELEASE_WORKFLOW_PATHS = frozenset(
    {
        ".github/workflows/platform-release-bridge.yml",
        ".github/workflows/yoke-release.yml",
    }
)

HOSTED_RELEASE_WORKFLOW_CONTRACT_TESTS = (
    "runtime/api/domain/test_platform_release_bridge_workflow.py",
    "runtime/api/domain/test_release_notes_workflow.py",
    "runtime/api/tools/test_consumer_compatibility_advisory.py",
    "runtime/api/tools/test_require_platform_consumer_compatibility.py",
)


__all__ = [
    "HOSTED_RELEASE_WORKFLOW_CONTRACT_TESTS",
    "HOSTED_RELEASE_WORKFLOW_PATHS",
]
