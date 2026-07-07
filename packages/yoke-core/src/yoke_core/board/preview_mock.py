"""Mock dashboard data for preview mode.

The preview CLI renders dashboards without a live database. The constants
and ``_mock_dashboard`` helper here generate the synthetic rows the
preview consumes.
"""

from __future__ import annotations

import random
from typing import List


_MOCK_SPARKLINE = "▁▂▃▅▇█▅▃▂▁▃▅▇█"
_MOCK_SPARKLINE_2 = "▁▂▃▅▇▂▃▅▃▅▃▇▂▃"


def _mock_dashboard(velocity_meter: bool = False) -> str:
    """Render mock dashboard rows for preview (no DB needed)."""
    lines: List[str] = []

    # Weather
    lines.append("")
    lines.append("\U0001f31e Clear")

    # Row 1: velocity sparkline | type badges
    lines.append("")
    lines.append(
        f"\U0001f4ca {_MOCK_SPARKLINE} 14d activity"
        f"      \U0001f525\U0001f525\U0001f525 3d streak"
    )

    lines.append("")
    lines.append(
        f"\U0001f4ca {_MOCK_SPARKLINE_2} 14d activity"
        f"      \U0001f525\U0001f525\U0001f525 3d streak"
        f" | \U0001f516 epic:5 feature:3 issue:2"
    )

    # 120-day velocity meter (if requested)
    if velocity_meter:
        lines.append("")
        rng = random.Random(42)
        blocks = "▁▂▃▅▇█"
        activity = ""
        effort = ""
        delivery = ""
        sml = ""
        for i in range(120):
            # Activity: moderate with late bursts
            if i < 60:
                activity += blocks[0]
            elif i % 9 == 0:
                activity += blocks[4]
            elif i % 5 == 0:
                activity += blocks[2]
            else:
                activity += blocks[1]
            # Effort: rising trend
            e_level = min((i * 5 // 119) + 1, 5)
            effort += blocks[e_level]
            # Delivery: sporadic spikes
            if i % 7 == 0 or i % 11 == 0:
                delivery += blocks[3]
            else:
                delivery += blocks[0]
            # SML: occasional
            if i % 13 == 0:
                sml += blocks[2]
            else:
                sml += blocks[0]
        lines.append(f"\U0001f4ca {activity} 120d activity")
        lines.append(f"\U0001f4be {effort} 120d code")
        lines.append(f"\U0001f4e6 {delivery} 120d issues")
        lines.append(f"\U0001f9ed {sml} 120d strategy")

    # Row 2: age heatmap | achievement badges
    lines.append("")
    lines.append(
        "\U0001f550 "
        "\U0001f7e9\U0001f7e9\U0001f7e9\U0001f7e8\U0001f7e8"
        "\U0001f7e7\U0001f7e7\U0001f7e5\U0001f480"
        " age: \U0001f7e9<1h \U0001f7e8<6h \U0001f7e7<1d \U0001f7e5<1w \U0001f480>1w"
        " | \U0001f3c5 100done  \U0001f3af streak5  \U0001f6df zero-bugs"
    )

    return "\n".join(lines)
