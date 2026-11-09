'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { executeAssert } = require('../src/step-actions/assertion');

function fixture(t, values, { readTime = 0, error } = {}) {
  let now = 0;
  const budgets = [];
  const waits = [];
  t.mock.method(Date, 'now', () => now);
  const locator = {
    async textContent({ timeout }) {
      budgets.push(timeout);
      now += readTime;
      if (error) throw error;
      return values.length > 1 ? values.shift() : values[0];
    },
  };
  const page = {
    locator(target) {
      assert.equal(target, '#details');
      return locator;
    },
    async waitForTimeout(ms) {
      waits.push(ms);
      now += ms;
    },
  };
  const run = (check, expected, timeout = 350) => executeAssert(page, {
    target: '#details', check, expected, timeout_ms: timeout,
  }, {}, null);
  return { run, budgets, waits, elapsed: () => now };
}

for (const check of ['text_contains', 'text_equals']) {
  test(`${check} waits through loading and null text`, async t => {
    const f = fixture(t, ['Loading details…', null, ' Ready ']);
    assert.deepEqual(await f.run(check, 'Ready'), { success: true });
    assert.equal(f.budgets.length, 3);
    assert.equal(f.elapsed(), 200);
  });

  test(`${check} returns immediately for matching text`, async t => {
    const f = fixture(t, [' Ready ']);
    assert.deepEqual(await f.run(check, 'Ready'), { success: true });
    assert.deepEqual(f.waits, []);
  });

  test(`${check} reports last text when the budget expires`, async t => {
    const f = fixture(t, ['Loading', 'Still loading']);
    await assert.rejects(f.run(check, 'Ready', 250), /got "Still loading"/);
    assert.deepEqual(f.budgets, [250, 150, 50]);
    assert.deepEqual(f.waits, [100, 100, 50]);
    assert.equal(f.elapsed(), 250);
  });

  test(`${check} includes attachment time in its budget`, async t => {
    const f = fixture(t, ['Loading'], { readTime: 125 });
    await assert.rejects(f.run(check, 'Ready', 200), /got "Loading"/);
    assert.deepEqual(f.budgets, [200]);
    assert.deepEqual(f.waits, [75]);
    assert.equal(f.elapsed(), 200);
  });

  test(`${check} propagates strict-mode errors without retrying`, async t => {
    const error = new Error('strict mode violation: resolved to 2 elements');
    const f = fixture(t, [], { error });
    await assert.rejects(f.run(check, 'Ready'), actual => actual === error);
    assert.equal(f.budgets.length, 1);
    assert.deepEqual(f.waits, []);
  });
}

test('text_contains preserves case-insensitive substring matching', async t => {
  const f = fixture(t, ['Details are READY now']);
  assert.deepEqual(await f.run('text_contains', 'ready'), { success: true });
});

test('text_equals remains case-sensitive and requires the whole trimmed text', async t => {
  const f = fixture(t, ['ready', 'Ready now', ' Ready ']);
  assert.deepEqual(await f.run('text_equals', 'Ready'), { success: true });
  assert.equal(f.budgets.length, 3);
});

test('null text cannot satisfy an empty expected string', async t => {
  const f = fixture(t, [null]);
  await assert.rejects(f.run('text_contains', '', 100), /Expected text to contain/);
});
