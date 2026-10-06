"""Context-scoped binding for the source tree Doctor checks read.

Source-checkout health checks resolve their repository root from the
runner's ambient working directory. That is right while the runner stands
in the tree it reports on, and wrong the moment one runner reports on a
project it is not standing in: an https client composes locally executed
source checks for whichever project was named, so ``--project buzz`` run
from the Yoke checkout would otherwise read Yoke files and label the
findings Buzz.

The selected checkout travels on a ContextVar rather than through
``os.chdir``. A process-global directory change is unsafe in a runner
that serves concurrent work — one composition's tree would leak into
every other caller sharing the process — and it survives past the failure
it happened on. Mirrors
:func:`yoke_core.domain.db_backend.bound_pg_dsn`: set the token on enter,
reset it in ``finally``, so each thread and task keeps its own value.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Iterator, Optional
import subprocess
import warnings

from yoke_contracts.install_binding import source_checkout_root
from yoke_contracts.doctor_budget import remaining_seconds

GIT_IDENTITY_TIMEOUT_S = 5


_BOUND_SOURCE_ROOT: ContextVar[Optional[str]] = ContextVar(
    "yoke_doctor_source_root",
    default=None,
)


@contextmanager
def bound_source_root(root: Path | str) -> Iterator[None]:
    """Bind this execution context to the checkout source checks must read."""
    text = str(root).strip()
    if not text:
        raise ValueError("the bound Doctor source root must not be empty")
    token = _BOUND_SOURCE_ROOT.set(text)
    try:
        yield
    finally:
        _BOUND_SOURCE_ROOT.reset(token)


def bound_source_root_or_none() -> Optional[str]:
    """Return the bound checkout, or ``None`` when this context binds none."""
    return _BOUND_SOURCE_ROOT.get()


__all__ = ["bound_source_root", "bound_source_root_or_none"]


def preferred_source_checkout(mapped: Path) -> Path:
    """Prefer imported source from the mapped repo or its disposable clone."""
    source = source_checkout_root(__file__)
    if source is None or source == mapped:
        return mapped

    def common_dir(root):
        result = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ],
            capture_output=True,
            text=True,
            timeout=remaining_seconds(GIT_IDENTITY_TIMEOUT_S),
        )
        if result.returncode or not result.stdout.strip():
            raise OSError(
                f"Git identity read failed for {root}: "
                f"exit={result.returncode}, {result.stderr.strip() or 'empty common dir'}"
            )
        return result.stdout.strip()

    try:
        selected = common_dir(source)
        if selected and selected == common_dir(mapped):
            return source
        origin = subprocess.run(
            ["git", "-C", str(source), "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            timeout=remaining_seconds(GIT_IDENTITY_TIMEOUT_S),
        )
        if origin.returncode not in (0, 1):
            raise OSError(
                f"Git clone identity read failed for {source}: exit={origin.returncode}"
            )
        location = Path(origin.stdout.strip())
        if (
            origin.returncode == 0
            and location.is_absolute()
            and location.resolve() == mapped.resolve()
        ):
            return source
    except (OSError, subprocess.TimeoutExpired) as exc:
        warnings.warn(
            f"doctor_source_checkout_fallback: {exc}; using mapped checkout {mapped}. "
            "Recovery: restore Git access and rerun Doctor to verify the source lane.",
            RuntimeWarning,
            stacklevel=2,
        )
    return mapped
