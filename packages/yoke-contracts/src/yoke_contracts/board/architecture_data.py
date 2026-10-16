"""Connection-free board architecture coverage rendering."""

from typing import Mapping, Sequence


def render_architecture_rows(rows: Sequence[Mapping]) -> str:
    """Render named project coverage facts; no declared map means no section."""
    if not rows:
        return ""
    lines = ["### 🗺 Architecture", ""]
    for row in rows:
        project, total, covered = row["project"], row["total"], row["covered"]
        if total:
            pct = round(100.0 * covered / total, 1)
            lines.append(
                f"  {project}: {pct}% classified · "
                f"{total - covered} unclassified of {total} python files"
            )
        else:
            lines.append(f"  {project}: map declared · no snapshot yet")
    lines.append(
        "  violations: `yoke project-structure architecture-health get "
        "--project <slug>`"
    )
    return "\n".join(lines)
