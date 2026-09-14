import { buildUniverseRoute } from "./universe_navigation.js";
import {
  callFunction,
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
import {
  renderProjectLaneSummary,
} from "./universe_views_project_lanes.js";

function createProjectNote(documentNode, capabilities) {
  const panel = section(documentNode, "Create project");
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
          href: (row) => buildUniverseRoute("projects", null, String(row.id)),
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
            ? `${row.strategy_doc_count} ${Number(row.strategy_doc_count) === 1 ? "doc" : "docs"}`
            : "not started",
        },
      ], "no projects yet");
    },
  );
}

export function titleLimitCard(context, scope, effectiveLimit) {
  const documentNode = context.document;
  const card = el(documentNode, "div", "project-settings-title-limit");
  card.appendChild(el(
    documentNode,
    "p",
    "secondary-muted",
    "Applies to new item and epic-task titles, and to explicit title " +
    "edits. Existing titles are never affected.",
  ));
  const row = el(documentNode, "div", "project-settings-title-limit-row");
  // A <label> wrapping only the input is a programmatic label — the same
  // implicit-association idiom item_intake_controls.itemIntakeField uses.
  // Save is a sibling, not nested inside the label with the input.
  const field = el(documentNode, "label");
  field.appendChild(el(
    documentNode, "span", "item-form-label", "Title character limit",
  ));
  const input = el(documentNode, "input", "project-settings-title-limit-input");
  input.type = "number";
  input.min = "10";
  input.step = "1";
  input.value = String(effectiveLimit);
  field.appendChild(input);
  row.appendChild(field);
  const status = el(
    documentNode, "span", "project-settings-title-limit-status secondary-muted",
  );
  const save = el(documentNode, "button", "row-link", "Save");
  save.type = "button";
  save.addEventListener("click", async () => {
    status.textContent = "";
    save.disabled = true;
    let result;
    try {
      result = await callFunction(
        context.client,
        "projects.capability_settings.merge",
        {
          project: String(scope),
          cap_type: "project-policy",
          assignments: { title_max_length: Number(input.value) },
        },
      );
    } catch (callError) {
      save.disabled = false;
      status.textContent = String(callError);
      return;
    }
    save.disabled = false;
    if (!result.envelope.success) {
      status.textContent =
        result.envelope?.error?.message || "Could not save the title limit.";
      return;
    }
    status.textContent = "Saved.";
  });
  row.appendChild(save);
  card.appendChild(row);
  card.appendChild(status);
  return card;
}

export function renderProjectView(context, main, scope) {
  const documentNode = context.document;
  const panel = section(documentNode, "Project settings");
  // The lane summary reads the project the route opened, not the remembered
  // list selection, so opening a second project shows that project's lanes.
  main.replaceChildren(panel, renderProjectLaneSummary(context, scope));
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

      const titleLimitHost = el(documentNode, "div");
      body.appendChild(titleLimitHost);
      callFunction(
        context.client,
        "workflows.definition.get",
        { project: String(scope) },
      ).then((limitResult) => {
        if (!context.isMounted()) return;
        const limit = limitResult.envelope?.result?.title_max_length;
        if (limitResult.status === 200 && limitResult.envelope.success && limit) {
          titleLimitHost.replaceChildren(titleLimitCard(context, scope, limit));
        }
      }).catch(() => {
        // The title-limit card is an enhancement to an already-rendered
        // panel; a failed read here leaves the panel as-is rather than
        // surfacing a second error alongside the project facts above.
      });

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
