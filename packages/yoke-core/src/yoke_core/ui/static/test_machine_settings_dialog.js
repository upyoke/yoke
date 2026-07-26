import {
  callFunction,
  el,
  renderError,
  statePill,
} from "./universe_view_support.js";

export const machineSecretNotes = {
  ssh_private_key: "executor subprocess only",
  sudo_password: "used only by registered host-baseline operations",
  screen_control_token: "Terminal automation bridge",
};

export function machineSettingsDialog(context, detail, close, saved) {
  const documentNode = context.document;
  const overlay = el(documentNode, "div", "test-machine-overlay");
  const dialog = el(documentNode, "section", "test-machine-dialog");
  overlay.addEventListener("click", close);
  dialog.addEventListener("click", (event) => event.stopPropagation());
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.setAttribute("aria-label", "Edit Test Mac settings");
  dialog.appendChild(el(documentNode, "h2", null, "Edit Test Mac"));
  dialog.appendChild(el(
    documentNode,
    "p",
    "muted",
    "Only non-secret project capability settings are saved here. Secret values never enter the browser.",
  ));
  const fields = el(documentNode, "div", "test-machine-fields");
  const inputs = {};
  for (const [key, label] of [
    ["resource_name", "Resource name"],
    ["host", "Host"],
    ["user", "User"],
    ["operating_notes", "Operating notes"],
  ]) {
    const wrapper = el(documentNode, "label", null, label);
    const input = el(documentNode, "input");
    input.value = detail.settings[key] || "";
    wrapper.appendChild(input);
    fields.appendChild(wrapper);
    inputs[key] = input;
  }
  dialog.appendChild(fields);
  const credentials = el(documentNode, "div", "test-machine-dialog-secrets");
  credentials.appendChild(el(documentNode, "h3", null, "Credential references"));
  credentials.appendChild(el(
    documentNode,
    "p",
    "muted",
    "Presence is visible here; replacement happens through the registered terminal surface with --value-stdin, so raw values never render or enter browser history.",
  ));
  for (const secret of detail.secrets || []) {
    const row = el(documentNode, "div", "test-machine-command");
    row.appendChild(el(documentNode, "strong", null, secret.key));
    const state = statePill(
      documentNode, secret.stored ? "stored" : "missing",
    );
    if (state) row.appendChild(state);
    row.appendChild(el(
      documentNode,
      "small",
      null,
      machineSecretNotes[secret.key] || "executor-only credential",
    ));
    row.appendChild(el(
      documentNode,
      "code",
      null,
      `yoke projects capability secret set --project ${detail.project} --cap-type test-machine --key ${secret.key} --value-stdin`,
    ));
    credentials.appendChild(row);
  }
  dialog.appendChild(credentials);
  dialog.appendChild(el(
    documentNode,
    "p",
    "muted",
    "Host baselines stay read-only here: fresh-host and shell-preconfigured are registered executor operations, not user-authored instructions.",
  ));
  const actions = el(documentNode, "div", "test-machine-dialog-actions");
  const cancel = el(documentNode, "button", "btn", "Cancel");
  cancel.type = "button";
  cancel.addEventListener("click", close);
  actions.appendChild(cancel);
  const save = el(documentNode, "button", "btn primary", "Save non-secret settings");
  save.type = "button";
  save.addEventListener("click", async () => {
    save.disabled = true;
    const result = await callFunction(
      context.client,
      "test_machine.settings_replace",
      {
        project: detail.project,
        settings: Object.fromEntries(
          Object.entries(inputs).map(([key, input]) => [key, input.value]),
        ),
        base_settings: detail.settings_token,
      },
    );
    if (!result.envelope.success) {
      save.disabled = false;
      renderError(dialog, result);
      return;
    }
    saved();
  });
  actions.appendChild(save);
  dialog.appendChild(actions);
  overlay.appendChild(dialog);
  return overlay;
}
