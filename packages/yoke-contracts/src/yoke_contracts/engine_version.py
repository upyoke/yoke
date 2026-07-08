"""Engine-version handshake between Yoke servers and clients.

The server advertises the engine version it runs — in the health payload
and as a response header on API responses — and clients compare it against
their own installed version, warning once per process on skew. The
handshake never blocks: the function-call and health endpoints are
compatibility surfaces, and version skew is expected during rollouts.

Versions come from setuptools-scm dist metadata (one repository version
shared by every Yoke distribution built together), read via
``importlib.metadata``. A process running from a source tree with no
installed dist metadata resolves to ``""``, which disables advertising
and comparison gracefully.

Container builds also carry a baked source SHA. If setuptools-scm could
not see SCM metadata during that build, the wheel metadata falls back to
the configured fallback version. That value is not a comparable engine
version, so servers with a build SHA suppress it and let the health
payload's ``build`` field carry code identity instead.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _dist_version

#: Response header carrying the server's engine version on API responses.
ENGINE_VERSION_HEADER = "X-Yoke-Engine-Version"

#: The engine distribution — the server runtime.
ENGINE_DISTRIBUTION_NAME = "yoke-core"

#: The client CLI distribution; released in lockstep with the engine from
#: one repository version, so it is a valid skew-comparison base on
#: installs that carry no engine.
CLIENT_DISTRIBUTION_NAME = "yoke-cli"

#: setuptools-scm fallback used when a build has neither SCM nor archive
#: metadata. It is deliberately not advertised by image-built servers.
UNRESOLVED_SCM_FALLBACK_VERSION = "0.1.0"


def _installed_version(distribution: str) -> str:
    try:
        return _dist_version(distribution)
    except PackageNotFoundError:
        return ""


def installed_engine_version() -> str:
    """Version of the installed engine distribution, ``""`` when absent.

    Absent means the process runs from a source tree without installed
    dist metadata; callers degrade to "no version advertised".
    """
    return _installed_version(ENGINE_DISTRIBUTION_NAME)


def advertised_engine_version(*, build: str = "") -> str:
    """Engine version worth advertising to remote clients.

    A container image with ``build`` set but dist metadata at the SCM
    fallback ran current code from a source snapshot whose version could
    not be resolved at wheel-build time. Advertising that fallback makes
    clients report false skew, so the server treats it like missing
    metadata and omits the handshake value.
    """
    version = installed_engine_version()
    if build and version == UNRESOLVED_SCM_FALLBACK_VERSION:
        return ""
    return version


def local_handshake_version() -> str:
    """The version this process compares against a server's engine version.

    Prefers the installed engine dist; a client-only install (https
    transport, no engine) falls back to the CLI dist. ``""`` disables the
    comparison.
    """
    return installed_engine_version() or _installed_version(
        CLIENT_DISTRIBUTION_NAME
    )


__all__ = [
    "advertised_engine_version",
    "CLIENT_DISTRIBUTION_NAME",
    "ENGINE_DISTRIBUTION_NAME",
    "ENGINE_VERSION_HEADER",
    "installed_engine_version",
    "local_handshake_version",
    "UNRESOLVED_SCM_FALLBACK_VERSION",
]
