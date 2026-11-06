"""Runtime interface for merge item local runtime."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class MergeItemLocalRuntime(Protocol):
    """Operations and values supplied by the executing adapter."""

    LocalMergeGithubAuthorityError: type[Any]
    machine_github_user_authority: Callable[..., Any]


def get_merge_item_local_runtime() -> MergeItemLocalRuntime:
    return cast(MergeItemLocalRuntime, load_port("merge_item_local_runtime", MergeItemLocalRuntime))
