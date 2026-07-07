"""Canonical board emoji vocabulary — the single source of truth.

Every board surface imports its glyphs from here so no glyph carries two
meanings. Before this module the same status was drawn with up to four
unrelated glyphs across the stats box, section headers, per-row status, and
art colors; and decorative/metadata surfaces silently reused semantic glyphs
(🔥 meant Active *and* the streak; 🚀 meant Pipeline *and* release *and*
advance). The dedup decisions and the full allocation registry below are the
authority; surfaces that still hardcode a glyph are bugs.

Three exempt surfaces deliberately reuse glyphs and are NOT governed here:
the frontier art status *colors* (🟩🟧🟨🟥🟦🟪🟣 — status *groups*, not 1:1),
the rainbow emoji art sets, and the celebration pool (a random flourish).

Allocation registry (canonical owner per glyph; reassignments noted):

  Buckets (stats box == section headers):
    🎫 Active · 💧 Pipeline · 🌱 Backlog · ⛔ Blocked · 🧊 Frozen · ✅ Done · ❓ Unknown
  Per-row lifecycle status (STATUS_EMOJI): see dict below.
  Session actions (sections_sessions._MODE_EMOJI):
    📝 refine · ✨ polish · ⚡ charge · 🧠 strategize · 🚨 escalate · 🔧 manual
    🔄 resume · ⏩ advance · ⏳ wait · 🎼 conduct · 🧑‍🌾 shepherd · 🎬 usher
    🧹 curate · 🩺 doctor · 🔮 simulate · 💡 idea · 🧾 wrapup · 🎮 do · 🍴 feed
    📌 plan · 🪝 hook
  Executors (sections_sessions_cells._EXECUTOR_EMOJI):
    🤖 claude-code · 🍎 claude-desktop · 🪟 claude-vscode · 📟 claude-cli
    📕 codex · 💻 codex-desktop · 🪄 codex-vscode · 📠 codex-cli
  Badges (widgets_badges):
    🔖 type · 🏅 milestone · 🎯 streak · 🛟 zero-bugs · 📭 inbox-zero · 🕐 age
  Velocity meter (widgets_velocity_meter):
    📊 activity · 💾 code · 📦 delivery · 🧭 strategy
  Session section headers: 🟢 Active Harness Sessions · 🔴 Recent Harness Sessions
  Claim decorations: 📁 path-claim · 🔒 lease · 🔩 process-anchor
"""

from __future__ import annotations

import random
from typing import Dict, Optional

# ---------------------------------------------------------------------------
# Bucket vocabulary — shared by the stats box (art_stats) and the section
# headers (renderer_sections). One label + one glyph per bucket.
# ---------------------------------------------------------------------------

ACTIVE_LABEL, ACTIVE_EMOJI = "Active", "🎫"           # 🎫 tickets
PIPELINE_LABEL, PIPELINE_EMOJI = "Pipeline", "💧"    # 💧 droplet (flow)
BACKLOG_LABEL, BACKLOG_EMOJI = "Backlog", "🌱"         # 🌱 seedling
BLOCKED_LABEL, BLOCKED_EMOJI = "Blocked", "⛔"             # ⛔ no-entry
FROZEN_LABEL, FROZEN_EMOJI = "Frozen", "🧊"            # 🧊 snowflake
DONE_LABEL, DONE_EMOJI = "Done", "✅"                      # ✅
UNKNOWN_LABEL, UNKNOWN_EMOJI = "Unknown", "❓"             # ❓

# ---------------------------------------------------------------------------
# Per-row lifecycle status glyphs (was sections_classify._STATUS_EMOJI_PREFIX).
# The implementation/review arc rides an *escalating checkmark* ladder:
# 👍 reviewed → ⛳ implemented → ✅ done.
# ---------------------------------------------------------------------------

STATUS_EMOJI: Dict[str, str] = {
    "idea": "\U0001f4a1",                       # 💡
    "refining-idea": "📝",            # 📝
    "refined-idea": "\U0001f48e",               # 💎
    "planning": "📐",                       # 📐 triangular ruler — Architect drafts the epic plan
    "plan-drafted": "📋",                       # 📋 clipboard — the drafted plan
    "refining-plan": "📝",            # 📝
    "planned": "💎",                        # 💎 refined/ready — parallel to refined-idea
    "implementing": "\U0001f528",               # 🔨
    "reviewing-implementation": "\U0001f440",   # 👀
    "reviewed-implementation": "👍",  # 👍
    "polishing-implementation": "✨",       # ✨
    "implemented": "⛳",              # ⛳
    "release": "\U0001f680",                    # 🚀
    "done": DONE_EMOJI,                         # ✅
    "blocked": BLOCKED_EMOJI,                   # ⛔ no-entry
    "stopped": "\U0001f6d1",                # 🛑 stop sign
    "cancelled": "🚫",                # 🚫
    "failed": "❗",                         # ❗
}

# ---------------------------------------------------------------------------
# Badge glyphs (widgets_badges) — centralized here as the single source.
# ---------------------------------------------------------------------------

BADGE_CLOCK = "\U0001f550"        # 🕐 age-heatmap label
BADGE_TYPE = "🔖"                 # 🔖 type badges
BADGE_MILESTONE = "\U0001f3c5"    # 🏅 milestone achievement
BADGE_STREAK = "\U0001f3af"       # 🎯 streak achievement
BADGE_ZERO_BUGS = "🛟"            # 🛟 zero-bugs achievement
BADGE_INBOX_ZERO = "\U0001f4ed"   # 📭 inbox-zero achievement

# Age heatmap (recency scale; colored-square family, exempt from semantic dedup)
AGE_FRESH = "\U0001f7e9"          # 🟩
AGE_WEEK = "\U0001f7e8"           # 🟨
AGE_BIWEEK = "\U0001f7e7"         # 🟧
AGE_MONTH = "\U0001f7e5"          # 🟥
AGE_ANCIENT = "\U0001f480"        # 💀

# ---------------------------------------------------------------------------
# Velocity-meter glyphs (widgets_velocity_meter)
# ---------------------------------------------------------------------------

VELOCITY_CODE = "\U0001f4be"      # 💾 code
VELOCITY_DELIVERY = "\U0001f4e6"  # 📦 delivery
VELOCITY_STRATEGY = "\U0001f9ed"  # 🧭 strategy

# ---------------------------------------------------------------------------
# Celebration pool — random flourish when the board reaches frontier inbox-zero.
# Exempt from dedup (decorative); intentionally overlaps semantic glyphs.
# ---------------------------------------------------------------------------

CELEBRATION_EMOJIS = [
    "\U0001f680", "\U0001f31f", "\U0001f386", "\U0001f389",
    "\U0001f3c6", "\U0001f4ab", "\U0001f525", "\U0001f48e",
    "\U0001f984", "\U0001f308", "\U0001f3af", "\U0001f4a5",
]


def resolve_celebration(
    stats: Dict[str, int], mode: str, seed: Optional[int]
) -> Optional[str]:
    """Pick the one celebration glyph for this render, or ``None``.

    Gated on **frontier** art mode (other modes render their own grid/legend,
    so a swap would surface only on the stats-box Done row and read as a random
    trophy change rather than a milestone) AND inbox-zero (done > 0 with no
    active / pipeline / backlog work). Deterministic given ``seed`` so the same
    glyph flows to the stats box, the frontier grid/legend, the Done section
    header, and every per-row ``done`` status within a single render.
    """
    if mode != "frontier":
        return None
    if (
        stats.get("done", 0) > 0
        and stats.get("active", 0) == 0
        and stats.get("pipeline", 0) == 0
        and stats.get("backlog", 0) == 0
    ):
        return random.Random(seed).choice(CELEBRATION_EMOJIS)
    return None
