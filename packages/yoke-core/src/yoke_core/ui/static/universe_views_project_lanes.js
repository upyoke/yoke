// The read-only lane summary on a project's settings screen. Everything it
// shows — effective labels and glyphs, which selectors route where, which
// harnesses default to a lane, and what each action means — is composed by
// `projects.lane_summary.get`, so this module renders and never resolves.
// Editing belongs to a harness through the project capability-settings
// commands, which is why there is no control here that writes.

import { el, loadSection, section } from "./universe_view_support.js";

const PRIORITY_ORDER =
  "explicit override → harness + model → model → harness → default.";
const PRIORITY_DETAIL =
  "An ending * matches a model family. Exact models beat prefixes; " +
  "longer prefixes beat shorter ones.";

function laneCell(documentNode, lane) {
  const cell = el(documentNode, "td");
  const caption = el(documentNode, "span", "lane-caption");
  if (lane.glyph) {
    caption.appendChild(el(documentNode, "span", "lane-glyph", lane.glyph));
  }
  caption.appendChild(el(documentNode, "b", null, lane.label || lane.id));
  cell.appendChild(caption);
  return cell;
}

function matchesCell(documentNode, lane, harnessLabels) {
  const cell = el(documentNode, "td");
  const matches = lane.matches || [];
  if (!matches.length) {
    cell.appendChild(
      el(documentNode, "span", "lane-muted", "No custom matches"),
    );
    return cell;
  }
  // Several matches on one lane are alternatives: a session landing here
  // satisfied any one of them, never all of them.
  const list = el(documentNode, "div", "lane-matches");
  for (const match of matches) {
    const row = el(documentNode, "div", "lane-match-summary");
    row.appendChild(el(
      documentNode,
      "span",
      null,
      match.harness ? (harnessLabels.get(match.harness) || match.harness)
        : "Any harness",
    ));
    row.appendChild(el(documentNode, "span", "lane-muted", "·"));
    row.appendChild(el(
      documentNode, "code", null, match.model || "Any model",
    ));
    list.appendChild(row);
  }
  cell.appendChild(list);
  return cell;
}

function actionsCell(documentNode, lane, catalog) {
  const cell = el(documentNode, "td");
  const allowed = lane.actions || [];
  const chosen = catalog.filter((action) => allowed.includes(action.id));
  // An empty allowlist is a lane that runs nothing, which reads as None.
  // Rendering it as All would invert the operator's configuration.
  if (!chosen.length) {
    cell.appendChild(el(documentNode, "span", "lane-muted", "None"));
    return cell;
  }
  const disclosure = el(documentNode, "details", "lane-actions");
  disclosure.appendChild(el(
    documentNode,
    "summary",
    null,
    chosen.length === catalog.length
      ? `All ${chosen.length} ${chosen.length === 1 ? "action" : "actions"}`
      : chosen.map((action) => action.label).join(", "),
  ));
  const detail = el(documentNode, "div");
  for (const action of chosen) {
    const entry = el(documentNode, "div");
    entry.appendChild(el(documentNode, "b", null, action.label));
    entry.appendChild(el(documentNode, "small", null, action.description));
    detail.appendChild(entry);
  }
  disclosure.appendChild(detail);
  cell.appendChild(disclosure);
  return cell;
}

function defaultsCell(documentNode, lane) {
  const cell = el(documentNode, "td");
  const defaults = lane.default_for || [];
  if (!defaults.length) {
    cell.appendChild(el(documentNode, "span", "lane-muted", "None"));
    return cell;
  }
  for (const label of defaults) {
    cell.appendChild(el(documentNode, "div", "lane-default-summary", label));
  }
  return cell;
}

function laneTable(documentNode, result) {
  const catalog = result.action_catalog || [];
  const harnessLabels = new Map(
    (result.harnesses || []).map((harness) => [harness.id, harness.label]),
  );
  const wrap = el(documentNode, "div", "table-wrap");
  const table = el(documentNode, "table", "items lane-table");
  const head = el(documentNode, "tr");
  head.appendChild(el(documentNode, "th", null, "Lane"));
  const matchHead = el(documentNode, "th", null, "Matches");
  matchHead.appendChild(
    el(documentNode, "span", "lane-th-note", "Harness · model"),
  );
  head.appendChild(matchHead);
  head.appendChild(el(documentNode, "th", null, "Allowed actions"));
  head.appendChild(el(documentNode, "th", null, "Default for"));
  table.appendChild(head);
  for (const lane of result.lanes || []) {
    const row = el(documentNode, "tr");
    row.setAttribute("data-lane-row", lane.id);
    row.appendChild(laneCell(documentNode, lane));
    row.appendChild(matchesCell(documentNode, lane, harnessLabels));
    row.appendChild(actionsCell(documentNode, lane, catalog));
    row.appendChild(defaultsCell(documentNode, lane));
    table.appendChild(row);
  }
  wrap.appendChild(table);
  return wrap;
}

export function renderProjectLaneSummary(context, scope) {
  const documentNode = context.document;
  const panel = section(documentNode, "Lanes");
  panel.classList.add("lane-settings");
  loadSection(
    context,
    panel,
    "projects.lane_summary.get",
    { project: String(scope) },
    (body, callResult) => {
      const result = (callResult.envelope.result || {});
      const lanes = result.lanes || [];
      panel.setCount(lanes.length);
      if (!lanes.length) {
        body.appendChild(el(
          documentNode,
          "p",
          "empty",
          "No lanes configured for this project.",
        ));
      } else {
        body.appendChild(laneTable(documentNode, result));
      }
      const unrouted = result.unrouted_harnesses || [];
      if (unrouted.length) {
        // A harness that resolves to no lane is otherwise just absent from
        // every row, which reads like a lane nobody defaults to.
        body.appendChild(el(
          documentNode,
          "p",
          "lane-unrouted",
          `${unrouted.join(", ")} ${unrouted.length === 1 ? "matches" : "match"}`
            + " no lane and cannot be routed work.",
        ));
      }
      const priority = el(documentNode, "div", "lane-priority");
      priority.appendChild(el(documentNode, "b", null, "Priority:"));
      priority.appendChild(el(documentNode, "span", null, ` ${PRIORITY_ORDER}`));
      priority.appendChild(el(documentNode, "div", "lane-muted", PRIORITY_DETAIL));
      body.appendChild(priority);

      const editing = el(documentNode, "div", "lane-cli");
      editing.appendChild(el(documentNode, "b", null, "Edit with your harness"));
      const instruction = el(documentNode, "p", null, "tell your agent to use ");
      instruction.appendChild(
        el(documentNode, "code", null, "yoke projects capability-settings"),
      );
      editing.appendChild(instruction);
      body.appendChild(editing);
    },
  );
  return panel;
}

export { PRIORITY_DETAIL, PRIORITY_ORDER };
