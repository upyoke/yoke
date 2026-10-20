"""Headless setup shell: the wizard's own steps, asked one question at a time.

:class:`AgentSetup` composes the exact flow list the Textual wizard composes
(:data:`onboard_wizard_flows.SETUP_FLOWS`) and supplies the shell primitives
those flows call — ``_goto``, ``_replace_current``, ``_run_checking``,
``run_worker`` and the rest — without a terminal. Presenting a screen either
answers it (an answer given on this command line, then a stored one, then a
preset) or stops and prints it as the one waiting question. Checks run in
line, browser steps are printed for the person and never opened, a browser
approval ends the call and resumes on the next one (:mod:`setup_agent_approvals`),
steps that already changed the machine are read back from the run facts in the
store (:mod:`setup_run_facts`), and every outcome is one JSON line from
:mod:`setup_agent_response`.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import sys
from typing import Any, Callable

from yoke_cli.config import onboard_wizard_apply_prompts as apply_prompts
from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config import setup_agent_answers as answers
from yoke_cli.config import setup_agent_response as responses
from yoke_cli.config.onboard_wizard_flows import SETUP_FLOWS, init_setup_state
from yoke_cli.config.onboard_wizard_state import CopyTarget, _View
from yoke_cli.config.setup_agent_answering import REVIEW_KEY, AnswerFlow, SetupRefusal
from yoke_cli.config.setup_agent_approvals import (
    MACHINE_KEY,
    AgentApprovals,
    ApprovalPending,
)
from yoke_cli.config.setup_prompt import SetupHuman, SetupPrompt
from yoke_cli.config.setup_run_facts import RunFacts


class _StepFailed(RuntimeError):
    """The flow reached a screen that asks nothing and leads nowhere."""


class AgentShell(AgentApprovals, AnswerFlow):
    """Shell primitives the setup flows call, implemented without Textual."""

    opens_browser = False

    def _start_front(self) -> None:
        _progress("Checking install…")
        self._checking = self._checking_blocks_quit = True
        self._finish_install(*self._check_install())

    # ── flow control ────────────────────────────────────────

    def _goto(self, view: _View) -> None:
        self._history.append(view)
        self._render_current()

    def _replace_current(self, view: _View) -> None:
        if self._history:
            self._history[-1] = view
        else:
            self._history.append(view)
        self._render_current()

    def _render_current(self) -> None:
        self._next = self._present_current

    def _step_back(self) -> None:
        if not self._applying and len(self._history) > 1:
            self._history.pop()
            self._render_current()

    def exit(self, *_args: Any, **_kwargs: Any) -> None:
        self._exited = True
        self._next = None

    def run_worker(self, work: Any, **_kwargs: Any) -> None:
        if inspect.iscoroutine(work):
            asyncio.run(work)
        else:
            work()

    def call_from_thread(
        self, fn: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> Any:
        return fn(*args, **kwargs)

    def call_after_refresh(self, fn: Callable[..., Any], *args: Any) -> None:
        fn(*args)

    def suspend(self) -> contextlib.AbstractContextManager:
        return contextlib.nullcontext()

    def _run_checking(
        self,
        *,
        step: str,
        title: str,
        message: str,
        work: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_error: Callable[[BaseException], None],
        detail_lines: list[str] | None = None,
        group: str = "onboard-check",
        replace_current: bool = False,
        blocks_quit: bool = False,
        on_cancel: Callable[[], None] | None = None,
        copy_targets: tuple[CopyTarget, ...] = (),
        human: SetupHuman | None = None,
    ) -> None:
        if replace_current and self._history:
            self._history.pop()
        _progress(f"{title} {message}")

        def finish() -> None:
            try:
                result = work()
            except ApprovalPending:
                return  # the browser step is this call's outcome
            except Exception as exc:  # noqa: BLE001 - each check names its error route
                on_error(exc)
                return
            on_success(result)

        self._next = finish

    # ── browser steps ───────────────────────────────────────

    def _show_browser(self, step: str, key: str, human: SetupHuman) -> None:
        marker = human.url or human.instructions
        if marker in self._browser_shown:
            return
        self._browser_shown.add(marker)
        responses.emit(responses.browser(step, key, human))

    def show_browser_step(self, line: str, targets: tuple[CopyTarget, ...]) -> None:
        url = next((t.value for t in targets if t.is_url), None)
        code = next((t.value for t in targets if not t.is_url), None)
        current = self._history[-1].prompt if self._history else None
        self._show_browser(
            current.step if current else "github",
            current.key if current else "github.machine",
            SetupHuman(instructions=line, url=url, user_code=code),
        )

    # ── Apply ───────────────────────────────────────────────

    def _start_apply(self) -> None:
        self._answers.flush(waiting_key=REVIEW_KEY)
        super()._start_apply()

    def _set_apply_step_status(self, action: str, target: str, status: str) -> None:
        step = self._match_apply_step(action, target)
        if step is None:
            return
        step["status"] = status
        if status in {"running", "failed"}:
            _progress(steps.apply_step_line(step))


class AgentSetup(AgentShell, *SETUP_FLOWS):
    """One agent-mode invocation over the shared setup flows."""

    def __init__(
        self,
        *,
        defaults: Any,
        apply_report: Callable[..., Any],
        store: answers.AnswerStore,
        cli_answers: dict[str, str],
    ) -> None:
        init_setup_state(
            self,
            defaults=defaults,
            apply_report=apply_report,
            run_facts=RunFacts(store.facts, on_change=store.keep_facts),
        )
        self._answers = store
        self._cli = dict(cli_answers)
        self._pending_refusal: tuple[str, str] | None = None
        waiting = store.waiting_key
        if waiting and any(not _belongs(key, waiting) for key in self._cli):
            self._cli = {}
            self._pending_refusal = (
                "setup_answer_not_current",
                "answer the current question shown here, by its key",
            )
        self._apply_preset = bool(defaults.apply)
        self._next: Callable[[], None] | None = None
        self._exited = False
        self._final: dict[str, Any] | None = None
        self._auto_answered: set[str] = set()
        self._browser_shown: set[str] = set()
        self._diverted = False

    def run(self) -> int:
        """Walk to the next question or outcome, print it, and return the exit code."""
        current: SetupPrompt | None = None
        try:
            self._start_front()
            while self._next is not None and self._final is None:
                step, self._next = self._next, None
                current = self._history[-1].prompt if self._history else current
                step()
            if self._final is None:
                self._finish_stopped()
        except SetupRefusal as refusal:
            if refusal.prompt is not None:
                # The repeated question's printed answer must be the next one accepted.
                self._answers.wait_at(refusal.prompt.key)
            self._final = responses.refused(
                refusal.reason, refusal.recovery, refusal.prompt
            )
        except KeyboardInterrupt:
            self._final = responses.interrupted(report_path=self.report_path)
        except Exception as exc:  # noqa: BLE001 - agent mode never prints a traceback
            self._final = self._step_failed(exc, current)
        responses.emit(self._final)
        return responses.EXIT_CODES[self.outcome]

    @property
    def outcome(self) -> str:
        return self._final["state"] if self._final else ""

    # ── presenting one screen ───────────────────────────────

    def _present_current(self) -> None:
        view = self._history[-1]
        prompt = view.prompt
        if prompt.key == apply_prompts.APPLY_DONE_KEY:
            self._finish_done()
            return
        if prompt.key == REVIEW_KEY and self._divert_to_apply_failure():
            return
        if self._answer_from_sources(view):
            return
        if prompt.key == apply_prompts.APPLY_FAILED_KEY:
            self._finish_apply_failed(prompt)
            return
        if prompt.key == MACHINE_KEY:
            view.on_select(prompt.choices[0].value)
            return
        if not prompt.answerable:
            said = [responses.plain(prompt.title), prompt.message, *prompt.detail_lines]
            raise _StepFailed(" ".join(text for text in said if text) or prompt.key)
        self._stop_at(prompt)

    def _divert_to_apply_failure(self) -> bool:
        failure = self._answers.apply_failure
        if not failure or self._diverted:
            return False
        self._diverted = True
        self._auto_answered.add(REVIEW_KEY)
        self.report_path = failure.get("report_path")
        self.last_error = failure.get("error")
        self.failed_step = failure.get("failed_step")
        self.resume_command = failure.get("resume_command")
        self._goto(self._apply_failure_view())
        return True

    # ── outcomes ────────────────────────────────────────────

    def _stop_at(self, prompt: SetupPrompt) -> None:
        self._refuse_unused_answers(prompt)
        self._answers.flush(waiting_key=prompt.key)
        self._final = responses.question(prompt)

    def _refuse_unused_answers(self, prompt: SetupPrompt) -> None:
        """Stopping with an answer left unused refuses at the stopping screen."""
        if self._cli or self._pending_refusal:
            reason, recovery = self._pending_refusal or (
                "setup_answer_not_current",
                "answer the current question shown here, by its key",
            )
            raise SetupRefusal(reason, recovery, prompt)

    def _finish_apply_failed(self, prompt: SetupPrompt) -> None:
        self._answers.apply_failure = {
            "report_path": self.report_path,
            "error": self.last_error,
            "failed_step": self.failed_step,
            "resume_command": self.resume_command,
        }
        self._answers.flush(waiting_key=prompt.key)
        self._final = responses.failed(
            "setup_apply_failed",
            "show the person the cause, then answer this question; resume "
            "continues the same run",
            report_path=self.report_path,
            failed_step=self.failed_step,
            **responses.question_fields(prompt),
        )

    def _finish_done(self) -> None:
        answers.discard()
        self._final = responses.response(responses.STATE_DONE, **self._done_fields())

    def _finish_stopped(self) -> None:
        if not self._exited:
            raise _StepFailed("setup stopped without asking a question")
        answers.discard()
        self._final = responses.response(
            responses.STATE_DONE,
            cancelled=True,
            detail=["Setup stopped at the person's choice; nothing more was applied."],
            next=["Run `yoke setup --agent` again to start over."],
        )

    def _step_failed(
        self, exc: BaseException, prompt: SetupPrompt | None
    ) -> dict[str, Any]:
        report = f" The run report is {self.report_path}." if self.report_path else ""
        cause = (
            str(exc) if isinstance(exc, _StepFailed) else f"{type(exc).__name__}: {exc}"
        )
        return responses.failed(
            "setup_step_failed",
            f"{cause.rstrip('.')}.{report} Fix the named cause, then run "
            "`yoke setup --agent` again to continue from the last answered question.",
            key=prompt.key if prompt else None,
            report_path=self.report_path,
        )


def _belongs(key: str, waiting_key: str) -> bool:
    return key == waiting_key or key.startswith(f"{waiting_key}.")


def _progress(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


__all__ = ["AgentSetup"]
