// Everyone and everything permitted to act in this universe. The roster is
// read from the engine; the browser offers no grant or revoke controls.

import {
  callFunction, el, portabilityMode, renderError,
} from "./universe_view_support.js";

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

function projectAccess(actor) {
  const grants = (actor.roles?.projects || []).map(
    (row) => `${row.role} · ${row.project}`,
  );
  if ((actor.roles?.org || []).some((row) => row.role === "admin")) {
    grants.unshift("all projects");
  }
  return grants.length ? grants.join(", ") : "—";
}

function renderRoster(body, result, hosted) {
  const documentNode = body.ownerDocument;
  const rows = Array.isArray(result.rows) ? result.rows : [];
  const tableWrap = el(documentNode, "div", "table-wrap");
  const table = el(documentNode, "table", "items actors-table");
  const head = el(documentNode, "thead");
  const headings = el(documentNode, "tr");
  for (const label of [
    "Actor", "Kind", "Org role", "Project access", ...(hosted ? ["Account"] : []),
  ]) headings.appendChild(el(documentNode, "th", null, label));
  head.appendChild(headings);
  table.appendChild(head);
  const tbody = el(documentNode, "tbody");
  for (const actor of rows) {
    const tr = el(documentNode, "tr");
    tr.appendChild(actorCell(documentNode, actor, result.current_actor_id));
    const kind = el(documentNode, "td");
    kind.appendChild(pill(
      documentNode, actor.kind, actor.kind === "human" ? "good" : "idle",
    ));
    tr.appendChild(kind);
    const orgRole = el(documentNode, "td");
    const orgRoles = actor.roles?.org || [];
    if (orgRoles.length) {
      for (const role of orgRoles) orgRole.appendChild(pill(
        documentNode, role.role, role.role === "admin" ? "run" : "idle",
      ));
    } else orgRole.appendChild(el(documentNode, "span", "actors-muted", "—"));
    tr.appendChild(orgRole);
    tr.appendChild(el(documentNode, "td", "actors-muted", projectAccess(actor)));
    if (hosted) tr.appendChild(el(
      documentNode, "td", "actors-muted", actor.identity?.email || "—",
    ));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  tableWrap.appendChild(table);
  body.replaceChildren(tableWrap);
  if (!rows.length) body.appendChild(el(
    documentNode, "p", "empty actors-empty", "No actors are registered in this universe.",
  ));
  return rows;
}

export async function renderActorsView(context, main) {
  const documentNode = context.document;
  const mode = portabilityMode(context.capabilities);
  const lead = el(
    documentNode, "p", "actors-lead",
    "Everyone and everything that can act in this universe, and what each may do.",
  );
  const localNotice = el(documentNode, "div", "panel actors-local-notice");
  localNotice.hidden = true;
  const panel = el(documentNode, "section", "panel actors-panel");
  const body = el(documentNode, "div", "panel-body actors-body", "Loading actors…");
  body.setAttribute("role", "status");
  panel.appendChild(body);
  main.replaceChildren(lead, localNotice, panel);

  let callResult;
  try {
    callResult = await callFunction(context.client, "actors.roster", {});
  } catch (error) {
    callResult = {
      status: 0,
      envelope: { success: false, error: { message: String(error) } },
    };
  }
  if (!context.isMounted() || !main.contains(panel)) return;
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
  const rows = renderRoster(body, callResult.envelope.result || {}, mode === "hosted");
  if (mode === "local" && rows.length === 1 && rows[0].kind === "human") {
    const noticeBody = el(documentNode, "div", "panel-body actors-local-body");
    noticeBody.appendChild(pill(documentNode, "sole actor", "idle"));
    noticeBody.appendChild(el(
      documentNode, "span", "actors-muted",
      "You hold the database, so there is nothing to grant. This screen fills in when a second actor exists — a teammate, or an API token for CI.",
    ));
    localNotice.replaceChildren(noticeBody);
    localNotice.hidden = false;
  }
}
