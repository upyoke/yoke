"""Handler registration for the lint-config enforcement-state read."""

from __future__ import annotations

from yoke_core.domain.handlers import lint_config_show as _lcs


def register(registry) -> None:
    registry.register(
        "lint.config.show", _lcs.handle_lint_config_show,
        _lcs.LintConfigShowRequest, _lcs.LintConfigShowResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.lint_config_show",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )


__all__ = ["register"]
