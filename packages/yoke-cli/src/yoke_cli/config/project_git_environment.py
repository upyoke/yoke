"""Sanitized noninteractive environment for onboarding git subprocesses."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
import tempfile
from typing import Mapping

from yoke_cli.config.project_onboard_support import ProjectOnboardError


_EPHEMERAL_CONFIG_PREFIXES = ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")
_EPHEMERAL_CONFIG_KEYS = (
    "GIT_CONFIG", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS",
)
_REPOSITORY_ROUTING_ENV = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_NAMESPACE",
    "GIT_EXEC_PATH",
    "GIT_TEMPLATE_DIR",
    "GIT_GRAFT_FILE",
    "GIT_SHALLOW_FILE",
    "GIT_REPLACE_REF_BASE",
    "GIT_SSH",
    "GIT_SSH_VARIANT",
    "GIT_PROXY_COMMAND",
)
_NETWORK_OVERRIDE_ENV = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "all_proxy", "no_proxy",
    "GIT_SSL_CAINFO", "GIT_SSL_CAPATH", "GIT_SSL_CERT", "GIT_SSL_KEY",
    "GIT_SSL_CERT_PASSWORD_PROTECTED", "SSL_CERT_FILE", "SSL_CERT_DIR",
    "CURL_CA_BUNDLE",
    "SSLKEYLOGFILE",
)
_NONINTERACTIVE_SSH = (
    "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new"
)


def non_interactive_git_env(
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return a prompt-free git environment with deterministic askpass/SSH."""

    env = dict(base if base is not None else os.environ)
    for key in _REPOSITORY_ROUTING_ENV:
        env.pop(key, None)
    for key in tuple(env):
        if key.startswith("GIT_TRACE") or key == "GIT_CURL_VERBOSE":
            env.pop(key, None)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = ""
    env["SSH_ASKPASS"] = ""
    env["SSH_ASKPASS_REQUIRE"] = "never"
    env["GIT_TRACE_REDACT"] = "1"
    # Git treats *any* non-empty GIT_SSL_NO_VERIFY value, including "0", as
    # disabling certificate verification.  Absence is the only safe default.
    env.pop("GIT_SSL_NO_VERIFY", None)
    env["GIT_SSH_COMMAND"] = _NONINTERACTIVE_SSH
    return env


@contextmanager
def isolated_network_git_env(
    entries: tuple[str, ...],
    *,
    base: Mapping[str, str] | None = None,
    allow_protocols: str | None = None,
):
    """Yield an owner-only, credential-empty environment for network Git.

    Persistent system/global Git config, ``~/.netrc``, repository-routing
    variables, hooks/templates, and tracing destinations must not influence a
    clone, fetch, push, or probe that may carry a short-lived GitHub token.
    Project-local config remains visible because push target validation reads it
    separately before this environment is used.
    """

    with tempfile.TemporaryDirectory(prefix="yoke-network-git-") as directory:
        root = Path(directory)
        hooks = root / "hooks"
        templates = root / "templates"
        hooks.mkdir(mode=0o700)
        templates.mkdir(mode=0o700)
        protected_entries = (
            *entries,
            f"core.hooksPath={hooks}",
            f"init.templateDir={templates}",
            "trace2.eventTarget=",
            "trace2.normalTarget=",
            "trace2.perfTarget=",
            "trace2.configParams=",
            "trace2.envVars=",
        )
        env = git_config_env(protected_entries, base=base)
        for key in _REPOSITORY_ROUTING_ENV:
            env.pop(key, None)
        for key in _NETWORK_OVERRIDE_ENV:
            env.pop(key, None)
        for key in tuple(env):
            if key.startswith("GIT_TRACE") or key == "GIT_CURL_VERBOSE":
                env.pop(key, None)
        env["GIT_TRACE_REDACT"] = "1"
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        env["GIT_CONFIG_SYSTEM"] = os.devnull
        env["GIT_CONFIG_GLOBAL"] = os.devnull
        env["GIT_ATTR_NOSYSTEM"] = "1"
        env["HOME"] = directory
        env["XDG_CONFIG_HOME"] = directory
        if allow_protocols:
            env["GIT_ALLOW_PROTOCOL"] = allow_protocols
        else:
            env.pop("GIT_ALLOW_PROTOCOL", None)
        yield env


def git_config_env(
    entries: tuple[str, ...],
    *,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Rebuild ephemeral Git config from only the caller's allowlisted entries."""

    env = non_interactive_git_env(base)
    for key in tuple(env):
        if key in _EPHEMERAL_CONFIG_KEYS or key.startswith(
            _EPHEMERAL_CONFIG_PREFIXES
        ):
            env.pop(key, None)
    for index, entry in enumerate(entries):
        key, separator, value = entry.partition("=")
        if not separator or not key:
            raise ProjectOnboardError(f"invalid ephemeral git config: {entry!r}")
        env[f"GIT_CONFIG_KEY_{index}"] = key
        env[f"GIT_CONFIG_VALUE_{index}"] = value
    env["GIT_CONFIG_COUNT"] = str(len(entries))
    return env


__all__ = [
    "git_config_env",
    "isolated_network_git_env",
    "non_interactive_git_env",
]
