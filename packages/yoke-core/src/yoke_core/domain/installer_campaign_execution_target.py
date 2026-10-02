"""Fill the installer campaign template from one QA execution target."""

from __future__ import annotations

import re
from typing import Any, Mapping

from yoke_core.domain.installer_campaign_current_text_cases import (
    CURRENT_TEXT_INSTALLER_CAMPAIGN_CASES,
)
from yoke_core.domain.environment_declared_facts import target_is_production
from yoke_core.domain.qa_execution_environment_target import require_case_target


_TEMPLATE_FIELD = re.compile(r"\{\{([a-z_]+)\}\}")


def _fill_template(value: Any, fields: Mapping[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: _fill_template(child, fields) for key, child in value.items()}
    if isinstance(value, list):
        return [_fill_template(child, fields) for child in value]
    if isinstance(value, str):

        def substitute(match: re.Match[str]) -> str:
            try:
                return fields[match[1]]
            except KeyError:
                raise ValueError(
                    f"installer_campaign_template_field_unknown: {match[1]}; "
                    "add its value to the plan target binding or correct the template."
                ) from None

        return _TEMPLATE_FIELD.sub(substitute, value)
    return value


def installer_campaign_cases_for_target(
    target: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return concrete cases filled only from the plan's bound environment."""
    endpoints = target["endpoints"]
    app_url = str(endpoints["app_url"])
    fields = {
        "app_url": app_url,
        "installer_base_url": str(endpoints["installer_base_url"]),
        "release_channel": str(endpoints["release_channel"]),
        "environment_display_name": (
            "Production"
            if target_is_production(target)
            else str(target["environment"]["name"]).title()
        ),
    }
    cases = _fill_template(list(CURRENT_TEXT_INSTALLER_CAMPAIGN_CASES), fields)
    for case in cases:
        require_case_target(case, target)
    return cases


__all__ = ["installer_campaign_cases_for_target"]
