"""Where a persistent deployment's own served-revision proof is configured.

A release may only claim a registered environment is serving the candidate
if something asked the environment. Two facts make that question askable,
and both are already project authority rather than anything new: the
registered environment's own ``url``, which is the sole origin authorized
to answer for it, and an optional ``identity_path`` on the project's
``health-endpoint`` capability — the capability that already describes how
this project's persistent environments are interrogated.

The path is deliberately on that capability and not on the preview one:
a preview and a long-lived environment are different target classes with
different origins, so the preview's own path is no authority over a
persistent target. Same reader, different configuration.

Absence and failure are different answers here and stay different all the
way out to the refusal text. Most projects publish no such endpoint, and a
runtime that read an unset option as a broken one would refuse every
definition that never needed the proof; a capability that cannot be READ,
by contrast, is not evidence of absence, so it reports an error instead of
reporting "unconfigured" and letting an unprovable definition activate.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Dict, List

from yoke_core.domain import db_backend, json_helper
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.served_revision_probe import origin_relative_path_error

#: The capability that already describes how to interrogate this project's
#: persistent environments; the identity path is its optional sibling to
#: the liveness path it has always carried.
IDENTITY_CAPABILITY = "health-endpoint"
IDENTITY_PATH_KEY = "identity_path"

_HINT = (
    "set it via: yoke projects capability-merge-settings "
    f"<project> {IDENTITY_CAPABILITY} --set {IDENTITY_PATH_KEY}=/<path>"
)


@dataclass(frozen=True)
class ConfiguredIdentityPath:
    """The configured served-revision path, or why there is no answer.

    Exactly one of the three states holds: ``configured`` (a usable path),
    neither (this project publishes no proof, which is an answer), or
    ``error`` (the configuration could not be read or is unusable, which
    is not).
    """

    path: str = ""
    error: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.path) and not self.error


def identity_path_from_settings(settings: Any) -> ConfiguredIdentityPath:
    """Read the identity path out of one capability settings document.

    Accepts the stored JSON text or an already-decoded mapping, because
    both are live shapes: the table stores text and callers that already
    resolved a capability hold the mapping.
    """
    if isinstance(settings, str):
        if not settings.strip():
            return ConfiguredIdentityPath()
        try:
            settings = json_helper.loads_text(settings)
        except ValueError as exc:
            return ConfiguredIdentityPath(
                error=(
                    f"the {IDENTITY_CAPABILITY} capability settings are not "
                    f"readable JSON ({exc}), so whether this project can "
                    "prove a served revision is unknown rather than absent"
                )
            )
    if settings is None:
        return ConfiguredIdentityPath()
    if not isinstance(settings, Mapping):
        return ConfiguredIdentityPath(
            error=(
                f"the {IDENTITY_CAPABILITY} capability settings are a "
                f"{type(settings).__name__}, not an object, so no "
                f"{IDENTITY_PATH_KEY} can be read from them"
            )
        )
    path = str(settings.get(IDENTITY_PATH_KEY) or "").strip()
    if not path:
        return ConfiguredIdentityPath()
    shape_error = origin_relative_path_error(path)
    if shape_error:
        return ConfiguredIdentityPath(
            error=(
                f"the {IDENTITY_CAPABILITY} capability's {IDENTITY_PATH_KEY} "
                f"{path!r} {shape_error}; the origin comes from the "
                "registered environment's own url and this setting only "
                f"selects a path beneath it; {_HINT}"
            )
        )
    return ConfiguredIdentityPath(path=path)


def persistent_identity_path(conn: Any, project_id: int) -> ConfiguredIdentityPath:
    """The project's configured persistent served-revision path.

    A universe with no capability table at all configures nothing, which is
    the unconfigured answer rather than a read failure: there is no row to
    have failed to read. A table that is present and refuses its own read
    is a failure, and says so.
    """
    if not _table_exists(conn, "project_capabilities"):
        return ConfiguredIdentityPath()
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    try:
        row = conn.execute(
            "SELECT settings FROM project_capabilities "
            f"WHERE project_id={marker} AND type={marker}",
            (int(project_id), IDENTITY_CAPABILITY),
        ).fetchone()
    except Exception as exc:
        return ConfiguredIdentityPath(
            error=(
                f"the {IDENTITY_CAPABILITY} capability could not be read "
                f"({exc}), so whether this project can prove a served "
                "revision is unknown rather than absent"
            )
        )
    if row is None:
        return ConfiguredIdentityPath()
    return identity_path_from_settings(row[0])


def environment_urls(conn: Any, project_id: int, names: List[str]) -> Dict[str, str]:
    """The registered url of each named environment in this project.

    The url is the only origin authorized to answer for an environment, so
    it is read from the environment row rather than accepted from a
    caller. Names with no registered row are simply absent from the
    result; the caller that needed one refuses by its own words.
    """
    wanted = [name for name in dict.fromkeys(names) if name]
    if not wanted or not _table_exists(conn, "environments"):
        return {}
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    placeholders = ",".join(marker for _ in wanted)
    rows = conn.execute(
        "SELECT name,url FROM environments "
        f"WHERE project_id={marker} AND name IN ({placeholders})",
        (int(project_id), *wanted),
    ).fetchall()
    resolved: Dict[str, str] = {}
    for row in rows:
        name = str(row[0] or "")
        url = str(row[1] or "").strip()
        if name and url:
            resolved[name] = url
    return resolved


def qa_target_environment_names(stages: Any) -> List[str]:
    """Every environment a QA target in *stages* names, in order."""
    if isinstance(stages, str):
        stages = json_helper.loads_text(stages)
    if not isinstance(stages, list):
        return []
    names: List[str] = []
    for stage in stages:
        if not isinstance(stage, Mapping):
            continue
        target = stage.get("target")
        if not isinstance(target, Mapping):
            continue
        name = str(target.get("environment") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def identity_origin_for(target_identity: Any, environment: str) -> str:
    """The origin authorized to answer for *environment*, and no other.

    The projection is keyed by environment name precisely so that one
    environment's proof can never be read off another's host: a receipt
    records the environment it names, and the consumer requires that name
    to equal the QA target's, so the origin has to be selected by the same
    key or the evidence would vouch for a target it never touched.
    """
    if not isinstance(target_identity, Mapping) or not environment:
        return ""
    urls = target_identity.get("environment_urls")
    if not isinstance(urls, Mapping):
        return ""
    return str(urls.get(environment) or "")


def run_target_identity(
    conn: Any, *, project_id: int, stages: Any, target_environment: str = ""
) -> Dict[str, Any]:
    """The identity facts a release driver needs, resolved on the server.

    The driver runs the candidate build and probes over the network, but
    the configuration it probes with is control-plane authority, so it is
    resolved here — once, beside the run it belongs to — rather than read
    from the driver's own machine. ``error`` travels with it: a driver that
    cannot tell "unconfigured" from "unreadable" would deploy on the
    strength of a failed read.
    """
    configured = persistent_identity_path(conn, project_id)
    names = qa_target_environment_names(stages)
    if target_environment:
        names.append(target_environment)
    return {
        "identity_path": configured.path,
        "error": configured.error,
        "environment_urls": environment_urls(conn, project_id, names),
    }


__all__ = [
    "IDENTITY_CAPABILITY",
    "IDENTITY_PATH_KEY",
    "ConfiguredIdentityPath",
    "environment_urls",
    "identity_origin_for",
    "identity_path_from_settings",
    "persistent_identity_path",
    "qa_target_environment_names",
    "run_target_identity",
]
