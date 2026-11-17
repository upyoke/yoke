"""Collection-skipped modules retained by CI grouping and coverage manifests."""

_SKIPPED_MODULES: set[str] = set()


def pytest_sessionstart(session):
    _SKIPPED_MODULES.clear()


def pytest_collectreport(report):
    if report.skipped and report.nodeid.endswith(".py"):
        _SKIPPED_MODULES.add(report.nodeid)


def skipped_modules() -> tuple[str, ...]:
    return tuple(sorted(_SKIPPED_MODULES))
