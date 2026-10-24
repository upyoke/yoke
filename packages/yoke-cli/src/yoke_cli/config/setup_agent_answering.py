"""Checking an agent's answer against the screen it answers, then applying it.

Each answer goes through the same rules the wizard's own controls enforce: a
choice must be one of the screen's rows, a typed value runs the screen's own
validation and default, and a form takes ``<key>.<field>`` values. Secret
inputs never accept an answer. A rejected answer raises
:class:`SetupRefusal` before anything runs, so a refusal changes nothing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_cli.config import onboard_wizard_apply_prompts as apply_prompts
from yoke_cli.config.onboard_wizard_state import _View
from yoke_cli.config.setup_agent_response import yoke_executable
from yoke_cli.config.setup_prompt import (
    SetupPrompt,
    check_choice,
    check_field,
    check_input,
)

REVIEW_KEY = "review.confirm"
APPLY_CHOICE = "apply"
# Answers that run or redirect Apply count only in the invocation that gives
# them, so replaying stored answers never starts Apply on its own.
INVOCATION_ONLY_KEYS = frozenset(
    {
        REVIEW_KEY,
        apply_prompts.APPLY_FAILED_KEY,
        apply_prompts.APPLY_DIFFERENT_FOLDER_KEY,
    }
)


# Reopening the git installer is an action, not a choice to remember: a
# replayed answer waits on the installer this run already opened.
INVOCATION_ONLY_ANSWERS = frozenset(
    (key, "install")
    for key in (
        "project.project_git_install_handoff",
        "project.project_git_install_error",
        "project.clone_git_install_handoff",
        "project.clone_git_install_error",
    )
)


class SetupRefusal(Exception):
    """A named refusal plus its recovery, raised at the screen it concerns."""

    def __init__(self, reason: str, recovery: str, prompt: SetupPrompt | None) -> None:
        super().__init__(recovery)
        self.reason = reason
        self.recovery = recovery
        self.prompt = prompt


class AnswerFlow:
    """Validate and apply one screen's answers; stage them for the store."""

    def _answer_from_sources(self, view: _View) -> bool:
        """Answer from this command line, then the store, then ``--yes``."""
        prompt = view.prompt
        given = self._cli_for(prompt.key)
        if given:
            mode = self._answers.value(prompt.key)
            if prompt.fields and prompt.key not in given and mode is not None:
                given = {prompt.key: mode, **given}
            self._answer(view, given)
            return True
        # A form's mode switch redraws it, so a stored answer counts once per mode.
        marker = (
            prompt.key if prompt.selected is None else f"{prompt.key}@{prompt.selected}"
        )
        if marker in self._auto_answered or prompt.key in INVOCATION_ONLY_KEYS:
            return self._answer_preset(view)
        stored = self._answers.values_for(prompt.key)
        if not stored:
            return self._answer_preset(view)
        if prompt.fields and stored == {prompt.key: prompt.selected}:
            return False
        self._auto_answered.add(marker)
        try:
            self._answer(view, stored)
        except SetupRefusal:
            self._answers.drop(prompt.key)
            return False
        return True

    def _answer_preset(self, view: _View) -> bool:
        prompt = view.prompt
        if prompt.key != REVIEW_KEY or not self._apply_preset:
            return False
        if prompt.key in self._auto_answered:
            return False
        if APPLY_CHOICE not in {row.value for row in prompt.choices}:
            return False
        self._auto_answered.add(prompt.key)
        self._answer(view, {prompt.key: APPLY_CHOICE})
        return True

    def _cli_for(self, key: str) -> dict[str, str]:
        prefix = f"{key}."
        return {
            name: value
            for name, value in self._cli.items()
            if name == key or name.startswith(prefix)
        }

    def _answer(self, view: _View, values: dict[str, str]) -> None:
        prompt = view.prompt
        if prompt.input is not None:
            self._answer_input(view, values)
        elif prompt.fields:
            self._answer_form(view, values)
        else:
            self._answer_choice(view, values)

    def _answer_input(self, view: _View, values: dict[str, str]) -> None:
        prompt = view.prompt
        value = values.get(prompt.key)
        if value is None:
            raise _not_current(prompt)
        if prompt.input.password:
            raise _secret(prompt)
        text, error = check_input(prompt.input, value)
        if error:
            raise SetupRefusal("setup_answer_invalid", error, prompt)
        self._accept(prompt, {prompt.key: text}, used=[prompt.key])
        view.on_select(text)

    def _answer_choice(self, view: _View, values: dict[str, str]) -> None:
        prompt = view.prompt
        value = values.get(prompt.key)
        if value is None:
            raise _not_current(prompt)
        error = check_choice(prompt, value)
        if error:
            raise SetupRefusal("setup_answer_not_allowed", error, prompt)
        self._accept(prompt, {prompt.key: value}, used=[prompt.key])
        view.on_select(value)

    def _answer_form(self, view: _View, values: dict[str, str]) -> None:
        prompt = view.prompt
        choice = values.get(prompt.key)
        if choice is not None:
            error = check_choice(prompt, choice)
            if error:
                raise SetupRefusal("setup_answer_not_allowed", error, prompt)
            if prompt.selected is not None and choice != prompt.selected:
                # Switching the screen's mode redraws it; the field answers
                # wait for the redrawn screen.
                self._accept(prompt, {prompt.key: choice}, used=[prompt.key])
                view.on_select(choice)
                return
        submitted: dict[str, str] = {}
        for field in prompt.fields:
            name = f"{prompt.key}.{field.key}"
            if field.is_secret:
                raise _secret(prompt)
            text, error = check_field(field, values.get(name, ""))
            if error:
                raise SetupRefusal("setup_answer_invalid", f"{name}: {error}", prompt)
            submitted[field.key] = text
        staged = {f"{prompt.key}.{name}": text for name, text in submitted.items()}
        if choice is not None:
            staged[prompt.key] = choice
        self._accept(prompt, staged, used=[prompt.key, *staged])
        view.on_form(submitted)

    def _accept(
        self, prompt: SetupPrompt, staged: dict[str, str], *, used: list[str]
    ) -> None:
        for name in used:
            self._cli.pop(name, None)
        if prompt.key == apply_prompts.APPLY_FAILED_KEY:
            self._answers.apply_failure = None
        if prompt.key in INVOCATION_ONLY_KEYS:
            return
        if (prompt.key, staged.get(prompt.key)) not in INVOCATION_ONLY_ANSWERS:
            self._answers.stage(staged)

    def _done_fields(self) -> dict[str, Any]:
        report = getattr(self, "_applied_report", None)
        report = report if isinstance(report, dict) else {}
        summary = report.get("apply_report")
        changed = list((self.result.path_repair or {}).get("changed_files") or [])
        checkout = self.result.project_checkout
        next_steps = []
        if changed:
            next_steps.append(
                "Open a new terminal so the changed shell files take effect: "
                + ", ".join(changed)
            )
        readiness = f"{yoke_executable()} doctor run --session"
        in_checkout = bool(checkout) and _inside(Path.cwd(), Path(checkout))
        if in_checkout:
            next_steps.append(
                f"Check this session is ready: run `{readiness}` and give each "
                "failed check's next step to the person, then rerun it."
            )
        elif checkout:
            next_steps.append(f"Open Claude Code, Codex or Cursor in {checkout}.")
            next_steps.append(
                f"Check that session with `{readiness}` before taking its next action."
            )
        else:
            next_steps.append(
                "To add a project later, run `yoke setup --agent` again and "
                "choose the folder its code lives in."
            )
        setup = None
        if checkout:
            from yoke_cli.config.setup_facts_summary import read_project, next_line

            setup = read_project(checkout)
            action = setup["next_action"]
            if action:
                next_steps.append(
                    "After session readiness passes: " + next_line(action)
                )
            elif setup["lines"]:
                next_steps.extend(setup["lines"])
        return {
            "next_action": setup["next_action"] if setup else None,
            "detail": ([f"Run report: {self.report_path}"] if self.report_path else [])
            + [apply_prompts.CONCEPTS_GUIDANCE],
            "report": summary if isinstance(summary, dict) else None,
            "install_health": report.get("install_health"),
            "changed_files": changed,
            "next": next_steps,
            "guidance": (
                "Tell the person setup is done, show the install health result in "
                "full, and give them the next steps in order. Yoke never opens "
                "a new session for them."
            ),
        }


def _inside(path: Path, folder: Path) -> bool:
    try:
        return path.resolve().is_relative_to(folder.resolve())
    except OSError:
        return False


def _secret(prompt: SetupPrompt) -> SetupRefusal:
    return SetupRefusal(
        "setup_secret_answer_refused",
        "setup never takes a secret through --answer; take this question's "
        "non-secret route, or finish this step in a terminal with `yoke setup --tui`",
        prompt,
    )


def _not_current(prompt: SetupPrompt) -> SetupRefusal:
    return SetupRefusal(
        "setup_answer_not_current",
        f"answer {prompt.key} itself; its field answers alone do not answer it",
        prompt,
    )


__all__ = [
    "APPLY_CHOICE",
    "AnswerFlow",
    "INVOCATION_ONLY_ANSWERS",
    "INVOCATION_ONLY_KEYS",
    "REVIEW_KEY",
    "SetupRefusal",
]
