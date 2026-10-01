"""Give browser setup the terminal while Linux onboarding checks OS libraries."""

from yoke_cli.config.onboard_machine_setup import BROWSER_SETUP_ACTION


def browser_terminal_progress(app, action: str, status: str) -> None:
    if action != BROWSER_SETUP_ACTION:
        return
    if status == "running":
        context = app.suspend()
        context.__enter__()
        app._browser_terminal_context = context
    elif status in {"done", "failed"}:
        context = getattr(app, "_browser_terminal_context", None)
        if context is not None:
            app._browser_terminal_context = None
            context.__exit__(None, None, None)
