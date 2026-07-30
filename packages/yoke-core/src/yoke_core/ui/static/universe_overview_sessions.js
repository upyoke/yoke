import {
  el,
  mergedRows,
  portabilityMode,
  sessionModePill,
  whoColumn,
} from "./universe_view_support.js";
import { holdScopedSection, rowsInScope } from "./universe_held_reads.js";
import { relativeTime } from "./universe_time.js";
import {
  appendCell,
  destinationHref,
  emptyTableRow,
  makeRowNavigable,
  overviewMiniRow,
  overviewTable,
  projectDisplay,
  routeCell,
  SESSION_SUMMARY_ROW_LIMIT,
} from "./universe_overview_primitives.js";

function sessionWhoIdentity(documentNode, row, who, mode) {
  const identity = el(
    documentNode,
    "span",
    "overview-session-identity",
  );
  const machine = who.isMachine(row);
  if (mode === "hosted") {
    if (machine) {
      identity.appendChild(el(
        documentNode,
        "span",
        "overview-session-unmapped",
        "—",
      ));
      identity.appendChild(el(
        documentNode,
        "span",
        "overview-session-machine-kind",
        " machine",
      ));
      return identity;
    }
    const member = who.value(row);
    if (member === "—") {
      identity.appendChild(el(
        documentNode,
        "span",
        "overview-session-unmapped",
        "—",
      ));
      return identity;
    }
    identity.appendChild(el(
      documentNode,
      "span",
      "overview-session-avatar",
      String(member).slice(0, 1),
    ));
    identity.appendChild(el(
      documentNode,
      "span",
      "overview-session-member-label",
      ` ${member}`,
    ));
    return identity;
  }

  const actorLabel = row.actor_label ||
    (row.actor_id == null ? "unattributed" : `actor ${row.actor_id}`);
  if (!machine) {
    identity.appendChild(el(
      documentNode,
      "span",
      "overview-session-avatar",
      String(actorLabel).slice(0, 1),
    ));
  }
  identity.appendChild(el(
    documentNode,
    "span",
    machine
      ? "overview-session-actor-label overview-session-machine-label"
      : "overview-session-actor-label",
    `${machine ? "" : " "}${actorLabel}`,
  ));
  if (row.actor_id != null) {
    identity.appendChild(el(
      documentNode,
      "span",
      "overview-session-actor-id",
      ` #${row.actor_id}`,
    ));
  }
  if (machine) {
    identity.appendChild(el(
      documentNode,
      "span",
      "overview-session-machine-kind",
      " machine",
    ));
  }
  return identity;
}

// Live sessions use the same mode-shaped identity column as the full screen,
// followed by a compact recently-ended tail.
export function loadSessions(context, panel, getScope) {
  const who = whoColumn(context.capabilities);
  const mode = portabilityMode(context.capabilities);
  const showWho = mode !== "local";
  panel.setDetail(mode === "local" ? "this machine" : "across the universe");
  // The held roster is one unscoped read filtered client-side, so ask for the
  // per-project windowed slice: each project (and the unattributed partition)
  // keeps its own newest-N, so a busy project cannot crowd a quiet one out of
  // the held set.
  return holdScopedSection(
    context, panel, [null],
    [{ functionId: "sessions.list", payload: { per_project: true } }],
    getScope,
    (body, callResults, scope) => {
      const documentNode = body.ownerDocument;
      const rows = rowsInScope(
        mergedRows(callResults, (result) => result.rows), scope, context.projects(),
      );
      const liveRows = rows.filter((row) => ["active", "stale"].includes(
        String(row.liveness || "").toLowerCase(),
      ));
      const endedRows = rows.filter((row) =>
        String(row.liveness || "").toLowerCase() === "ended");
      panel.setCount(`${liveRows.length} live`);
      const headers = [
        "Session", "Project",
        ...(showWho ? [who.label === "member" ? "Member" : "Actor"] : []),
        "Executor", "Model", "Lane", "Mode", "Age", "Claim",
      ];
      const table = overviewTable(
        documentNode, "overview-sessions-table", headers,
      );
      const href = destinationHref("sessions", scope);
      for (const row of liveRows.slice(0, SESSION_SUMMARY_ROW_LIMIT)) {
        const tableRow = el(documentNode, "tr", "overview-session-row");
        routeCell(
          documentNode,
          tableRow,
          row.session_id || "session",
          href,
          "overview-session-id",
        );
        appendCell(
          documentNode,
          tableRow,
          projectDisplay(context.projects(), row.project),
          "overview-project-cell",
        );
        if (showWho) {
          appendCell(
            documentNode,
            tableRow,
            sessionWhoIdentity(documentNode, row, who, mode),
            "overview-who-cell",
          );
        }
        appendCell(documentNode, tableRow, row.executor || "—");
        appendCell(
          documentNode, tableRow, row.model || "—", "overview-model-cell",
        );
        appendCell(
          documentNode,
          tableRow,
          el(
            documentNode,
            "span",
            "overview-lane",
            row.execution_lane || "—",
          ),
        );
        appendCell(
          documentNode,
          tableRow,
          sessionModePill(documentNode, row.mode, row.liveness),
        );
        appendCell(
          documentNode,
          tableRow,
          relativeTime(documentNode, row.activity_at),
          "overview-age-cell",
        );
        const claim = el(documentNode, "span", "overview-claim");
        if (row.current_item) {
          claim.textContent =
            `${row.owns_current_item ? "🔒" : "↳"} ${row.current_item}`;
          claim.title = [
            row.current_item_title,
            row.owns_current_item ? "owns claim" : row.work_role,
          ].filter(Boolean).join(" · ");
        } else {
          claim.textContent = "—";
        }
        appendCell(documentNode, tableRow, claim, "overview-claim-cell");
        makeRowNavigable(
          documentNode, tableRow, href, row.session_id || "Sessions",
        );
        table.body.appendChild(tableRow);
      }
      if (!liveRows.length) {
        emptyTableRow(
          documentNode, table.body, headers.length, "No live sessions in this scope.",
        );
      }
      body.appendChild(table.wrap);

      const endedHead = el(documentNode, "div", "overview-subhead");
      const endedTitle = el(documentNode, "strong", null, "Recently ended");
      endedTitle.appendChild(el(
        documentNode,
        "span",
        "overview-subhead-count",
        ` · ${endedRows.length}`,
      ));
      endedHead.appendChild(endedTitle);
      body.appendChild(endedHead);
      if (!endedRows.length) {
        body.appendChild(el(
          documentNode, "p", "overview-region-empty", "No recently ended sessions.",
        ));
      }
      for (const row of endedRows.slice(0, 3)) {
        const identity = el(
          documentNode,
          "span",
          "overview-ended-session",
          row.session_id || "session",
        );
        const detail = [
          row.executor,
          row.model,
          row.execution_lane,
          row.mode,
          showWho ? who.value(row) : null,
          projectDisplay(context.projects(), row.project),
        ].filter(Boolean).join(" · ");
        body.appendChild(overviewMiniRow(
          documentNode,
          identity,
          detail,
          relativeTime(documentNode, row.ended_at || row.activity_at),
        ));
      }
    },
  );
}
