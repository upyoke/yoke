// Settings → Levels: the universe's launch levels, read-only. Each level shows
// its ordered options, the quota pools each option's model draws on, whether
// it can launch now, and where the next launch at that level goes. Every fact
// and every reason is composed by `universe.level_capacity.get`; this module
// renders and never decides. Levels are edited from a harness through the
// CLI, and a project override only through its session-routing capability.

import {
  callFunction, el, renderError, section,
} from "./universe_view_support.js";

const OVERRIDE_COMMAND = "yoke projects capability-settings --cap-type session-routing";

function text(documentNode, tag, className, value) {
  return el(documentNode, tag, className, String(value ?? ""));
}

function pill(documentNode, family, label) {
  return el(documentNode, "span", `pill ${family}`, label);
}

function small(documentNode, value, className) {
  return el(documentNode, "small", className, value);
}

function contextLabel(tokens) {
  if (!tokens) return null;
  return tokens % 1_000_000 === 0 ? `${tokens / 1_000_000}M`
    : tokens % 1_000 === 0 ? `${tokens / 1_000}K` : String(tokens);
}

function percent(value) {
  return value === null || value === undefined ? "unreadable" : `${value}%`;
}

function blockerText(blocker, separator) {
  if (blocker.kind === "no_machine") {
    return `no usable machine offers ${blocker.surface}`;
  }
  return `${blocker.label}${separator}0% left`;
}

// "2026-10-06T18:43:07Z" reads as "2026-10-06 18:43 UTC".
function readStamp(value) {
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(String(value || ""));
  return match ? `${match[1]} ${match[2]} UTC` : String(value || "");
}

function readLine(documentNode, result) {
  const machines = result.usable_machines;
  const workers = Object.entries(result.live_workers || {})
    .map(([surface, count]) => `${surface} ${count}`).join(" · ");
  return text(
    documentNode, "div", "levels-read",
    `Capacity read ${readStamp(result.read_at)}` +
      ` · ${machines} usable machine${machines === 1 ? "" : "s"}` +
      ` · live workers ${workers}`,
  );
}

function levelHead(documentNode, level, index) {
  const head = el(documentNode, "div", "level-head");
  const order = text(documentNode, "span", "level-order", index + 1);
  order.title = "Order";
  head.appendChild(order);
  head.appendChild(text(documentNode, "span", "level-glyph", level.glyph));
  head.appendChild(text(documentNode, "b", "level-name", level.name));
  head.appendChild(text(
    documentNode, "span", "level-count", `${level.options.length} options`,
  ));
  return head;
}

function capacitySummary(documentNode, level) {
  const next = level.next_launch;
  if (!next) {
    const box = el(documentNode, "div", "level-surfaces level-exhausted");
    box.appendChild(pill(documentNode, "crit", "No capacity"));
    const list = el(documentNode, "ul");
    for (const option of level.options) {
      const item = el(documentNode, "li");
      item.appendChild(text(documentNode, "b", null, option.surface));
      const blockers = (option.now.blockers || []).map((b) => blockerText(b, " "));
      item.appendChild(documentNode.createTextNode(
        ` · ${option.display_name}: ${blockers.join(", ")}`,
      ));
      list.appendChild(item);
    }
    box.appendChild(list);
    return box;
  }
  const box = el(documentNode, "div", "level-surfaces");
  box.appendChild(text(documentNode, "span", "level-muted", "Launchable on"));
  for (const surface of level.launchable_surfaces) {
    box.appendChild(pill(documentNode, "good", surface));
  }
  const line = el(documentNode, "div", "level-next");
  line.appendChild(documentNode.createTextNode("Next launch → "));
  line.appendChild(text(
    documentNode, "b", null, `${next.surface} · ${next.display_name}`,
  ));
  line.appendChild(documentNode.createTextNode(
    ` (option ${next.option_index + 1}): ${next.reason}`,
  ));
  box.appendChild(line);
  return box;
}

function cell(documentNode, label, className) {
  const td = el(documentNode, "td", className);
  td.setAttribute("data-label", label);
  return td;
}

function modelCell(documentNode, option) {
  const td = cell(documentNode, "Model", "level-model");
  td.appendChild(text(documentNode, "code", null, option.model));
  td.appendChild(small(
    documentNode,
    `${option.display_name}${option.native_selector ? " · Cursor selector" : ""}`,
  ));
  if (option.fallback) {
    const note = small(
      documentNode,
      `${option.pools[0]?.label || option.surface} exhausted → `,
      "level-fallback",
    );
    note.appendChild(text(documentNode, "code", null, option.fallback.model));
    td.appendChild(note);
  }
  return td;
}

function nowCell(documentNode, option, isNext) {
  const td = cell(documentNode, "Now", "level-now");
  const now = option.now;
  if (now.state === "blocked") {
    td.appendChild(pill(documentNode, "crit", "Blocked"));
    for (const blocker of now.blockers || []) {
      td.appendChild(small(documentNode, blockerText(blocker, " · ")));
    }
    return td;
  }
  td.appendChild(pill(
    documentNode, isNext ? "run" : "good", isNext ? "Next launch" : "Can launch",
  ));
  if (now.via) td.appendChild(small(documentNode, `via ${now.via}`));
  const pool = now.binding_pool;
  const headroom = small(documentNode, "", "level-headroom");
  headroom.appendChild(text(
    documentNode, "b", null,
    pool ? `${pool.headroom}% headroom` : "headroom unreadable",
  ));
  if (pool) {
    headroom.appendChild(documentNode.createTextNode(
      ` · ${pool.label}, ${percent(pool.left)} left`,
    ));
  }
  td.appendChild(headroom);
  return td;
}

function optionRow(documentNode, option, index, isNext) {
  const row = el(documentNode, "tr");
  const rank = cell(documentNode, "Order", "level-rank");
  rank.textContent = String(index + 1);
  row.appendChild(rank);
  const surface = cell(documentNode, "Surface");
  surface.appendChild(text(documentNode, "b", null, option.surface));
  row.appendChild(surface);
  row.appendChild(modelCell(documentNode, option));
  const effort = cell(documentNode, "Effort");
  effort.textContent = option.fallback
    ? `${option.reasoning_effort} / ${option.fallback.reasoning_effort}`
    : option.reasoning_effort;
  row.appendChild(effort);
  const context = cell(documentNode, "Context");
  const window = contextLabel(option.context_window_tokens);
  if (window) context.textContent = window;
  else context.appendChild(text(documentNode, "span", "level-muted", "default"));
  row.appendChild(context);
  const pools = cell(documentNode, "Draws on", "level-pools");
  for (const pool of [...option.pools, ...(option.fallback?.pools || [])]) {
    pools.appendChild(text(documentNode, "span", null, pool.label));
  }
  row.appendChild(pools);
  row.appendChild(nowCell(documentNode, option, isNext));
  return row;
}

function optionsTable(documentNode, level) {
  const wrap = el(documentNode, "div", "table-wrap");
  const table = el(documentNode, "table", "items level-options");
  const head = el(documentNode, "thead");
  const headRow = el(documentNode, "tr");
  for (const label of ["#", "Surface", "Model or selector", "Effort", "Context", "Draws on", "Now"]) {
    headRow.appendChild(text(documentNode, "th", null, label));
  }
  head.appendChild(headRow);
  table.appendChild(head);
  const body = el(documentNode, "tbody");
  level.options.forEach((option, index) => {
    body.appendChild(optionRow(
      documentNode, option, index, level.next_launch?.option_index === index,
    ));
  });
  table.appendChild(body);
  wrap.appendChild(table);
  return wrap;
}

function levelBlock(documentNode, level, index) {
  const block = el(documentNode, "section", "level");
  block.setAttribute("aria-label", level.name);
  block.setAttribute("data-level", level.name);
  block.appendChild(levelHead(documentNode, level, index));
  block.appendChild(capacitySummary(documentNode, level));
  block.appendChild(optionsTable(documentNode, level));
  return block;
}

function overridesTable(documentNode, projects) {
  const wrap = el(documentNode, "div", "table-wrap");
  const table = el(documentNode, "table", "items level-overrides");
  const head = el(documentNode, "thead");
  const headRow = el(documentNode, "tr");
  headRow.appendChild(text(documentNode, "th", null, "Project"));
  headRow.appendChild(text(documentNode, "th", null, "Levels"));
  head.appendChild(headRow);
  table.appendChild(head);
  const body = el(documentNode, "tbody");
  for (const project of projects) {
    const row = el(documentNode, "tr");
    row.setAttribute("data-project", project.project);
    const name = cell(documentNode, "Project");
    name.textContent = project.name;
    row.appendChild(name);
    const levels = cell(documentNode, "Levels");
    if (project.override) {
      levels.appendChild(pill(documentNode, "warn", "Override"));
      for (const [level, change] of project.changes || []) {
        const line = el(documentNode, "div");
        line.appendChild(text(documentNode, "b", null, level));
        line.appendChild(documentNode.createTextNode(` · ${change}`));
        levels.appendChild(line);
      }
    } else {
      levels.appendChild(text(documentNode, "span", "level-muted", "Universe default"));
    }
    row.appendChild(levels);
    body.appendChild(row);
  }
  table.appendChild(body);
  wrap.appendChild(table);
  return wrap;
}

function renderLevels(panel, result) {
  const documentNode = panel.ownerDocument;
  const levels = result.levels || [];
  panel.setCount(levels.length);
  panel.renderEnvelope(null, (body) => {
    body.appendChild(readLine(documentNode, result));
    levels.forEach((level, index) => {
      body.appendChild(levelBlock(documentNode, level, index));
    });
  });
}

function renderOverrides(panel, result) {
  const documentNode = panel.ownerDocument;
  const projects = result.projects || [];
  panel.setCount(projects.filter((project) => project.override).length);
  panel.renderEnvelope(null, (body) => {
    body.appendChild(overridesTable(documentNode, projects));
    const command = el(documentNode, "div", "levels-cli");
    command.appendChild(text(documentNode, "code", null, OVERRIDE_COMMAND));
    body.appendChild(command);
  });
}

export async function renderLevelsView(context, main) {
  const documentNode = context.document;
  main.replaceChildren();
  const stack = el(documentNode, "div", "levels");
  const levelsPanel = section(documentNode, "Levels");
  levelsPanel.classList.add("levels-panel");
  const viewOnly = text(documentNode, "span", "levels-view-only", "View only");
  levelsPanel.children[0].appendChild(viewOnly);
  const overridesPanel = section(documentNode, "Project overrides");
  overridesPanel.classList.add("levels-overrides-panel");
  stack.appendChild(levelsPanel);
  stack.appendChild(overridesPanel);
  main.appendChild(stack);

  let callResult;
  try {
    callResult = await callFunction(context.client, "universe.level_capacity.get", {});
  } catch (fetchError) {
    callResult = {
      status: 0,
      envelope: { success: false, error: { message: String(fetchError) } },
    };
  }
  if (!context.isMounted()) return;
  if (callResult.status !== 200 || !callResult.envelope.success) {
    levelsPanel.renderEnvelope(callResult, renderError);
    stack.removeChild(overridesPanel);
    return;
  }
  const result = callResult.envelope.result || {};
  renderLevels(levelsPanel, result);
  renderOverrides(overridesPanel, result);
}

export { OVERRIDE_COMMAND };
