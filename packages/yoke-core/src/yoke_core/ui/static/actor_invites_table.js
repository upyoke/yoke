// Public invitation history and inline, kind-specific actions.
import { el, labelCellsByColumn } from "./universe_view_support.js";

const COLUMNS = ["Person", "Kind", "Role", "State", "Expires", "Invited by", "Action"];
const STATES = ["pending", "expired", "revoked", "consumed"];
const TONES = { pending: "run", expired: "warn", revoked: "idle", consumed: "good" };
const instant = (value) => typeof value === "string" ? Date.parse(value) : NaN;
// Date keeps milliseconds; native wire timestamps also carry microseconds.
const fraction = (value) => (value.match(/\.(\d+)/)?.[1] || "").padEnd(9, "0");
const newest = (a, b) => instant(b.created_at) - instant(a.created_at)
  || fraction(b.created_at).localeCompare(fraction(a.created_at));
const stateOf = (row) => row.state || (row.status === "accepted" ? "consumed" : row.status);

function actions(context, row, { canManage, onRevoke, onReissue }) {
  const doc = context.document;
  const cell = el(doc, "td");
  const state = stateOf(row);
  const name = row.kind === "email" ? row.email : row.name;
  const buttons = [];
  if (row.kind === "email") cell.title = "Revoke, then invite again to resend.";
  const add = (label, action, callback) => {
    const button = el(doc, "button", "item-button", label);
    button.type = "button";
    button.addEventListener("click", () => {
      let busy = false;
      const copy = action === "Revoke"
        ? `Revoke the invite for ${name}? They won't be able to use it.`
        : `Reissue the invite for ${name}? The old code stops working. Any code shown above will close.`;
      const confirm = el(doc, "button", "item-button primary", `${action} invite`);
      const cancel = el(doc, "button", "item-button", "Cancel");
      confirm.type = cancel.type = "button";
      const error = el(doc, "p", "error");
      error.setAttribute("role", "alert");
      const close = () => { if (!busy) { cell.replaceChildren(...buttons); button.focus(); } };
      cancel.addEventListener("click", close);
      const prompt = el(doc, "div", "actors-confirm-copy", copy);
      prompt.addEventListener("keydown", (event) => {
        if (event.key === "Escape") { event.preventDefault(); close(); }
      });
      confirm.addEventListener("click", async () => {
        if (busy) return;
        busy = true;
        confirm.disabled = cancel.disabled = true;
        error.textContent = "";
        let response;
        try { response = await callback(row); } catch { response = null; }
        if (!context.isMounted() || !cell.contains(prompt)) return;
        if (response?.status === 200 && response.envelope?.success) return;
        const refusal = response?.envelope?.error || {};
        error.textContent = refusal.code === "result_unavailable"
          ? "This invite was already reissued. Its code cannot be shown again. Read the list, then use Reissue for a new code."
          : `${refusal.message || "Invite update failed. Read the list before trying again."} ${refusal.hint || ""}${refusal.code ? ` (${refusal.code})` : ""}`;
        busy = false;
        confirm.disabled = cancel.disabled = false;
      });
      prompt.appendChild(confirm);
      prompt.appendChild(cancel);
      prompt.appendChild(error);
      cell.replaceChildren(prompt);
      confirm.focus();
    });
    buttons.push(button);
  };
  if (canManage && state === "pending") add("Revoke…", "Revoke", onRevoke);
  if (canManage && row.kind === "code" && ["pending", "expired", "revoked"].includes(state)) {
    add("Reissue", "Reissue", onReissue);
  }
  cell.replaceChildren(...(buttons.length ? buttons : [el(doc, "span", "actors-muted", "—")]));
  return cell;
}

export function renderInvitesTable(context, host, rows, options) {
  const { showUsed, roleDescriptions = {} } = options;
  const doc = context.document;
  host.replaceChildren();
  const visible = rows.filter((row) => showUsed || stateOf(row) !== "consumed");
  if (!visible.length) {
    host.appendChild(el(doc, "p", "empty actors-empty", rows.length
      ? "No active invites. Show used to see people who joined." : "No invites yet."));
    return;
  }
  const groups = [...STATES, ...new Set(visible.map(stateOf).filter((state) => !STATES.includes(state)))];
  const ordered = groups.flatMap((state) => {
    const group = visible.filter((row) => stateOf(row) === state);
    return group.every((row) => Number.isFinite(instant(row.created_at)))
      ? group.sort(newest) : group;
  });
  if (visible.some((row) => !Number.isFinite(instant(row.created_at)))) {
    host.appendChild(el(doc, "p", "actors-muted",
      "Creation order is unavailable for some invites. Ask the server operator to upgrade, then reload."));
  }
  const wrap = el(doc, "div", "table-wrap");
  const table = el(doc, "table", "items actors-table table-stacks-narrow");
  table.appendChild(el(doc, "caption", "shell-visually-hidden", "Invites"));
  const head = el(doc, "thead");
  const headings = el(doc, "tr");
  for (const label of COLUMNS) headings.appendChild(el(doc, "th", null, label));
  head.appendChild(headings);
  table.appendChild(head);
  const body = el(doc, "tbody");
  for (const row of ordered) {
    const state = stateOf(row);
    const tr = el(doc, "tr");
    const person = el(doc, "td", "actors-name", row.kind === "email" ? row.email : row.name);
    if (row.kind === "code") person.appendChild(el(doc, "div", "actors-muted", `actor #${row.actor_id}`));
    const role = el(doc, "td");
    if (row.role === undefined) {
      role.appendChild(el(doc, "span", "actors-muted", "Role unavailable. Upgrade the server, then reload."));
    } else if (row.role === null) {
      role.appendChild(el(doc, "span", "actors-muted", "No role grant"));
    } else {
      const chip = el(doc, "span", "actors-role", row.role);
      if (roleDescriptions[row.role]) chip.title = roleDescriptions[row.role];
      role.appendChild(chip);
    }
    const stateCell = el(doc, "td");
    stateCell.appendChild(el(doc, "span", `pill ${TONES[state] || "idle"}`, state === "consumed" ? "joined" : state));
    const expires = el(doc, "td", null, "—");
    if (!["consumed", "revoked"].includes(state) && Number.isFinite(instant(row.expires_at))) {
      const time = el(doc, "time", null, new Date(row.expires_at).toLocaleString());
      time.setAttribute("datetime", row.expires_at);
      expires.replaceChildren(time);
    }
    const inviter = row.invited_by_name || (row.invited_by_name === undefined
      ? "Inviter unavailable. Upgrade the server, then reload." : "Inviter unavailable.");
    for (const cell of [person, el(doc, "td", null, row.kind === "email" ? "Email invite" : "Invite code"),
      role, stateCell, expires, el(doc, "td", null, inviter), actions(context, row, options)]) tr.appendChild(cell);
    labelCellsByColumn(tr, COLUMNS);
    body.appendChild(tr);
  }
  table.appendChild(body);
  wrap.appendChild(table);
  host.appendChild(wrap);
}
