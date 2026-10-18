def _publication_error(
    *,
    kind: str,
    version: str,
    origin: str,
    detail: str,
) -> InstallError:
    safe_origin = _safe_url(origin)
    safe_detail = _sanitize_diagnostic(detail)
    if kind == "unpublished":
        return InstallError(
            "installer_release_unpublished: "
            f"Yoke {version} is not published at {safe_origin} ({safe_detail}); "
            f"publish Yoke {version} at {safe_origin}, or correct the requested "
            "version, then rerun the installer"
        )
    return InstallError(
        "installer_release_unverified: "
        f"could not confirm Yoke {version} is published at {safe_origin} "
        f"({safe_detail}); restore access to {safe_origin} and rerun the installer"
    )


def _iter_exceptions(exc: BaseException):
    seen: set[int] = set()
    stack = [exc]
    while stack:
        current = stack.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        cause = current.__cause__
        if isinstance(cause, BaseException):
            stack.append(cause)
        reason = getattr(current, "reason", None)
        if isinstance(reason, BaseException):
            stack.append(reason)


def _publication_fetch_error(
    version: str, origin: str, exc: BaseException
) -> InstallError:
    for item in _iter_exceptions(exc):
        if isinstance(item, urllib.error.HTTPError):
            kind = "unpublished" if item.code in {404, 410} else "unverified"
            return _publication_error(
                kind=kind,
                version=version,
                origin=origin,
                detail=f"HTTP {item.code}",
            )
    for item in _iter_exceptions(exc):
        if "SSL" in type(item).__name__:
            return _publication_error(
                kind="unverified",
                version=version,
                origin=origin,
                detail="TLS error",
            )
    return _publication_error(
        kind="unverified",
        version=version,
        origin=origin,
        detail=_sanitize_diagnostic(str(exc)),
    )


def _format_command_failure(
    command: Sequence[str],
    result: subprocess.CompletedProcess[str],
) -> str:
    safe_command = _bounded_diagnostic(" ".join(command), DIAGNOSTIC_MAX_CHARS)
    safe_stdout = _bounded_diagnostic(result.stdout or "", DIAGNOSTIC_MAX_CHARS)
    safe_stderr = _bounded_diagnostic(result.stderr or "", DIAGNOSTIC_MAX_CHARS)
    return (
        "Yoke dependency resolution uses the configured Yoke package index "
        f"and public PyPI ({PYPI_INDEX_URL}).\n"
        f"command failed with {result.returncode}: {safe_command}\n"
        f"stdout:\n{safe_stdout}\n"
        f"stderr:\n{safe_stderr}"
    )


def _bounded_diagnostic(value: str, limit: int) -> str:
    safe = _sanitize_diagnostic(value)
    if len(safe) <= limit:
        return safe
    return f"<earlier output omitted>\n{safe[-limit:]}"


def _sanitize_diagnostic(value: str) -> str:
    """Remove URL credentials/query material from operator-visible text."""

    return _URL_RE.sub(lambda match: _safe_url(match.group(0)), value)


def _safe_url(value: str) -> str:
    raw = str(value or "")
    try:
        parsed = urllib.parse.urlsplit(raw)
    except ValueError:
        return "<redacted-url>"
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return raw
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    try:
        port = parsed.port
    except ValueError:
        port = None
    netloc = f"{host}:{port}" if port is not None else host
    return urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").lower() in {"1", "true", "yes", "y"}
