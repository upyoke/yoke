'use strict';

/**
 * The keys a browser case step may carry, by action.
 *
 * Must match yoke_contracts.browser_qa_contract (SHARED_STEP_KEYS and
 * ACTION_STEP_KEYS). A key that is accepted and then ignored is how a
 * correct-looking case tests the wrong thing.
 */

const SHARED_STEP_KEYS = Object.freeze([
  'action',
  'timeout_ms',
  'source_ac',
  'refined',
  'viewport',
]);

const ACTION_STEP_KEYS = Object.freeze({
  navigate: Object.freeze(['route']),
  click: Object.freeze(['target']),
  type: Object.freeze(['target', 'value', 'delay']),
  fill_form: Object.freeze(['fields']),
  assert: Object.freeze(['target', 'check', 'expected', 'min_count']),
  screenshot: Object.freeze(['capture', 'fullPage']),
  wait_for: Object.freeze(['target']),
  delay: Object.freeze(['duration', 'duration_ms']),
  scroll: Object.freeze(['target', 'x', 'y']),
  hover: Object.freeze(['target']),
  select: Object.freeze(['target', 'value']),
});

function definedKeysForAction(action) {
  const extra = ACTION_STEP_KEYS[action];
  if (!extra) {
    return SHARED_STEP_KEYS.slice();
  }
  return SHARED_STEP_KEYS.concat(extra);
}

function unrecognizedStepKeys(step) {
  const action = step && step.action;
  if (!Object.prototype.hasOwnProperty.call(ACTION_STEP_KEYS, action)) {
    return [];
  }
  const allowed = new Set(definedKeysForAction(action));
  return Object.keys(step).filter((key) => !allowed.has(key)).sort();
}

function refuseUnrecognizedStepKeys(step) {
  const unknown = unrecognizedStepKeys(step);
  if (unknown.length === 0) {
    return;
  }
  const defined = definedKeysForAction(step.action).slice().sort();
  const labelled = unknown.map((key) => JSON.stringify(key)).join(', ');
  const noun = unknown.length === 1 ? 'key' : 'keys';
  throw new Error(
    `Browser ${step.action} step does not honour ${noun} ${labelled}. `
    + `Defined keys: ${defined.join(', ')}`
  );
}

function refuseNavigateWithoutRoute(step) {
  if (!step || step.action !== 'navigate') {
    return;
  }
  if (typeof step.route === 'string' && step.route.trim()) {
    return;
  }
  const defined = definedKeysForAction('navigate').slice().sort();
  throw new Error(
    'Browser navigate step requires a non-empty route. '
    + `Defined keys: ${defined.join(', ')}`
  );
}

module.exports = {
  ACTION_STEP_KEYS,
  SHARED_STEP_KEYS,
  definedKeysForAction,
  refuseNavigateWithoutRoute,
  refuseUnrecognizedStepKeys,
  unrecognizedStepKeys,
};
