// Profile: the signed-in person's own page, reached from the actor menu.
// One profile.get read feeds five cards — who you are, what you can do, API
// tokens, preferences, and the onboarding reset. Each card draws its own
// failure so a refused read names itself instead of blanking the page.

import { buildUniverseRoute } from "./universe_navigation.js";
import { relativeAgePhrase, setDisplayTimeZone } from "./universe_time.js";
import {
  callFunction, el, renderError, section,
} from "./universe_view_support.js";

const READ_FAILED = { status: 0, envelope: { success: false, error: {} } };

function keyValueRows(documentNode, rows) {
  const list = el(documentNode, "dl", "profile-facts");
  for (const [label, value] of rows) {
    if (value === null || value === undefined || value === "") continue;
    list.appendChild(el(documentNode, "dt", null, label));
    const dd = el(documentNode, "dd");
    if (typeof value === "string") dd.textContent = value;
    else dd.appendChild(value);
    list.appendChild(dd);
  }
  return list;
}

function whoCard(documentNode, profile) {
  const actorId = el(documentNode, "code", null, `#${profile.actor.id}`);
  const identity = profile.identity || {};
  return keyValueRows(documentNode, [
    ["Name", profile.actor.name],
    ["Email", identity.email],
    ["Signed in with", identity.signed_in_with],
    ["Actor id", actorId],
  ]);
}

function rolesCard(documentNode, profile) {
  const rows = [
    ...profile.roles.org.map((row) => [row.org, `${row.role} · organization`]),
    ...profile.roles.projects.map((row) => [
      row.name || row.project, `${row.role} on ${row.project}`,
    ]),
  ];
  if (!rows.length) return el(documentNode, "p", "muted", "No roles yet.");
  const list = el(documentNode, "div", "profile-list");
  for (const [title, detail] of rows) {
    const row = el(documentNode, "div", "profile-row");
    row.appendChild(el(documentNode, "b", null, title));
    row.appendChild(el(documentNode, "small", null, detail));
    list.appendChild(row);
  }
  return list;
}

function tokenDetail(token) {
  const parts = [];
  if (token.machine_id) parts.push("machine token");
  if (token.created_at) parts.push(`created ${relativeAgePhrase(token.created_at)}`);
  parts.push(token.last_used_at
    ? `last used ${relativeAgePhrase(token.last_used_at)}` : "never used");
  return parts.join(" · ");
}

// Revoke asks once, inline, so a slip of the hand does not end a token.
function revokeControl(context, token, redraw) {
  const documentNode = context.document;
  const host = el(documentNode, "span", "profile-row-action");
  const arm = el(documentNode, "button", "item-button", "Revoke…");
  arm.type = "button";
  arm.addEventListener("click", () => {
    const confirm = el(documentNode, "button", "item-button danger", "Revoke");
    confirm.type = "button";
    const keep = el(documentNode, "button", "item-button", "Keep");
    keep.type = "button";
    keep.addEventListener("click", () => host.replaceChildren(arm));
    confirm.addEventListener("click", async () => {
      confirm.disabled = true;
      const result = await callFunction(
        context.client, "profile.token.revoke", { token_id: token.token_id },
      ).catch(() => READ_FAILED);
      if (!context.isMounted()) return;
      if (result.status === 200 && result.envelope.success) redraw();
      else host.replaceChildren(el(
        documentNode, "span", "error",
        (result.envelope.error || {}).message || "revoke failed",
      ));
    });
    host.replaceChildren(confirm, keep);
  });
  host.appendChild(arm);
  return host;
}

function tokenRow(context, token, redraw) {
  const documentNode = context.document;
  const row = el(documentNode, "div", "profile-row");
  const main = el(documentNode, "div", "profile-row-main");
  main.appendChild(el(documentNode, "b", null, token.name));
  main.appendChild(el(documentNode, "small", null, tokenDetail(token)));
  row.appendChild(main);
  if (token.machine_id) {
    const link = el(documentNode, "a", "profile-row-action", "Machine →");
    link.href = buildUniverseRoute("machines", null, token.machine_id);
    row.appendChild(link);
  } else {
    row.appendChild(revokeControl(context, token, redraw));
  }
  return row;
}

// A new token's raw value is shown exactly once, because the engine keeps
// only its hash: the row that replaces this notice will never show it again.
function newTokenForm(context, body, redraw) {
  const documentNode = context.document;
  const form = el(documentNode, "form", "profile-new-token");
  const name = el(documentNode, "input");
  name.type = "text";
  name.placeholder = "Token name";
  name.required = true;
  name.maxLength = 80;
  const create = el(documentNode, "button", "item-button primary", "New token");
  create.type = "submit";
  form.appendChild(name);
  form.appendChild(create);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const value = String(name.value || "").trim();
    if (!value) return;
    create.disabled = true;
    const result = await callFunction(
      context.client, "profile.token.create", { name: value },
    ).catch(() => READ_FAILED);
    if (!context.isMounted()) return;
    if (!(result.status === 200 && result.envelope.success)) {
      create.disabled = false;
      renderError(body, result);
      return;
    }
    const notice = el(documentNode, "div", "profile-token-reveal");
    notice.appendChild(el(
      documentNode, "p", null,
      `Copy ${value} now. It is shown once and never again.`,
    ));
    notice.appendChild(el(
      documentNode, "code", "profile-token-value", result.envelope.result.raw_token,
    ));
    const done = el(documentNode, "button", "item-button", "Done");
    done.type = "button";
    done.addEventListener("click", redraw);
    notice.appendChild(done);
    body.replaceChildren(notice);
  });
  return form;
}

function tokensCard(context, body, profile, redraw) {
  const documentNode = context.document;
  body.replaceChildren();
  if (!profile.tokens.length) {
    body.appendChild(el(documentNode, "p", "muted", "No tokens yet."));
  } else {
    const list = el(documentNode, "div", "profile-list");
    for (const token of profile.tokens) {
      list.appendChild(tokenRow(context, token, redraw));
    }
    body.appendChild(list);
  }
  body.appendChild(newTokenForm(context, body, redraw));
}

function timeZoneOptions(current) {
  const zones = typeof Intl.supportedValuesOf === "function"
    ? Intl.supportedValuesOf("timeZone") : [];
  if (current && !zones.includes(current)) zones.unshift(current);
  return zones;
}

function preferencesCard(context, profile) {
  const documentNode = context.document;
  const current = profile.preferences.time_zone || "";
  const select = el(documentNode, "select", "profile-time-zone");
  const automatic = el(documentNode, "option", null, "Automatic");
  automatic.value = "";
  select.appendChild(automatic);
  for (const zone of timeZoneOptions(current)) {
    const option = el(documentNode, "option", null, zone);
    option.value = zone;
    if (zone === current) option.selected = true;
    select.appendChild(option);
  }
  const status = el(documentNode, "small", "profile-save-status");
  select.addEventListener("change", async () => {
    const value = select.value;
    status.textContent = "saving…";
    const result = await callFunction(
      context.client, "profile.preference.set",
      { key: "profile.time_zone", value },
    ).catch(() => READ_FAILED);
    if (!context.isMounted()) return;
    if (result.status === 200 && result.envelope.success) {
      setDisplayTimeZone(value);
      status.textContent = "saved";
    } else {
      status.textContent = (result.envelope.error || {}).message
        || "could not save";
    }
  });
  const wrap = el(documentNode, "div", "profile-time-zone-row");
  wrap.appendChild(select);
  wrap.appendChild(status);
  return keyValueRows(documentNode, [["Time zone", wrap]]);
}

function resetCard(context, body, profile) {
  const documentNode = context.document;
  const hidden = profile.onboarding.hidden_count;
  const draw = (count) => {
    body.replaceChildren();
    body.appendChild(el(
      documentNode, "p", null,
      "Show every onboarding module on Overview again"
        + (count ? ` (${count} hidden now)` : "")
        + ". Modules you already completed stay completed.",
    ));
    const reset = el(documentNode, "button", "item-button", "Reset");
    reset.type = "button";
    reset.disabled = !count;
    reset.addEventListener("click", async () => {
      reset.disabled = true;
      const result = await callFunction(
        context.client, "profile.onboarding.reset", {},
      ).catch(() => READ_FAILED);
      if (!context.isMounted()) return;
      if (result.status === 200 && result.envelope.success) draw(0);
      else renderError(body, result);
    });
    body.appendChild(reset);
  };
  draw(hidden);
}

export function renderProfileView(context, main, scope, chrome) {
  const documentNode = context.document;
  if (chrome && typeof chrome.setPageHead === "function") {
    chrome.setPageHead({ title: "Profile" });
  }
  const who = section(documentNode, "Who you are");
  const roles = section(documentNode, "What you can do");
  const tokens = section(documentNode, "API tokens");
  const preferences = section(documentNode, "Preferences");
  const reset = section(documentNode, "Reset onboarding modules");
  const grid = el(documentNode, "div", "profile-grid");
  for (const panel of [who, roles, tokens, preferences, reset]) {
    grid.appendChild(panel);
  }
  main.replaceChildren(grid);

  const load = async () => {
    const result = await callFunction(context.client, "profile.get", {})
      .catch((error) => ({
        status: 0,
        envelope: { success: false, error: { message: String(error) } },
      }));
    if (!context.isMounted()) return;
    const ok = result.status === 200 && result.envelope.success;
    if (!ok) {
      for (const panel of [who, roles, tokens, preferences, reset]) {
        panel.renderEnvelope(result, renderError);
      }
      return;
    }
    const profile = result.envelope.result;
    setDisplayTimeZone(profile.preferences.time_zone || "");
    who.renderEnvelope(result, (body) => body.appendChild(
      whoCard(documentNode, profile),
    ));
    roles.renderEnvelope(result, (body) => body.appendChild(
      rolesCard(documentNode, profile),
    ));
    tokens.renderEnvelope(result, (body) => tokensCard(
      context, body, profile, load,
    ));
    preferences.renderEnvelope(result, (body) => body.appendChild(
      preferencesCard(context, profile),
    ));
    reset.renderEnvelope(result, (body) => resetCard(context, body, profile));
  };
  return load();
}
