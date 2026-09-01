import { buildUniverseRoute } from "./universe_navigation.js";
import {
  el,
  loadSection,
  portabilityMode,
  renderTable,
  section,
} from "./universe_view_support.js";
import {
  labelledFact,
  metricStrip,
} from "./universe_secondary_primitives.js";

function createProjectNote(documentNode, capabilities) {
  const panel = section(documentNode, "Create project", { showRaw: false });
  panel.classList.add("create-project-note");
  panel.renderEnvelope(
    { status: 200, envelope: { success: true, result: {} } },
    (body) => {
      const mode = portabilityMode(capabilities);
      if (mode === "hosted") {
        body.appendChild(el(
          documentNode,
          "p",
          "secondary-muted",
          "Use the hosted project setup section below. It will register the " +
            "project in this universe after the host finishes provisioning it.",
        ));
        return;
      }
      body.appendChild(el(
        documentNode,
        "p",
        "secondary-muted",
        "Create from a checkout with the registered operator command:",
      ));
      const line = el(documentNode, "div", "project-create-line");
      line.appendChild(el(
        documentNode,
        "code",
        null,
        "yoke projects create --slug <slug> --name <name> "
        + "--public-item-prefix <PREFIX>",
      ));
      body.appendChild(line);
    },
  );
  return panel;
}

export function renderProjectsView(context, main) {
  const documentNode = context.document;
  const panel = section(documentNode, "Projects");
  main.replaceChildren(panel, createProjectNote(
    documentNode,
    context.capabilities,
  ));
  loadSection(
    context,
    panel,
    "projects.list",
    { include_summary: true },
    (body, callResult) => {
      const rows = (callResult.envelope.result || {}).rows || [];
      panel.setCount(rows.length);
      const sum = (key) => rows.reduce(
        (total, row) => total + (Number(row[key]) || 0),
        0,
      );
      body.appendChild(metricStrip(documentNode, [
        { label: "projects", value: rows.length },
        { label: "in flight", value: sum("in_flight_count") },
        { label: "ready", value: sum("ready_count"), tone: "good" },
        { label: "blocked", value: sum("blocked_count"), tone: "warn" },
        { label: "strategy docs", value: sum("strategy_doc_count") },
      ]));
      renderTable(body, rows, [
        {
          label: "project",
          value: (row) => `${row.emoji || "▤"} ${row.name || row.slug}`,
          href: (row) => buildUniverseRoute("project", String(row.id)),
        },
        { label: "slug", value: (row) => row.slug, mono: true },
        {
          label: "repository",
          value: (row) => row.github_repo || "—",
          href: (row) => row.github_repo
            ? `https://github.com/${row.github_repo}`
            : null,
        },
        { label: "in flight", value: (row) => row.in_flight_count },
        { label: "ready", value: (row) => row.ready_count },
        { label: "blocked", value: (row) => row.blocked_count },
        {
          label: "strategy",
          value: (row) => row.has_strategy
            ? `${row.strategy_doc_count} docs` : "not started",
        },
      ], "no projects yet");
    },
  );
}

export function renderProjectView(context, main, scope) {
  const documentNode = context.document;
  const panel = section(documentNode, "Project settings");
  main.replaceChildren(panel);
  loadSection(
    context,
    panel,
    "projects.get",
    { project: String(scope) },
    (body, callResult) => {
      const row = (callResult.envelope.result || {}).row || {};
      const heading = el(documentNode, "div", "secondary-card-header");
      const title = el(documentNode, "div");
      title.appendChild(el(
        documentNode,
        "h3",
        null,
        `${row.emoji || "▤"} ${row.name || row.slug || "Project"}`,
      ));
      title.appendChild(el(
        documentNode,
        "p",
        "secondary-muted",
        row.slug || "",
      ));
      heading.appendChild(title);
      body.appendChild(heading);

      const grid = el(documentNode, "div", "project-settings-grid");
      for (const [label, value] of [
        ["Project id", row.id],
        ["Public item prefix", row.public_item_prefix],
        ["Default branch", row.default_branch],
        ["GitHub repository", row.github_repo || "Not connected"],
        ["GitHub sync", row.github_sync_mode || "Not configured"],
        ["Created", row.created_at],
      ]) {
        grid.appendChild(labelledFact(documentNode, label, value));
      }
      body.appendChild(grid);

      const actions = el(documentNode, "div", "secondary-action-row");
      const back = el(documentNode, "a", "row-link", "All projects →");
      back.href = buildUniverseRoute("projects", null);
      actions.appendChild(back);
      if (row.github_repo) {
        const repo = el(documentNode, "a", "row-link", "Open repository ↗");
        repo.href = `https://github.com/${row.github_repo}`;
        actions.appendChild(repo);
      }
      body.appendChild(actions);
    },
  );
}
