"""Atlas doc section renderers — teaching/field-notes/contradictions/next/curl.

Sibling of :mod:`atlas_render_docs` (split under the authored-file cap);
the front door imports these section functions and owns assembly order.
"""

from __future__ import annotations

from typing import Any, Dict, List

from yoke_core.tools.atlas_render_docs_tables import _md_table


def _render_teaching(report: Dict[str, Any]) -> List[str]:
    out = ["## 5. Teaching coverage", ""]
    totals = report["teaching_places"]["totals"]
    out.extend(_md_table(
        ("path glob", "count"),
        sorted(((glob, str(count)) for glob, count in totals.items()), key=lambda r: r[0]),
    ))
    out.append("")
    lints = report["lints"]
    out.append(
        f"Lint modules inventoried: **{lints['count']}** "
        f"({lints['with_field_note_reference']} reference the field-note "
        f"footer; {lints['with_denial_text']} carry denial text)."
    )
    out.append("")
    return out


def _render_field_notes(report: Dict[str, Any]) -> List[str]:
    out = ["## 6. Field-note hotspots", ""]
    fn = report["field_notes"]
    if fn.get("error"):
        out.append(f"_Field-note read failed: {fn['error']}_")
        out.append("")
        return out
    out.append(
        f"Recent field-notes inspected: **{fn['count']}** "
        f"(read surface: `{fn['read_surface_status']}`)."
    )
    out.append("")
    by_agent: Dict[str, int] = {}
    for row in fn["rows"]:
        by_agent[row.get("agent") or "unknown"] = (
            by_agent.get(row.get("agent") or "unknown", 0) + 1
        )
    if by_agent:
        out.extend(_md_table(
            ("agent", "recent count"),
            sorted(((k, str(v)) for k, v in by_agent.items()), key=lambda r: (-int(r[1]), r[0])),
        ))
        out.append("")
    return out


def _render_contradictions(report: Dict[str, Any]) -> List[str]:
    out = ["## 7. Contradictions", ""]
    rows = report["contradictions"]
    if not rows:
        out.append("_No tracked contradictions._")
        out.append("")
        return out
    out.extend(_md_table(
        ("id", "status", "surface", "live truth"),
        sorted(
            ((row["id"], row["status"], row["surface"], row["live_truth"]) for row in rows),
            key=lambda r: (r[1] != "open", r[0]),  # open first
        ),
    ))
    out.append("")
    return out


def _render_next_slice(report: Dict[str, Any]) -> List[str]:
    out = ["## 8. Next-slice recommendation", ""]
    candidates = report["followup_candidates"]
    if not candidates:
        out.append("_No outstanding follow-ups — the harness has nothing to recommend._")
        out.append("")
        return out
    for cand in candidates:
        out.append(f"- **{cand['title']}** _(category: {cand['category']})_")
    out.append("")
    return out


def _render_curl_floor() -> List[str]:
    """Static curl envelope reference — the operator floor under the CLI.

    Every function id in §2 dispatches through one envelope shape; an
    operator with curl alone can drive Yoke from anywhere. The CLI is
    the default; curl is the floor.
    """
    return [
        "## 9. Curl floor — the envelope shape under every family",
        "",
        "Every registered function id above accepts the same"
        " `FunctionCallRequest` envelope at the active env's"
        " `/v1/functions/call`. The `yoke` CLI is the default surface;"
        " curl is the operator floor when no CLI is installed:",
        "",
        "```bash",
        "API=https://api.stage.upyoke.com   # the active env's api_url",
        "TOKEN_FILE=~/.yoke/secrets/stage.token",
        "",
        "cat > /tmp/envelope.json <<'EOF'",
        "{",
        '  "function": "events.query.run",',
        '  "request_id": "<uuid>",',
        '  "actor": {"session_id": "<harness session id or omit>"},',
        '  "target": {"kind": "global"},',
        '  "payload": {"limit": 5}',
        "}",
        "EOF",
        "",
        'curl -sS -X POST "$API/v1/functions/call" \\',
        '  -H "Authorization: Bearer $(cat $TOKEN_FILE)" \\',
        "  -H 'Content-Type: application/json' \\",
        "  --data-binary @/tmp/envelope.json",
        "```",
        "",
        "Swap `function`, `target`, and `payload` per family — the"
        " payload schema for any id is served at"
        " `GET /v1/functions/schema/{function_id}` and the full id"
        " inventory at `GET /v1/functions/registry`. The CLI grammar"
        " manifest (tokens, usage lines) is `GET /v1/cli/manifest`."
        " Responses are typed `FunctionCallResponse` envelopes on both"
        " success and denial. The boundary overwrites envelope actor"
        " identity from the verified bearer token.",
        "",
    ]


__all__ = [
    "_render_contradictions",
    "_render_curl_floor",
    "_render_field_notes",
    "_render_next_slice",
    "_render_teaching",
]
