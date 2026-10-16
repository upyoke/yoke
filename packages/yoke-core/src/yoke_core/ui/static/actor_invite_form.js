// Fact-driven teammate invitations and their one-time, DOM-only code reveal.
import { callFunction, el, labelledField, liveStatus } from "./universe_view_support.js";

function button(doc, label, primary = false) {
  const node = el(doc, "button", `item-button${primary ? " primary" : ""}`, label);
  node.type = "button";
  return node;
}

function refusal(result, name) {
  const error = result.envelope?.error || {};
  if (error.code === "result_unavailable") return `This invite was already created, but its code can't be shown again. Use Reissue on ${name}'s invite below.`;
  const hint = error.code === "invite_email_required" ? "Enter their email address instead. Reload to update the form."
    : error.code === "invite_name_required" ? "This server uses invite codes. Enter their name instead. Reload to update the form."
      : error.hint || "";
  return `${error.message || "Could not create the invite. Check the list below before trying again."}${error.code ? ` (${error.code})` : ""} ${hint}`.trim();
}

export function renderInviteResult(context, slot, result, { onDone }) {
  const doc = context.document;
  const notice = el(doc, "div", "profile-token-reveal");
  const name = result.invite?.name;
  if (result.code) {
    notice.setAttribute("data-invite-code", "true");
    const lead = el(doc, "p");
    lead.appendChild(el(doc, "strong", null, `Invite code for ${name}. It is shown once and never again.`));
    const code = el(doc, "code", "profile-token-value", result.code);
    code.setAttribute("aria-label", `Invite code for ${name}`);
    const expiry = el(doc, "p", null, "Expires ");
    const instant = result.expires_at || result.invite.expires_at;
    const time = el(doc, "time", null, new Date(instant).toLocaleString(undefined, {
      year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short",
    }));
    time.setAttribute("datetime", instant);
    expiry.appendChild(time);
    expiry.appendChild(doc.createTextNode(" (in 24 hours). Works once."));
    const use = el(doc, "p", null, "On their computer they run ");
    const origin = doc.defaultView?.location?.origin || "<server>";
    use.appendChild(el(doc, "code", null, `yoke connect ${origin}`));
    use.appendChild(doc.createTextNode(" and choose Enter invite code."));
    for (const node of [lead, code, expiry,
      el(doc, "p", null, `Send it to ${name} only, through a private channel.`), use,
      el(doc, "p", null, `Lost it? Use Reissue on ${name}'s invite below. Yoke keeps only a hash, so this code can't be shown again.`),
    ]) notice.appendChild(node);
  } else {
    const status = el(doc, "p", null, `Invite sent to ${result.email}. They join when they sign in.`);
    status.setAttribute("role", "status");
    notice.appendChild(status);
  }
  const done = button(doc, "Done");
  done.addEventListener("click", () => {
    // Clear the detached card too: no stale button or node keeps the secret.
    notice.replaceChildren();
    slot.replaceChildren();
    onDone();
  });
  notice.appendChild(done);
  slot.replaceChildren(notice);
  done.focus();
}

export function openInviteForm(context, slot, options) {
  const { fact, roles, roleDescriptions, roster, onCreated, onCancel } = options;
  const doc = context.document;
  const reveal = slot.children[0];
  if (reveal?.getAttribute("data-invite-code") === "true") {
    if (slot.children.length > 1) return;
    const confirm = el(doc, "div", "actors-muted", "Close the invite code? It can't be shown again.");
    const close = button(doc, "Close code", true);
    const keep = button(doc, "Keep");
    const cancel = () => { slot.removeChild(confirm); onCancel(false); };
    close.addEventListener("click", () => {
      reveal.replaceChildren();
      slot.replaceChildren();
      openInviteForm(context, slot, options);
    });
    keep.addEventListener("click", cancel);
    confirm.addEventListener("keydown", (event) => { if (event.key === "Escape") { event.preventDefault(); cancel(); } });
    confirm.appendChild(close);
    confirm.appendChild(keep);
    slot.appendChild(confirm);
    close.focus();
    return;
  }
  const email = fact.invite_form === "email";
  const form = el(doc, "form", "profile-new-token");
  form.noValidate = true;
  const input = el(doc, "input");
  input.type = email ? "email" : "text";
  input.required = true;
  if (!email) input.maxLength = 80;
  const field = labelledField(doc, email ? "Email" : "Name", input, "profile-token-name-field");
  const validation = el(doc, "span", "error");
  validation.id = "invite-person-error";
  validation.setAttribute("role", "alert");
  const duplicate = el(doc, "span", "actors-muted");
  field.appendChild(validation);
  field.appendChild(duplicate);
  const role = el(doc, "select", "item-button");
  for (const value of roles) {
    const option = el(doc, "option", null, value);
    option.value = value;
    role.appendChild(option);
  }
  role.value = roles.includes("operator") ? "operator" : "";
  const roleField = labelledField(doc, "Role", role, "profile-token-name-field");
  const description = el(doc, "span", "actors-muted");
  const describe = () => { description.textContent = `Can: ${roleDescriptions[role.value] || "Choose a person's org role."}`; };
  role.addEventListener("change", describe);
  describe();
  roleField.appendChild(description);
  const create = button(doc, "Create invite", true);
  create.type = "submit";
  const cancel = button(doc, "Cancel");
  let busy = false;
  const close = () => { if (!busy) { slot.replaceChildren(); onCancel(); } };
  cancel.addEventListener("click", close);
  form.addEventListener("keydown", (event) => { if (event.key === "Escape") { event.preventDefault(); close(); } });
  const details = el(doc, "div");
  const method = fact.sign_in_method === "yoke_account" ? "their Yoke account" : "company sign-in";
  details.appendChild(el(doc, "p", "actors-muted", email
    ? `They sign in as themselves with ${method}. No code is needed.`
    : "You'll get a one-time code to send them. It expires in 24 hours."));
  const status = liveStatus(doc, "actors-muted");
  const error = el(doc, "p", "error");
  error.setAttribute("role", "alert");
  details.appendChild(status);
  details.appendChild(error);
  const update = () => {
    validation.textContent = "";
    input.removeAttribute("aria-invalid");
    input.removeAttribute("aria-describedby");
    const name = input.value.trim();
    const exists = !email && name && roster.some((row) => row.kind === "human" && row.name.toLocaleLowerCase() === name.toLocaleLowerCase());
    duplicate.textContent = exists ? `${name} is already on the team. This creates a separate person; it does not add a machine to the existing one.` : "";
    create.textContent = exists ? `Create another ${name}` : "Create invite";
  };
  input.addEventListener("input", update);
  for (const node of [field, roleField, create, cancel, details]) form.appendChild(node);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy) return;
    const value = input.value.trim();
    if (!value || (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) || (!email && value.length > 80)) {
      validation.textContent = email ? "Enter an email address, like ana@example.com." : "Enter the teammate's name (up to 80 characters).";
      input.setAttribute("aria-invalid", "true");
      input.setAttribute("aria-describedby", validation.id);
      input.focus();
      return;
    }
    if (!roles.includes(role.value)) { error.textContent = "Choose a person's org role."; return; }
    busy = true;
    for (const node of [create, cancel, input, role]) node.disabled = true;
    status.hidden = false;
    status.textContent = "Creating invite…";
    error.textContent = "";
    const response = await callFunction(context.client, email ? "identity.invite.create" : "teammate_invites.create", {
      [email ? "email" : "name"]: value, role: role.value,
    }).catch(() => ({ status: 0, envelope: { success: false } }));
    if (!context.isMounted() || !slot.contains(form)) return;
    if (response.status === 200 && response.envelope?.success) {
      onCreated(response.envelope.result);
    } else {
      busy = false;
      for (const node of [create, cancel, input, role]) node.disabled = false;
      status.hidden = true;
      status.textContent = "";
      error.textContent = refusal(response, value);
      onCreated(null);
    }
  });
  slot.replaceChildren(form);
  input.focus();
}
