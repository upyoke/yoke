"""Resolve a case's automatic sign-in declaration without exposing credentials."""

from contextvars import ContextVar

from yoke_contracts.refusal_recovery import compose_refusal
from yoke_contracts.runtime_ports.browser_automatic_sign_in import get_browser_automatic_sign_in


sign_in_entry = get_browser_automatic_sign_in().sign_in_entry

_CASE_IDENTITY: ContextVar[tuple] = ContextVar(
    "browser_qa_case_identity", default=("", None)
)


def set_case_identity(project, declared):
    _CASE_IDENTITY.set((project, declared))


def resolve_step_sign_in(step):
    project, identity = _CASE_IDENTITY.get()
    site = (
        next((s for s in identity.sites if s.site == step["site"]), None)
        if identity
        else None
    )
    if site is None or site.sign_in is None:
        raise RuntimeError(
            compose_refusal(
                "browser_sign_in_step_not_automatic: the case identity's site has no "
                "automatic sign_in",
                recovery="Declare sign_in for the site in browser-control settings and "
                "select that identity in the case, then retry",
            )
        )
    return dict(
        sign_in_entry(project, identity, site), project=project, identity=identity.name
    )
