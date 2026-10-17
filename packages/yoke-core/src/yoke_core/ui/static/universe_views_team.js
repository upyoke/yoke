// Actor authority and nonsecret credential inventory for this universe.

import { normalizeActorSort, sortActors } from "./actor_roster_sort.js";
import { renderActorTable } from "./actors_roster_table.js";
import { renderInvitesTable } from "./actor_invites_table.js";
import { openInviteForm, renderInviteResult } from "./actor_invite_form.js";
import { localReachabilityNotice } from "./local_reachability_notice.js";
import { refreshScreenSort } from "./universe_app_shell_support.js";
import {
  callFunction, el, isRegistrySkewError, portabilityMode, renderError,
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
      columns: ["Actor", "State", "Grants", "API keys"],
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

export function renderTeamView(context, main, _scope, _detail, chrome = {}) {
  const documentNode = context.document;
  const mode = portabilityMode(context.capabilities);
  const hosted = mode === "hosted";
  const preferences = context.screenPreferences;
  const view = { showDisabled: false, showUsed: false };
  let roster = {}, rows = [], invites = [], fact = null, inviteRead = null, formOpen = false, generation = 0;
  let sort = normalizeActorSort(preferences?.sortFor(SORT_VIEW));
  const localNotice = el(documentNode, "div", "panel actors-local-notice");
  localNotice.hidden = mode !== "local";
  const controls = el(documentNode, "div", "actors-controls");
  const body = el(documentNode, "div", "actors-body", "Loading team…");
  const feedback = el(documentNode, "p", "actors-muted");
  feedback.setAttribute("role", "status");
  body.setAttribute("role", "status");
  main.replaceChildren(localNotice, controls, body, feedback);
  const panel = groupPanel(documentNode, "Invites", 0, () => null);
  panel.classList.add("actors-invites");
  const header = panel.children[0], inviteBody = panel.children[1];
  const slot = el(documentNode, "div", "actors-invite-slot");
  const listing = el(documentNode, "div", null, "Loading invites…");
  listing.setAttribute("role", "status");
  inviteBody.replaceChildren(slot, listing);
  if (mode !== "local") main.replaceChildren(localNotice, controls, body, panel, feedback);
  const active = () => context.isMounted() && main.contains(body);
  const success = (response) => response?.status === 200 && response.envelope?.success;
  const read = (id, payload = {}) => callFunction(context.client, id, payload)
    .catch(() => ({ status: 0, envelope: { success: false, error: { message: "Could not reach the server." } } }));
  const invite = el(documentNode, "button", "item-button primary", "Invite");
  invite.type = "button";
  const canInvite = () => mode !== "local" && roster.can_manage_actors
    && Array.isArray(roster.person_org_roles) && roster.person_org_roles.length
    && success(inviteRead) && ["code", "email"].includes(fact?.invite_form);
  const head = () => {
    invite.disabled = formOpen;
    chrome.setPageHead?.({ title: "Team", actions: canInvite() ? [invite] : [] });
  };
  const done = async () => { formOpen = false; head(); await reload(); if (active() && canInvite()) invite.focus(); };
  const created = (result) => {
    if (result) {
      formOpen = false;
      renderInviteResult(context, slot, result, { onDone: done });
      head();
    }
    void reload();
  };
  invite.addEventListener("click", () => {
    if (!canInvite() || formOpen) return;
    formOpen = true;
    head();
    openInviteForm(context, slot, {
      fact, roles: roster.person_org_roles, roleDescriptions: roster.role_descriptions || {}, roster: rows,
      onCreated: created,
      onCancel: () => { formOpen = false; head(); invite.focus(); },
    });
  });
  const onSort = (column) => {
    const direction = sort.column === column && sort.direction === "asc" ? "desc" : "asc";
    const chosen = normalizeActorSort({ column, direction });
    sort = chosen;
    feedback.textContent = "";
    preferences?.saveSortFor(SORT_VIEW, chosen).then((notice) => {
      if (chosen === sort && active()) feedback.textContent = notice;
    });
    draw();
  };
  const draw = () => {
    const disabledCount = rows.filter((row) => row.status === "disabled").length;
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
    if (mode === "local") {
      localNotice.replaceChildren(localReachabilityNotice(documentNode));
      if (rows.length === 1 && rows[0].kind === "human") localNotice.appendChild(el(
        documentNode, "p", "actors-muted", "You are the only actor in this universe.",
      ));
    }
  };
  const changeInvite = async (row, action) => {
    if (formOpen) return { envelope: { error: { message: "Finish or cancel the open invite form first." } } };
    const response = await read(`${row.kind === "email" ? "identity.invite" : "teammate_invites"}.${action}`, { invite_id: row.invite_id });
    if (!active()) return response;
    if (success(response)) {
      if (action === "reissue") renderInviteResult(context, slot, response.envelope.result, { onDone: done });
      await reload();
    } else if (response.envelope?.error?.code === "result_unavailable") {
      feedback.textContent = "This invite was already reissued. Its code cannot be shown again. Use Reissue for a new code.";
      await reload();
    }
    return response;
  };
  const drawInvites = () => {
    if (mode === "local") return;
    listing.replaceChildren();
    listing.removeAttribute("role");
    const title = el(documentNode, "h2", null, "Invites");
    header.replaceChildren(title);
    if (!roster.can_manage_actors) listing.appendChild(el(documentNode, "p", "actors-muted", "Only org admins can invite people."));
    if (!success(inviteRead)) {
      if (!roster.can_manage_actors && [401, 403].includes(inviteRead?.status)) return;
      if (isRegistrySkewError(inviteRead?.envelope?.error)) {
        listing.appendChild(el(documentNode, "p", "actors-muted", "Invites need a newer Yoke server. Ask the server operator to upgrade, then reload."));
      } else {
        renderError(listing, inviteRead);
        listing.appendChild(el(documentNode, "p", "actors-muted", "Invites could not be read."));
        const retry = el(documentNode, "button", "item-button machines-retry", "Try again");
        retry.type = "button";
        retry.addEventListener("click", () => { retry.disabled = true; void reload(); });
        listing.appendChild(retry);
      }
      return;
    }
    if (roster.can_manage_actors && !roster.person_org_roles?.length) listing.appendChild(el(documentNode, "p", "actors-muted",
      "Invite roles are unavailable. Ask the server operator to upgrade, then reload."));
    const used = invites.filter((row) => row.state === "consumed" || row.status === "accepted").length;
    title.appendChild(el(documentNode, "span", "panel-count", `· ${invites.length - (view.showUsed ? 0 : used)}`));
    if (used) {
      const label = el(documentNode, "label", "actors-show-disabled");
      const input = el(documentNode, "input");
      input.type = "checkbox";
      input.checked = view.showUsed;
      input.addEventListener("change", () => { view.showUsed = input.checked; drawInvites(); });
      label.appendChild(input);
      label.appendChild(el(documentNode, "span", null, `Show used (${used})`));
      header.appendChild(label);
    }
    const table = el(documentNode, "div");
    listing.appendChild(table);
    renderInvitesTable(context, table, invites, {
      canManage: Boolean(canInvite()), showUsed: view.showUsed, roleDescriptions: roster.role_descriptions,
      onRevoke: (row) => changeInvite(row, "revoke"), onReissue: (row) => changeInvite(row, "reissue"),
    });
  };
  const reload = async () => {
    if (!active()) return;
    const current = ++generation;
    const rosterRead = read("actors.roster");
    const invitesRead = mode === "local" ? Promise.resolve(null) : read("teammate_invites.list", { include_used: true }).then(async (response) => {
      if (!success(response) || response.envelope.result?.invite_form !== "email") return response;
      const email = await read("identity.invite.list");
      return success(email) ? { ...response, envelope: { ...response.envelope, result: {
        ...response.envelope.result,
        invites: [...(response.envelope.result.invites || []), ...(email.envelope.result?.invites || []).map((row) => ({ ...row, kind: "email" }))],
      } } } : email;
    });
    const response = await rosterRead;
    if (!active() || current !== generation) return;
    body.removeAttribute("role");
    roster = success(response) ? { ...response.envelope.result, client: context.client } : {};
    rows = Array.isArray(roster.rows) ? roster.rows : [];
    if (success(response)) draw();
    else {
      body.replaceChildren();
      renderError(body, response);
      body.appendChild(el(documentNode, "p", "actors-muted", "Refresh the page. If the read still fails, check the Yoke server and your actor access."));
    }
    inviteRead = await invitesRead;
    if (!active() || current !== generation) return;
    fact = success(inviteRead) ? inviteRead.envelope.result : null;
    invites = Array.isArray(fact?.invites) ? fact.invites : [];
    head();
    drawInvites();
  };
  if (mode === "local") localNotice.appendChild(localReachabilityNotice(documentNode));
  head();
  const notice = preferences ? refreshScreenSort(context.client, preferences, SORT_VIEW).then((message) => {
    if (active()) { sort = normalizeActorSort(preferences.sortFor(SORT_VIEW)); feedback.textContent = message; if (rows.length) draw(); }
  }) : Promise.resolve();
  return Promise.all([reload(), notice]);
}
