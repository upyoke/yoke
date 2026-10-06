'use strict';

/**
 * Interprets the one declared browser step schema.
 *
 * The declaration is yoke_contracts/browser_step_schema.json. Validation in
 * that package and execution here both refuse a step the schema cannot run.
 * A materialized runtime keeps a copy beside this file; source checkouts and
 * installed wheels read the contracts package.
 */

const fs = require('fs');
const path = require('path');

const SCHEMA_CANDIDATES = [
  path.join(__dirname, 'step-schema.json'),
  path.join(__dirname, '../../../yoke_contracts/browser_step_schema.json'),
  path.join(
    __dirname,
    '../../../../../yoke-contracts/src/yoke_contracts/browser_step_schema.json'
  ),
];

function schemaPath() {
  for (const candidate of SCHEMA_CANDIDATES) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }
  return null;
}

function loadSchema() {
  const location = schemaPath();
  if (!location) {
    throw new Error(
      'browser_step_schema_missing: the declared browser step schema was not '
      + 'found beside the runtime or in yoke_contracts. Tried: '
      + SCHEMA_CANDIDATES.join('; ')
      + '. Reinstall the product, or run `yoke qa browser setup` so the '
      + 'runtime is materialized from the contracts declaration.'
    );
  }
  return JSON.parse(fs.readFileSync(location, 'utf8'));
}

const SCHEMA = loadSchema();

const SHARED_STEP_KEYS = Object.freeze(SCHEMA.shared_keys.slice());
const ACTION_STEP_KEYS = Object.freeze(Object.fromEntries(
  Object.entries(SCHEMA.actions).map(([action, spec]) => [
    action,
    Object.freeze(spec.keys.slice()),
  ])
));

function definedKeysForAction(action) {
  const extra = ACTION_STEP_KEYS[action];
  if (!extra) {
    return SHARED_STEP_KEYS.slice();
  }
  return SHARED_STEP_KEYS.concat(extra);
}

function definedList(action) {
  return definedKeysForAction(action).slice().sort().join(', ');
}

function quote(value) {
  return JSON.stringify(value);
}

function unrecognizedStepKeys(step) {
  const action = step && step.action;
  if (!Object.prototype.hasOwnProperty.call(ACTION_STEP_KEYS, action)) {
    return [];
  }
  const allowed = new Set(definedKeysForAction(action));
  return Object.keys(step).filter((key) => !allowed.has(key)).sort();
}

function nonEmptyText(value) {
  return typeof value === 'string' && value.trim();
}

function refuseField(action, step, field, rule) {
  const present = Object.prototype.hasOwnProperty.call(step, field);
  const value = step[field];
  if (rule.type === 'true') {
    if (value !== true) {
      throw new Error(
        'Browser screenshot step requires capture=true so it records an '
        + 'artifact. Set "capture" to true, or remove the screenshot step.'
      );
    }
    return;
  }
  if (rule.type === 'object') {
    if (value === null || typeof value !== 'object' || Array.isArray(value)) {
      throw new Error(`Browser ${action} step requires a ${field} object.`);
    }
    return;
  }
  if (rule.type !== 'non_empty_string') {
    return;
  }
  if (value !== null && typeof value === 'object') {
    throw new Error(
      `Browser ${action} step field ${quote(field)} must be a non-empty `
      + 'string, not an object.'
    );
  }
  if ((rule.required || present) && !nonEmptyText(value)) {
    throw new Error(`Browser ${action} step requires a non-empty ${field}.`);
  }
}

function refuseStep(step) {
  if (!step || typeof step !== 'object' || Array.isArray(step)) {
    throw new Error('Browser step must be an object with an action field');
  }
  const action = step.action;
  if (typeof action !== 'string' || !action.trim()) {
    throw new Error('Step must have an action field');
  }
  const retired = SCHEMA.retired_actions && SCHEMA.retired_actions[action];
  if (retired) {
    throw new Error(
      `Browser step action ${quote(action)} is not executable; use ${retired}.`
    );
  }
  const spec = SCHEMA.actions[action];
  if (!spec) {
    const actions = Object.keys(SCHEMA.actions).sort().join(', ');
    throw new Error(
      `Unknown action: ${quote(action)}. Defined actions: ${actions}`
    );
  }
  const aliases = SCHEMA.aliases || {};
  const aliasHits = Object.keys(step).filter((key) => aliases[key]).sort();
  if (aliasHits.length) {
    const key = aliasHits[0];
    throw new Error(
      `Browser ${action} step does not honour key ${quote(key)}; `
      + `use ${quote(aliases[key])}. Defined keys: ${definedList(action)}`
    );
  }
  const reject = spec.reject_keys || {};
  const rejected = Object.keys(step).filter((key) => reject[key]).sort();
  if (rejected.length) {
    const key = rejected[0];
    throw new Error(
      `Browser ${action} step does not honour key ${quote(key)}; `
      + `use ${quote(reject[key])}. Defined keys: ${definedList(action)}`
    );
  }
  const unknown = unrecognizedStepKeys(step);
  if (unknown.length) {
    const labelled = unknown.map(quote).join(', ');
    const noun = unknown.length === 1 ? 'key' : 'keys';
    throw new Error(
      `Browser ${action} step does not honour ${noun} ${labelled}. `
      + `Defined keys: ${definedList(action)}`
    );
  }
  const fields = spec.fields || {};
  for (const [field, rule] of Object.entries(fields)) {
    refuseField(action, step, field, rule);
  }
  const requireAny = spec.require_any;
  if (requireAny && !requireAny.fields.some((field) => nonEmptyText(step[field]))) {
    throw new Error(`Browser ${action} step ${requireAny.refusal}`);
  }
}

module.exports = {
  ACTION_STEP_KEYS,
  SHARED_STEP_KEYS,
  definedKeysForAction,
  refuseStep,
  unrecognizedStepKeys,
};
