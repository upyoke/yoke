// The read-only execution levels on a project's settings screen: each level's
// glyph and its ordered launchable options, lowest level first, and whether
// they are the project's override or the universe levels. Everything shown is
// composed by `projects.level_summary.get`, so this module renders and never
// resolves. Editing belongs to a harness through the CLI, which is why there
// is no control here that writes.

import { el, loadSection, section } from "./universe_view_support.js";

const SOURCE_LABELS = {
  project: "This project's override",
  universe: "Universe levels",
  default: "Universe levels (shipped default)",
};

function levelCell(documentNode, level) {
  const cell = el(documentNode, "td");
  const caption = el(documentNode, "span", "level-caption");
  if (level.glyph) {
    caption.appendChild(el(documentNode, "span", "level-glyph", level.glyph));
  }
  caption.appendChild(el(documentNode, "b", null, level.name));
  cell.appendChild(caption);
  return cell;
}

function optionText(option) {
  const context = option.context_window_tokens
    ? `${option.context_window_tokens.toLocaleString("en-US")} tokens`
    : "default context";
  return `${option.reasoning_effort} · ${context}`;
}

function optionRow(documentNode, option, className) {
  const row = el(documentNode, "div", className);
  row.appendChild(el(documentNode, "span", null, option.surface));
  row.appendChild(el(documentNode, "code", null, option.model));
  row.appendChild(el(documentNode, "span", "level-muted", optionText(option)));
  return row;
}

function optionsCell(documentNode, level) {
  const cell = el(documentNode, "td");
  const list = el(documentNode, "div", "level-options");
  for (const option of level.options || []) {
    list.appendChild(optionRow(documentNode, option, "level-option"));
    if (option.fallback) {
      // A fallback launches only when its option's own pool is exhausted.
      list.appendChild(
        optionRow(documentNode, option.fallback, "level-option level-fallback"),
      );
    }
  }
  cell.appendChild(list);
  return cell;
}

function levelTable(documentNode, levels) {
  const wrap = el(documentNode, "div", "table-wrap");
  const table = el(documentNode, "table", "items level-table");
  const head = el(documentNode, "tr");
  head.appendChild(el(documentNode, "th", null, "Level"));
  head.appendChild(el(documentNode, "th", null, "Options"));
  table.appendChild(head);
  for (const level of levels) {
    const row = el(documentNode, "tr");
    row.setAttribute("data-level-row", level.name);
    row.appendChild(levelCell(documentNode, level));
    row.appendChild(optionsCell(documentNode, level));
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
      body.appendChild(el(
        documentNode,
        "p",
        "level-source",
        SOURCE_LABELS[result.source] || String(result.source || ""),
      ));
      body.appendChild(levelTable(documentNode, levels));

      const editing = el(documentNode, "div", "level-cli");
      editing.appendChild(el(documentNode, "b", null, "Edit with your harness"));
      const instruction = el(documentNode, "p", null, "tell your agent to use ");
      instruction.appendChild(
        el(documentNode, "code", null, "yoke universe levels set"),
      );
      instruction.appendChild(el(documentNode, "span", null, " or "));
      instruction.appendChild(
        el(documentNode, "code", null, "yoke projects capability-settings"),
      );
      editing.appendChild(instruction);
      body.appendChild(editing);
    },
  );
  return panel;
}

export { SOURCE_LABELS };
