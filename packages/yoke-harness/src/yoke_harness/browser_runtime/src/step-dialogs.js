'use strict';

// Dismiss refused dialogs so the browser action can finish and report why it
// failed. Event callbacks retain their errors for the step instead of rejecting
// outside the action's promise.
function observeDialogs(page, declaration) {
  const records = [];
  let pending = Promise.resolve();
  let failure = null;
  const refuse = (reason) => { failure = failure || new Error(reason); };
  const handler = (dialog) => {
    const record = { type: dialog.type(), message: dialog.message() };
    records.push(record);
    const first = records.length === 1;
    pending = pending.then(async () => {
      const answer = declaration && first;
      if (!answer) {
        refuse(
          `browser_dialog_unanswered: ${record.type} ${JSON.stringify(record.message)}. `
          + 'Declare dialog on the click step for exactly one dialog.'
        );
      }
      record.accepted = Boolean(answer && declaration === 'accept');
      try {
        if (record.accepted) {
          await dialog.accept();
        } else {
          await dialog.dismiss();
        }
      } catch (_) {
        refuse(
          `browser_dialog_answer_failed: ${record.type} ${JSON.stringify(record.message)}. `
          + 'Check whether the page closed and inspect its state before retrying.'
        );
      }
    });
  };
  page.on('dialog', handler);
  return {
    records,
    async finish(requireDialog = true) {
      await pending;
      if (failure) throw failure;
      if (requireDialog && declaration && records.length === 0) {
        throw new Error(
          'browser_dialog_missing: the click raised no dialog. Check the target '
          + 'and page state, or remove dialog if this click needs no answer.'
        );
      }
    },
    close() { page.off('dialog', handler); },
  };
}

module.exports = { observeDialogs };
