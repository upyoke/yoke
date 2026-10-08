// The read-only level summary on a project's settings screen. Everything it
// shows — effective labels and glyphs, which selectors route where, which
// harnesses default to a level — is composed by
// `projects.level_summary.get`, so this module renders and never resolves.
// Editing belongs to a harness through the project capability-settings
// commands, which is why there is no control here that writes.

import { el, loadSection, section } from "./universe_view_support.js";

const PRIORITY_ORDER =
  "explicit override → harness + model → model → harness → default.";
const PRIORITY_DETAIL =
  "An ending * matches a model family. Exact models beat prefixes; " +
  "longer prefixes beat shorter ones.";

function levelCell(documentNode, level) {
  const cell = el(documentNode, "td");
  const caption = el(documentNode, "span", "level-caption");
  if (level.glyph) {
    caption.appendChild(el(documentNode, "span", "level-glyph", level.glyph));
  }
  caption.appendChild(el(documentNode, "b", null, level.label || level.id));
  cell.appendChild(caption);
  return cell;
}

function matchesCell(documentNode, level, harnessLabels) {
  const cell = el(documentNode, "td");
  const matches = level.matches || [];
  if (!matches.length) {
    cell.appendChild(
      el(documentNode, "span", "level-muted", "No custom matches"),
    );
    return cell;
  }
  // Several matches on one level are alternatives: a session landing here
  // satisfied any one of them, never all of them.
  const list = el(documentNode, "div", "level-matches");
  for (const match of matches) {
    const row = el(documentNode, "div", "level-match-summary");
    row.appendChild(el(
      documentNode,
      "span",
      null,
      match.harness ? (harnessLabels.get(match.harness) || match.harness)
        : "Any harness",
    ));
    row.appendChild(el(documentNode, "span", "level-muted", "·"));
    row.appendChild(el(
      documentNode, "code", null, match.model || "Any model",
    ));
    list.appendChild(row);
  }
  cell.appendChild(list);
  return cell;
}

function defaultsCell(documentNode, level) {
  const cell = el(documentNode, "td");
  const defaults = level.default_for || [];
  if (!defaults.length) {
    cell.appendChild(el(documentNode, "span", "level-muted", "None"));
    return cell;
  }
  for (const label of defaults) {
    cell.appendChild(el(documentNode, "div", "level-default-summary", label));
  }
  return cell;
}

function levelTable(documentNode, result) {
  const harnessLabels = new Map(
    (result.harnesses || []).map((harness) => [harness.id, harness.label]),
  );
  const wrap = el(documentNode, "div", "table-wrap");
  const table = el(documentNode, "table", "items level-table");
  const head = el(documentNode, "tr");
  head.appendChild(el(documentNode, "th", null, "Level"));
  const matchHead = el(documentNode, "th", null, "Matches");
  matchHead.appendChild(
    el(documentNode, "span", "level-th-note", "Harness · model"),
  );
  head.appendChild(matchHead);
  head.appendChild(el(documentNode, "th", null, "Default for"));
  table.appendChild(head);
  for (const level of result.levels || []) {
    const row = el(documentNode, "tr");
    row.setAttribute("data-level-row", level.id);
    row.appendChild(levelCell(documentNode, level));
    row.appendChild(matchesCell(documentNode, level, harnessLabels));
    row.appendChild(defaultsCell(documentNode, level));
    table.appendChild(row);
  }
  wrap.appendChild(table);
  return wrap;
}

export function renderProjectLevelSummary(context, scope) {
  const documentNode = context.document;
  const panel = section(documentNode, "Levels");
  panel.classList.add("level-settings");
  loadSection(
    context,
    panel,
    "projects.level_summary.get",
    { project: String(scope) },
    (body, callResult) => {
      const result = (callResult.envelope.result || {});
      const levels = result.levels || [];
      panel.setCount(levels.length);
      if (!levels.length) {
        body.appendChild(el(
          documentNode,
          "p",
          "empty",
          "No levels configured for this project.",
        ));
      } else {
        body.appendChild(levelTable(documentNode, result));
      }
      const unrouted = result.unrouted_harnesses || [];
      if (unrouted.length) {
        // A harness that resolves to no level is otherwise just absent from
        // every row, which reads like a level nobody defaults to.
        body.appendChild(el(
          documentNode,
          "p",
          "level-unrouted",
          `${unrouted.join(", ")} ${unrouted.length === 1 ? "matches" : "match"}`
            + " no configured level grouping.",
        ));
      }
      const priority = el(documentNode, "div", "level-priority");
      priority.appendChild(el(documentNode, "b", null, "Priority:"));
      priority.appendChild(el(documentNode, "span", null, ` ${PRIORITY_ORDER}`));
      priority.appendChild(el(documentNode, "div", "level-muted", PRIORITY_DETAIL));
      body.appendChild(priority);

      const editing = el(documentNode, "div", "level-cli");
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
