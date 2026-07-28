"""Machine state checks in the installer Machine QA plan."""

from __future__ import annotations

from yoke_core.domain.installer_campaign_plan_common import (
    DUAL_HOST_BASELINES,
    FRESH_HOST,
    SHELL_PRECONFIGURED,
    machine_case,
)


def _shell_assertion(command: str) -> dict[str, object]:
    return {"argv": ["/bin/zsh", "-c", command]}


def _login_assertion(command: str) -> dict[str, object]:
    return {"argv": ["/bin/zsh", "-lic", command]}


PATH_ON_SHELL = machine_case(
    1,
    "path-on-shell",
    instructions=(
        "After reaching each registered host baseline, inspect both login and "
        "SSH-command shell resolution for the branch-determining yoke PATH state."
    ),
    expected_outcome=(
        "A fresh host does not resolve yoke on either shell surface; a "
        "shell-preconfigured host resolves a working yoke on both surfaces."
    ),
    method_config={
        "baseline_configs": {
            FRESH_HOST: {
                "assertions": [
                    _login_assertion("! command -v yoke >/dev/null"),
                    _shell_assertion("! command -v yoke >/dev/null"),
                ]
            },
            SHELL_PRECONFIGURED: {
                "assertions": [
                    _login_assertion(
                        "command -v yoke >/dev/null && yoke --version >/dev/null"
                    ),
                    _shell_assertion(
                        "command -v yoke >/dev/null && yoke --version >/dev/null"
                    ),
                ]
            },
        }
    },
    host_baselines=DUAL_HOST_BASELINES,
)


TOKEN_PERMS = machine_case(
    9,
    "token-perms",
    instructions=(
        "Inspect the real browser-approved Yoke token files left by the hosted "
        "journey without reading or printing their contents."
    ),
    expected_outcome=(
        "At least one hosted token file exists under the owner-only secrets "
        "directory, the directory mode is 700, and every token file mode is 600."
    ),
    method_config={
        "assertions": [
            _shell_assertion(
                "set -eu; "
                'files=("$HOME"/.yoke/secrets/*.token(N)); '
                "(( ${#files[@]} > 0 )); "
                "[[ $(/usr/bin/stat -f '%Lp' \"$HOME/.yoke/secrets\") == 700 ]]; "
                'for file in "${files[@]}"; do '
                "[[ $(/usr/bin/stat -f '%Lp' \"$file\") == 600 ]]; "
                "done"
            )
        ]
    },
)


UNIVERSE_BORN = machine_case(
    10,
    "universe-born",
    instructions=(
        "Inspect the local universe created or verified by apply-handoff using "
        "the installed product status surface and its owner-only DSN reference."
    ),
    expected_outcome=(
        "The embedded local-universe Postgres reports running and its Yoke-owned "
        "DSN file exists with mode 600."
    ),
    method_config={
        "assertions": [
            _login_assertion(
                "yoke local-postgres status --json | "
                "/usr/bin/grep -q '\"running\": true'"
            ),
            _shell_assertion(
                '[[ -f "$HOME/.yoke/secrets/local.dsn" ]] && '
                "[[ $(/usr/bin/stat -f '%Lp' "
                '"$HOME/.yoke/secrets/local.dsn") == 600 ]]'
            ),
        ]
    },
)


MACHINE_STATE_CASES = (
    PATH_ON_SHELL,
    TOKEN_PERMS,
    UNIVERSE_BORN,
)


__all__ = [
    "MACHINE_STATE_CASES",
    "PATH_ON_SHELL",
    "TOKEN_PERMS",
    "UNIVERSE_BORN",
]
