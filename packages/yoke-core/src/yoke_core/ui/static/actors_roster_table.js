// One Team roster table: people or machine accounts, with sortable headers.

import { ACTOR_SORT_COLUMNS, actorGrants, projectAccess } from "./actor_roster_sort.js";
import { roleControl } from "./actor_role_control.js";
import { sortHeader } from "./item_roster_sort.js";
import { callFunction, el, labelCellsByColumn } from "./universe_view_support.js";

function pill(documentNode, label, tone) {
  return el(documentNode, "span", `pill ${tone}`, label);
}

function actorCell(documentNode, actor, currentActorId) {
  const isCurrent = actor.id === currentActorId;
  const cell = el(documentNode, "td");
  const identity = el(documentNode, "div", "actors-identity");
  const avatar = el(
    documentNode, "span",
    `actor-avatar${actor.kind === "system" || !isCurrent ? " sys" : " current"}`,
    actor.kind === "system" ? "⚙" : (actor.name || "?").slice(0, 1),
  );
  avatar.setAttribute("aria-hidden", "true");
  identity.appendChild(avatar);
  const details = el(documentNode, "div");
  const name = el(documentNode, "div", "actors-name", actor.name);
  if (isCurrent) name.appendChild(el(documentNode, "span", "actors-muted", " (you)"));
  details.appendChild(name);
  details.appendChild(el(documentNode, "div", "actors-muted", `actor #${actor.id}`));
  identity.appendChild(details);
  cell.appendChild(identity);
  return cell;
}

// A person's role is a control for an org admin; a server that does not
// yet send person_org_roles shows every grant read-only.
function orgRoleCell(documentNode, actor, roster, feedback, reload) {
  const cell = el(documentNode, "td");
  const personRoles = roster.person_org_roles;
  if (roster.can_manage_actors && actor.kind === "human"
      && Array.isArray(personRoles) && personRoles.length) {
    cell.appendChild(roleControl(documentNode, actor, personRoles, roster, feedback, reload));
    return cell;
  }
  const roles = actor.roles?.org || [];
  if (!roles.length) cell.appendChild(el(documentNode, "span", "actors-muted", "—"));
  for (const role of roles) cell.appendChild(pill(
    documentNode, role.role, role.role === "admin" ? "run" : "idle",
  ));
  return cell;
}

// A role chip carries the server's description of the role on hover; a
// server that does not yet send role_descriptions shows the bare role.
function roleChip(documentNode, role, roster) {
  const chip = el(documentNode, "span", "actors-role", role);
  const description = roster.role_descriptions?.[role];
  if (description) chip.title = description;
  return chip;
}

function projectAccessCell(documentNode, actor, roster) {
  const cell = el(documentNode, "td");
  const entries = projectAccess(actor);
  if (!entries.length) cell.appendChild(el(documentNode, "span", "actors-muted", "—"));
  for (const entry of entries) {
    const access = el(documentNode, "span", "actors-access");
    if (entry.from) {
      access.appendChild(el(documentNode, "b", null, entry.project));
      access.appendChild(el(documentNode, "span", "actors-muted", ` · from org ${entry.from}`));
    } else {
      access.appendChild(el(documentNode, "span", null, `${entry.project} · `));
      access.appendChild(roleChip(documentNode, entry.role, roster));
    }
    cell.appendChild(access);
  }
  return cell;
}

// Each machine grant names its scope, its role, how the role may be held and
// what it allows. Tags and descriptions come from the roster read, so a
// server that does not yet send them shows scope and role alone.
function grantsCell(documentNode, actor, roster) {
  const cell = el(documentNode, "td", "actors-grants");
  const grants = actorGrants(actor);
  if (!grants.length) cell.appendChild(el(documentNode, "span", "actors-muted", "—"));
  const listed = (field, role) => Array.isArray(roster[field]) && roster[field].includes(role);
  for (const grant of grants) {
    const row = el(documentNode, "div", "actors-grant");
    const head = el(documentNode, "div", "actors-grant-head");
    head.appendChild(el(documentNode, "span", "actors-grant-scope", grant.scope));
    head.appendChild(el(documentNode, "span", "actors-role", grant.role));
    if (listed("machine_only_roles", grant.role)) {
      head.appendChild(el(documentNode, "span", "actors-tag", "machine-only"));
    }
    if (listed("bootstrap_only_roles", grant.role)) {
      head.appendChild(el(documentNode, "span", "actors-tag", "bootstrap-granted"));
    }
    row.appendChild(head);
    const description = roster.role_descriptions?.[grant.role];
    if (description) row.appendChild(el(documentNode, "div", "actors-muted", description));
    cell.appendChild(row);
  }
  return cell;
}

function keysCell(documentNode, actor) {
  const cell = el(documentNode, "td", "actors-keys");
  if (!actor.tokens?.length) {
    cell.appendChild(el(documentNode, "span", "actors-muted", "No active keys"));
    return cell;
  }
  for (const token of actor.tokens) {
    const machine = token.machine_id ? ` · machine ${token.machine_name || token.machine_id}` : "";
    cell.appendChild(el(
      documentNode, "div", "actors-key",
      `${token.name} (#${token.token_id}) · last used ${token.last_used_at || "never"}${machine}`,
    ));
  }
  return cell;
}

function actionCell(documentNode, actor, roster, feedback, reload) {
  const cell = el(documentNode, "td");
  if (!roster.can_manage_actors || actor.id === roster.current_actor_id) {
    cell.appendChild(el(documentNode, "span", "actors-muted", "—"));
    return cell;
  }
  const enabling = actor.status === "disabled";
  const button = el(documentNode, "button", "button", enabling ? "Enable" : "Disable");
  button.type = "button";
  const change = async (confirm, cancel) => {
    if (confirm.disabled) return;
    confirm.disabled = true;
    if (cancel) cancel.disabled = true;
    feedback.textContent = enabling ? "Enabling actor…" : "Disabling actor…";
    try {
      const changed = await callFunction(roster.client, "actors.state.set", {
        actor_id: actor.id, enabled: enabling,
      });
      if (changed.status === 200 && changed.envelope?.success) {
        await reload();
        return;
      }
      feedback.textContent = changed.envelope?.error?.message || "Actor update failed; retry.";
    } catch (error) {
      feedback.textContent = `${error}; retry the action.`;
    }
    confirm.disabled = false;
    if (cancel) cancel.disabled = false;
  };
  button.addEventListener("click", () => {
    if (enabling) { change(button); return; }
    const warning = el(documentNode, "p", "actors-confirm-copy",
      `Disable ${actor.name}? Their API keys will be revoked.`);
    const confirm = el(documentNode, "button", "item-button danger", `Disable ${actor.name}`);
    const cancel = el(documentNode, "button", "item-button", "Cancel");
    confirm.type = cancel.type = "button";
    confirm.addEventListener("click", () => change(confirm, cancel));
    cancel.addEventListener("click", () => { cell.replaceChildren(button); button.focus(); });
    cell.replaceChildren(warning, confirm, cancel);
    confirm.focus();
  });
  cell.appendChild(button);
  return cell;
}

const CELLS = {
  Actor: (d, actor, roster) => actorCell(d, actor, roster.current_actor_id),
  State: (d, actor) => {
    const cell = el(d, "td");
    cell.appendChild(pill(d, actor.status || "active", actor.status === "disabled" ? "idle" : "good"));
    return cell;
  },
  "Org role": (d, actor, roster, feedback, reload) => orgRoleCell(d, actor, roster, feedback, reload),
  "Project access": (d, actor, roster) => projectAccessCell(d, actor, roster),
  Grants: (d, actor, roster) => grantsCell(d, actor, roster),
  "Member email": (d, actor) => el(d, "td", "actors-muted", actor.identity?.email || "—"),
  "API keys": (d, actor) => keysCell(d, actor),
  Action: (d, actor, roster, feedback, reload) => actionCell(d, actor, roster, feedback, reload),
};

// `roster` is the actors.roster result plus the live `client`; `reload`
// re-reads the roster after an enable, disable, or role change lands.
export function renderActorTable(documentNode, {
  actors, columns, roster, sort, onSort, feedback, reload,
}) {
  const tableWrap = el(documentNode, "div", "table-wrap");
  const table = el(documentNode, "table", "items actors-table table-stacks-narrow");
  const head = el(documentNode, "thead");
  const headings = el(documentNode, "tr");
  for (const label of columns) headings.appendChild(ACTOR_SORT_COLUMNS[label]
    ? sortHeader(documentNode, label, sort, onSort, ACTOR_SORT_COLUMNS[label])
    : el(documentNode, "th", null, label));
  head.appendChild(headings);
  table.appendChild(head);
  const tbody = el(documentNode, "tbody");
  for (const actor of actors) {
    const tr = el(documentNode, "tr");
    for (const label of columns) {
      tr.appendChild(CELLS[label](documentNode, actor, roster, feedback, reload));
    }
    labelCellsByColumn(tr, columns);
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  tableWrap.appendChild(table);
  return tableWrap;
}
