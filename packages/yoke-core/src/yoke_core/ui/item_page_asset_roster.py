"""Packaged static assets for the item pages: roster, detail and intake.

Merged into :data:`yoke_core.ui.asset_roster.ASSET_CONTENT_TYPES`, the one
closed roster the UI server serves from.
"""

from __future__ import annotations

from typing import Dict

ITEM_PAGE_ASSET_CONTENT_TYPES: Dict[str, str] = {
    "item_detail_loader.js": "text/javascript; charset=utf-8",
    "item_view_approvals.js": "text/javascript; charset=utf-8",
    "item_view_claimant.js": "text/javascript; charset=utf-8",
    "item_view_delivery.js": "text/javascript; charset=utf-8",
    "item_view_details.js": "text/javascript; charset=utf-8",
    "item_intake_controls.js": "text/javascript; charset=utf-8",
    "item_view_facts.js": "text/javascript; charset=utf-8",
    "item_view_landings.js": "text/javascript; charset=utf-8",
    "item_new_form.js": "text/javascript; charset=utf-8",
    "item_roster_table.js": "text/javascript; charset=utf-8",
    "item_roster_sort.js": "text/javascript; charset=utf-8",
    "item_draft_storage.js": "text/javascript; charset=utf-8",
    "item_view_new.js": "text/javascript; charset=utf-8",
    "item_view_primitives.js": "text/javascript; charset=utf-8",
    "item_view_shell.js": "text/javascript; charset=utf-8",
    "item_view_verification.js": "text/javascript; charset=utf-8",
    "item_view_verdicts.js": "text/javascript; charset=utf-8",
    "item_view_requirement_card.js": "text/javascript; charset=utf-8",
    "item_foundations.css": "text/css; charset=utf-8",
    "item_roster.css": "text/css; charset=utf-8",
    "item_details.css": "text/css; charset=utf-8",
    "item_intake.css": "text/css; charset=utf-8",
}
