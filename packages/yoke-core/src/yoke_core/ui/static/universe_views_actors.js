// Actor authority and nonsecret credential inventory for this universe.

import { normalizeActorSort, sortActors } from "./actor_roster_sort.js";
import { renderActorTable } from "./actors_roster_table.js";
import { refreshScreenSort } from "./universe_app_shell_support.js";
import {
  callFunction, el, portabilityMode, renderError,
} from "./universe_view_support.js";

const SORT_VIEW = "actors";

function groups(hosted) {
  return [
    {
      title: "People", includes: (actor) => actor.kind === "human",
      columns: [
        "Actor", "State", "Org role", "Project access",
        ...(hosted ? ["Member email"] : []), "API keys", "Action",
      ],
    },
    {
      title: "Machine accounts", includes: (actor) => actor.kind !== "human",
      columns: ["Actor", "State", "Org role", "Project access", "API keys"],
    },
  ];
}

function showDisabledToggle(documentNode, disabledCount, view, redraw) {
  const label = el(documentNode, "label", "actors-show-disabled");
  const input = el(documentNode, "input");
  input.type = "checkbox";
  input.checked = view.showDisabled;
  input.addEventListener("change", () => { view.showDisabled = input.checked; redraw(); });
  label.appendChild(input);
  label.appendChild(el(documentNode, "span", null, `Show disabled (${disabledCount})`));
  return label;
}

function groupPanel(documentNode, title, shown, table) {
  const panel = el(documentNode, "section", "panel actors-panel");
  const header = el(documentNode, "div", "panel-header");
  const heading = el(documentNode, "h2", null, title);
  heading.appendChild(el(documentNode, "span", "panel-count", `· ${shown}`));
  header.appendChild(heading);
  const body = el(documentNode, "div", "panel-body actors-group-body");
  body.appendChild(shown ? table() : el(documentNode, "p", "empty actors-empty", "None active."));
  panel.appendChild(header);
  panel.appendChild(body);
  return panel;
}

export function renderActorsView(context, main) {
  return renderActors(context, main, { showDisabled: false });
}

// `view` carries the Show disabled choice across the re-read that follows an
// enable or disable, so acting on a disabled actor keeps it in sight.
async function renderActors(context, main, view) {
  const documentNode = context.document;
  const mode = portabilityMode(context.capabilities);
  const hosted = mode === "hosted";
  const preferences = context.screenPreferences;
  const localNotice = el(documentNode, "div", "panel actors-local-notice");
  localNotice.hidden = true;
  const controls = el(documentNode, "div", "actors-controls");
  const body = el(documentNode, "div", "actors-body", "Loading actors…");
  const feedback = el(documentNode, "p", "actors-muted");
  feedback.setAttribute("role", "status");
  body.setAttribute("role", "status");
  main.replaceChildren(localNotice, controls, body, feedback);

  const readRoster = callFunction(context.client, "actors.roster", {}).catch((error) => ({
    status: 0, envelope: { success: false, error: { message: String(error) } },
  }));
  const [callResult, sortNotice] = await Promise.all([
    readRoster, preferences ? refreshScreenSort(context.client, preferences, SORT_VIEW) : "",
  ]);
  if (!context.isMounted() || !main.contains(body)) return;
  body.removeAttribute("role");
  if (callResult.status !== 200 || !callResult.envelope?.success) {
    body.replaceChildren();
    renderError(body, callResult);
    body.appendChild(el(
      documentNode, "p", "actors-muted",
      "Refresh the page. If the read still fails, check the Yoke server and your actor access.",
    ));
    return;
  }
  const result = callResult.envelope.result || {};
  const rows = Array.isArray(result.rows) ? result.rows : [];
  const roster = { ...result, client: context.client };
  const disabledCount = rows.filter((row) => row.status === "disabled").length;
  let sort = normalizeActorSort(preferences?.sortFor(SORT_VIEW));
  feedback.textContent = sortNotice;
  const reload = async () => {
    if (context.isMounted() && main.contains(body)) await renderActors(context, main, view);
  };
  const onSort = (column) => {
    const direction = sort.column === column && sort.direction === "asc" ? "desc" : "asc";
    const chosen = normalizeActorSort({ column, direction });
    sort = chosen;
    feedback.textContent = "";
    preferences?.saveSortFor(SORT_VIEW, chosen).then((notice) => {
      if (chosen === sort && context.isMounted() && main.contains(body)) feedback.textContent = notice;
    });
    draw();
  };
  const draw = () => {
    controls.replaceChildren();
    if (disabledCount) controls.appendChild(showDisabledToggle(documentNode, disabledCount, view, draw));
    const visible = view.showDisabled ? rows : rows.filter((row) => row.status !== "disabled");
    body.replaceChildren();
    for (const group of groups(hosted)) {
      if (!rows.some(group.includes)) continue;
      const actors = sortActors(visible.filter(group.includes), sort);
      body.appendChild(groupPanel(documentNode, group.title, actors.length, () => renderActorTable(
        documentNode, { actors, columns: group.columns, roster, sort, onSort, feedback, reload },
      )));
    }
    if (!rows.length) body.appendChild(el(
      documentNode, "p", "empty actors-empty", "No actors are registered in this universe.",
    ));
  };
  draw();
  if (mode === "local" && rows.length === 1 && rows[0].kind === "human") {
    localNotice.replaceChildren(el(
      documentNode, "div", "panel-body actors-muted", "You are the only actor in this universe.",
    ));
    localNotice.hidden = false;
  }
}
