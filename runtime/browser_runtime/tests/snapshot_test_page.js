'use strict';

const path = require('path');
const { chromium } = require('playwright');

let browser;

async function setup() {
  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  return context;
}

async function teardown() {
  if (browser) await browser.close();
}

function fixtureUrl() {
  const fixturePath = path.join(__dirname, 'fixtures', 'test-page.html');
  return `file://${fixturePath}`;
}

module.exports = { fixtureUrl, setup, teardown };
