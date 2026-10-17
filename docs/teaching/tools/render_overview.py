"""Stable navigation and status meanings for the teaching overview."""

from model import STATUSES
from render import badge, esc, link, page, wrap

STATUS_MEANING = {
    "observed": "seen in source or a capture; scope stated, behavior unproven",
    "verified-live": "proven against running Yoke with recorded evidence",
    "candidate": "reviewed proposal, not approved scope",
    "approved": "approved scope or a locked boundary",
    "deferred": "approved direction whose execution waits",
    "draft-copy": "research outline or draft wording; not a shipped recipe",
    "superseded": "replaced proposal kept for provenance",
}


def index_page(views, intro):
    destinations = (
        ("Concepts", "concepts.html"),
        ("Teaching surfaces and rows", "surfaces.html"),
        ("Scenarios and lessons", "scenarios.html"),
        ("Locked boundaries", "boundaries.html"),
        ("Gaps", "gaps.html"),
        ("Evidence", "evidence.html"),
    )
    recipe = link("index.html", "../README.md", "README")
    body = (
        wrap(f"<p>{esc(intro)}</p>")
        + wrap(
            f"<p>The {recipe} holds the edit, rebuild and check recipe, the "
            "Platform route and the live command and docs-graph pages.</p>"
        )
        + ["<ul>"]
    )
    # Independent model edits must not produce a stale global counter when
    # Git combines their views. Each destination owns its detailed records.
    body += [
        f"<li>{link('index.html', target, label)}</li>"
        for label, target in destinations
    ]
    body += ["</ul>", "<h2>Record status</h2>"] + status_legend()
    views["index.html"] = page("index.html", "Yoke teaching prototype", body)


def status_legend() -> list[str]:
    out = ["<dl>"]
    for status in STATUSES:
        out += wrap(f"<dt>{badge(status)}</dt><dd>{esc(STATUS_MEANING[status])}</dd>")
    return out + ["</dl>"]
