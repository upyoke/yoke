"""Provider-specific argv for one Claude relay invocation."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Callable, Mapping

from yoke_contracts.session_control.launch_permission_bypass import (
    CLAUDE_BYPASS_ARGUMENTS,
)
from yoke_contracts.session_control.presentation import (
    CLAUDE_LOCAL_PRESENTATION,
    CLAUDE_REMOTE_CONTROL_SETTING,
)


@dataclass(frozen=True)
class ClaudeNativeInvocation:
    """One native command, its workspace, and the session it names.

    ``session_id`` is the conversation the native will run in — chosen by the
    relay on a create, and the target's own id on a wake. ``launch_id`` is the
    launch that asked for a create, and is what custody and the attestation are
    keyed on; a wake has no launch and leaves it unset.
    """

    executable: str
    cwd: Path
    session_id: str
    surface_version: str
    instruction: str = field(repr=False)
    resume: bool = False
    launch_id: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    presentation: str | None = None
    session_name: str | None = None
    launch_attestation: str | None = field(default=None, repr=False)
    progress_reporter: Callable[[Mapping[str, object]], bool] | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    @property
    def settings_arguments(self) -> tuple[str, ...]:
        if self.presentation != CLAUDE_LOCAL_PRESENTATION:
            return ()
        settings = json.dumps(
            {CLAUDE_REMOTE_CONTROL_SETTING: True},
            separators=(",", ":"),
        )
        return "--settings", settings

    @property
    def argv(self) -> tuple[str, ...]:
        arguments = [
            self.executable,
            "-p",
            *CLAUDE_BYPASS_ARGUMENTS,
            *self.settings_arguments,
        ]
        if self.resume:
            arguments.extend(("--resume", self.session_id))
        else:
            arguments.extend(("--session-id", self.session_id))
            if self.model:
                arguments.extend(("--model", self.model))
            if self.reasoning_effort:
                arguments.extend(("--effort", self.reasoning_effort))
            if self.session_name:
                arguments.extend(("--name", self.session_name))
        arguments.extend((self.instruction, "--output-format", "json"))
        return tuple(arguments)


__all__ = ["ClaudeNativeInvocation"]
