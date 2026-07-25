"""The closed roster of packaged static assets the UI server may serve.

Split out of :mod:`yoke_core.ui.server` so the roster can grow one line
per new static module without crowding the server's routing and security
logic; the server re-exports both names for its callers.
"""

from __future__ import annotations

from typing import Dict

#: ``Cache-Control`` for the app shell and static assets: ``no-cache``
#: makes browsers revalidate on every load, so an upgraded server never
#: keeps stale modules running from cache.
ASSET_CACHE_CONTROL = "no-cache"

#: Packaged static assets the server may serve, with their content types.
#: A closed name→type map (no filesystem paths from the request) keeps
#: traversal structurally impossible.
ASSET_CONTENT_TYPES: Dict[str, str] = {
    "index.html": "text/html; charset=utf-8",
    # Developer page, not a product route: mounts the same app with sample
    # platform chrome shaped like the hosted shell's slots, so frame defects
    # that only show with occupied slots are visible on a laptop.
    "hosted-frame-harness.html": "text/html; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "contract.js": "text/javascript; charset=utf-8",
    "contract-version.js": "text/javascript; charset=utf-8",
    "mount-options.js": "text/javascript; charset=utf-8",
    "universe_navigation.js": "text/javascript; charset=utf-8",
    "universe_view_support.js": "text/javascript; charset=utf-8",
    "universe_views.js": "text/javascript; charset=utf-8",
    "universe_views_capabilities.js": "text/javascript; charset=utf-8",
    "universe_views_delivery.js": "text/javascript; charset=utf-8",
    "universe_views_doctor.js": "text/javascript; charset=utf-8",
    "universe_views_events.js": "text/javascript; charset=utf-8",
    "universe_views_frontier.js": "text/javascript; charset=utf-8",
    "universe_views_github.js": "text/javascript; charset=utf-8",
    "universe_views_items.js": "text/javascript; charset=utf-8",
    "universe_views_organization.js": "text/javascript; charset=utf-8",
    "universe_views_ouroboros.js": "text/javascript; charset=utf-8",
    "universe_views_overview.js": "text/javascript; charset=utf-8",
    "universe_views_packs.js": "text/javascript; charset=utf-8",
    "universe_views_projects.js": "text/javascript; charset=utf-8",
    "universe_views_sessions.js": "text/javascript; charset=utf-8",
    "universe_views_strategy.js": "text/javascript; charset=utf-8",
    "universe_views_workflows.js": "text/javascript; charset=utf-8",
    "app.css": "text/css; charset=utf-8",
    "shell.css": "text/css; charset=utf-8",
    "theme.css": "text/css; charset=utf-8",
    "yoke.svg": "image/svg+xml",
    "yoke-wordmark.svg": "image/svg+xml",
    "favicon.svg": "image/svg+xml",
    "favicon.ico": "image/x-icon",
    "apple-touch-icon.png": "image/png",
}
