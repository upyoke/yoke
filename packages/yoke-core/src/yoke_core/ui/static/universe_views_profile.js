// Profile: the signed-in person's own page, reached from the actor menu.
// One profile.get read feeds a single readable column of sections — the
// account (identity and roles), API tokens, and settings — the way account
// pages conventionally read. A host's own Profile section (organizations and
// sign-out on a hosted universe) lands below them in the same column. Each
// section draws its own failure so a refused read names itself instead of
// blanking the page.

import { setDisplayTimeZone } from "./universe_time.js";
import {
  callFunction, el, renderError, section,
} from "./universe_view_support.js";
import {
  newTokenAction, renderTokens, withdrawTokenAction,
} from "./universe_views_profile_tokens.js";

const READ_FAILED = { status: 0, envelope: { success: false, error: {} } };

function rolesList(documentNode, profile) {
  const rows = [
    ...profile.roles.org.map((row) => [row.org, `${row.role} · organization`]),
    ...profile.roles.projects.map((row) => [
      row.name || row.project, `${row.role} on ${row.project}`,
    ]),
  ];
  if (!rows.length) return "No roles yet.";
  const list = el(documentNode, "ul", "profile-roles");
  for (const [title, detail] of rows) {
    const row = el(documentNode, "li");
    row.appendChild(el(documentNode, "b", null, title));
    row.appendChild(el(documentNode, "small", null, detail));
    list.appendChild(row);
  }
  return list;
}

function accountFacts(documentNode, profile) {
  const identity = profile.identity || {};
  const list = el(documentNode, "dl", "profile-facts");
  for (const [label, value] of [
    ["Name", profile.actor.name],
    ["Email", identity.email],
    ["Signed in with", identity.signed_in_with],
    ["Actor id", el(documentNode, "code", null, `#${profile.actor.id}`)],
    ["Roles", rolesList(documentNode, profile)],
  ]) {
    if (value === null || value === undefined || value === "") continue;
    list.appendChild(el(documentNode, "dt", null, label));
    const dd = el(documentNode, "dd");
    if (typeof value === "string") dd.textContent = value;
    else dd.appendChild(value);
    list.appendChild(dd);
  }
  return list;
}

// One settings row: what the control is on the left, the control on the
// right; the row wraps under itself on a narrow screen.
function settingRow(documentNode, title, detail, controls) {
  const row = el(documentNode, "div", "profile-setting");
  const label = el(documentNode, "div", "profile-setting-label");
  label.appendChild(el(documentNode, "b", null, title));
  if (detail) label.appendChild(el(documentNode, "small", null, detail));
  const control = el(documentNode, "div", "profile-setting-control");
  for (const node of controls) control.appendChild(node);
  row.appendChild(label);
  row.appendChild(control);
  return row;
}

function timeZoneOptions(current) {
  const zones = typeof Intl.supportedValuesOf === "function"
    ? Intl.supportedValuesOf("timeZone") : [];
  if (current && !zones.includes(current)) zones.unshift(current);
  return zones;
}

function timeZoneSetting(context, profile) {
  const documentNode = context.document;
  const current = profile.preferences.time_zone || "";
  const select = el(documentNode, "select", "profile-time-zone");
  select.setAttribute("aria-label", "Time zone");
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
  status.setAttribute("role", "status");
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
  return settingRow(documentNode, "Time zone", null, [select, status]);
}

function onboardingSetting(context, profile) {
  const documentNode = context.document;
  const host = el(documentNode, "div");
  const draw = (count) => {
    const reset = el(documentNode, "button", "item-button", "Reset");
    reset.type = "button";
    reset.disabled = !count;
    const error = el(documentNode, "div");
    reset.addEventListener("click", async () => {
      reset.disabled = true;
      const result = await callFunction(
        context.client, "profile.onboarding.reset", {},
      ).catch(() => READ_FAILED);
      if (!context.isMounted()) return;
      if (result.status === 200 && result.envelope.success) draw(0);
      else { reset.disabled = false; error.replaceChildren(); renderError(error, result); }
    });
    host.replaceChildren(settingRow(
      documentNode, "Onboarding modules",
      "Show every onboarding module on Overview again"
        + (count ? ` (${count} hidden now)` : "")
        + ". Modules you already completed stay completed.",
      [reset],
    ), error);
  };
  draw(profile.onboarding.hidden_count);
  return host;
}

export function renderProfileView(context, main, scope, chrome) {
  const documentNode = context.document;
  if (chrome && typeof chrome.setPageHead === "function") {
    chrome.setPageHead({ title: "Profile" });
  }
  main.classList.add("profile-view");
  const account = section(documentNode, "Account");
  const tokens = section(documentNode, "API tokens");
  const settings = section(documentNode, "Settings");
  const newToken = newTokenAction(documentNode, tokens);
  const panels = [account, tokens, settings];
  main.replaceChildren(...panels);

  const load = async () => {
    const result = await callFunction(context.client, "profile.get", {})
      .catch((error) => ({
        status: 0,
        envelope: { success: false, error: { message: String(error) } },
      }));
    if (!context.isMounted()) return;
    const ok = result.status === 200 && result.envelope.success;
    if (!ok) {
      withdrawTokenAction(newToken);
      for (const panel of panels) panel.renderEnvelope(result, renderError);
      return;
    }
    const profile = result.envelope.result;
    setDisplayTimeZone(profile.preferences.time_zone || "");
    account.renderEnvelope(result, (body) => body.appendChild(
      accountFacts(documentNode, profile),
    ));
    tokens.renderEnvelope(result, (body) => renderTokens(
      context, tokens, body, profile, newToken, load,
    ));
    settings.renderEnvelope(result, (body) => {
      body.appendChild(timeZoneSetting(context, profile));
      body.appendChild(onboardingSetting(context, profile));
    });
  };
  return load();
}
