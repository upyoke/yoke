// Profile's API tokens section: one full-width table of every token the
// person holds, personal tokens first and machine tokens grouped after them,
// with token creation behind the section's own "New token" action.

import { buildUniverseRoute } from "./universe_navigation.js";
import { relativeAgePhrase } from "./universe_time.js";
import {
  callFunction, el, labelCellsByColumn, renderError,
} from "./universe_view_support.js";

const READ_FAILED = { status: 0, envelope: { success: false, error: {} } };
const COLUMNS = ["Name", "Kind", "Created", "Last used", ""];

// Revoke asks once, inline, so a slip of the hand does not end a token.
function revokeControl(context, token, redraw) {
  const documentNode = context.document;
  const host = el(documentNode, "span", "profile-token-action");
  const arm = el(documentNode, "button", "item-button", "Revoke…");
  arm.type = "button";
  arm.addEventListener("click", () => {
    const confirm = el(documentNode, "button", "item-button danger", "Revoke");
    confirm.type = "button";
    const keep = el(documentNode, "button", "item-button", "Keep");
    keep.type = "button";
    keep.addEventListener("click", () => { host.replaceChildren(arm); arm.focus(); });
    const error = el(documentNode, "span", "error");
    error.setAttribute("role", "alert");
    confirm.addEventListener("click", async () => {
      if (confirm.disabled) return;
      confirm.disabled = true;
      keep.disabled = true;
      error.textContent = "";
      const result = await callFunction(
        context.client, "profile.token.revoke", { token_id: token.token_id },
      ).catch(() => READ_FAILED);
      if (!context.isMounted()) return;
      if (result.status === 200 && result.envelope.success) redraw();
      else {
        confirm.disabled = false;
        keep.disabled = false;
        error.textContent = (result.envelope.error || {}).message || "Could not revoke. Try again.";
      }
    });
    host.replaceChildren(confirm, keep, error);
    confirm.focus();
  });
  host.appendChild(arm);
  return host;
}

// A machine token is named after its machine; the stored token name is
// only the machine id again, so the machine's own name reads better.
function tokenRow(context, token, redraw) {
  const documentNode = context.document;
  const machine = Boolean(token.machine_id);
  const row = el(documentNode, "tr", machine ? "profile-token-machine" : null);
  row.appendChild(el(
    documentNode, "td", "profile-token-name",
    machine ? (token.machine_name || token.name) : token.name,
  ));
  row.appendChild(el(documentNode, "td", null, machine ? "Machine" : "Personal"));
  row.appendChild(el(
    documentNode, "td", null,
    token.created_at ? relativeAgePhrase(token.created_at) : "—",
  ));
  row.appendChild(el(
    documentNode, "td", null,
    token.last_used_at ? relativeAgePhrase(token.last_used_at) : "never",
  ));
  const action = el(documentNode, "td", "profile-token-actions");
  if (machine) {
    const link = el(documentNode, "a", "profile-token-action", "Machine →");
    link.href = buildUniverseRoute("machines", null, token.machine_id);
    action.appendChild(link);
  } else {
    action.appendChild(revokeControl(context, token, redraw));
  }
  row.appendChild(action);
  return labelCellsByColumn(row, COLUMNS);
}

function tokenTable(context, tokens, redraw) {
  const documentNode = context.document;
  const ordered = [
    ...tokens.filter((token) => !token.machine_id),
    ...tokens.filter((token) => token.machine_id),
  ];
  const table = el(documentNode, "table", "items table-stacks-narrow profile-tokens");
  const head = el(documentNode, "thead");
  const headings = el(documentNode, "tr");
  for (const label of COLUMNS) headings.appendChild(el(documentNode, "th", null, label));
  head.appendChild(headings);
  const body = el(documentNode, "tbody");
  for (const token of ordered) body.appendChild(tokenRow(context, token, redraw));
  table.appendChild(head);
  table.appendChild(body);
  return table;
}

// A new token's raw value is shown exactly once, because the engine keeps
// only its hash: the row that replaces this notice will never show it again.
function newTokenForm(context, slot, close, redraw) {
  const documentNode = context.document;
  const form = el(documentNode, "form", "profile-new-token");
  const name = el(documentNode, "input");
  name.type = "text";
  name.setAttribute("aria-label", "Token name");
  name.required = true;
  name.maxLength = 80;
  const nameField = el(documentNode, "label", "profile-token-name-field");
  nameField.appendChild(el(documentNode, "span", null, "Token name"));
  nameField.appendChild(name);
  const create = el(documentNode, "button", "item-button primary", "Create");
  create.type = "submit";
  const cancel = el(documentNode, "button", "item-button", "Cancel");
  cancel.type = "button";
  cancel.addEventListener("click", close);
  const error = el(documentNode, "div");
  for (const node of [nameField, create, cancel, error]) form.appendChild(node);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const value = String(name.value || "").trim();
    if (!value) return;
    create.disabled = true;
    error.replaceChildren();
    const result = await callFunction(
      context.client, "profile.token.create", { name: value },
    ).catch(() => READ_FAILED);
    if (!context.isMounted()) return;
    if (!(result.status === 200 && result.envelope.success)) {
      create.disabled = false;
      renderError(error, result);
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
    slot.replaceChildren(notice);
  });
  return { form, focus: () => name.focus() };
}

// The section's header carries the "New token" action, so creation sits
// above the list it adds to rather than under a long column of rows.
export function newTokenAction(documentNode, panel) {
  const button = el(documentNode, "button", "item-button primary", "New token");
  button.type = "button";
  button.hidden = true;
  button.addEventListener("click", () => { if (button.open) button.open(); });
  panel.children[0].appendChild(button);
  return button;
}

// A failed read leaves nothing to add a token to, so the action leaves the
// header with the table rather than opening a form into an error.
export function withdrawTokenAction(action) {
  action.hidden = true;
  action.open = null;
}

export function renderTokens(context, panel, body, profile, action, redraw) {
  const documentNode = context.document;
  const slot = el(documentNode, "div", "profile-token-slot");
  const close = () => { slot.replaceChildren(); action.disabled = false; action.focus(); };
  action.hidden = false;
  action.disabled = false;
  action.open = () => {
    const { form, focus } = newTokenForm(context, slot, close, redraw);
    slot.replaceChildren(form);
    action.disabled = true;
    focus();
  };
  body.replaceChildren(slot);
  panel.setCount(profile.tokens.length);
  if (!profile.tokens.length) {
    body.appendChild(el(documentNode, "p", "empty", "No tokens yet."));
    return;
  }
  body.appendChild(tokenTable(context, profile.tokens, redraw));
}
