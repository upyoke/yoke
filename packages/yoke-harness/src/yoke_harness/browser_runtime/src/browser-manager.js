'use strict';

/**
 * Browser manager -- wraps a single Playwright browser context.
 *
 * With a profile directory the context is persistent: it opens the operator's
 * signed-in Chromium profile for one project, so every page handed out is
 * signed into whatever the operator signed into. Without one the context is a
 * throwaway with an empty cookie jar.
 *
 * Exports: createBrowserManager(options) -> { launch, getBrowser, getPage, newPage, closeBrowser, isConnected, getProfileDir }
 */

const { chromium } = require('playwright');

/**
 * @param {Object} options
 * @param {string} [options.browserType='chromium'] - Browser type (only chromium supported today)
 * @param {boolean} [options.headless=true] - Run headless
 * @param {string} [options.profileDir] - Persistent profile directory, or empty for a throwaway context
 * @returns {Object} Browser manager interface
 */
function createBrowserManager(options = {}) {
  const browserType = options.browserType || 'chromium';
  const headless = options.headless !== false;
  const profileDir = options.profileDir || '';

  let browser = null;
  let context = null;
  let currentPage = null;

  async function launch() {
    if (browserType !== 'chromium') {
      throw new Error(`Unsupported browser type: ${browserType}. Only chromium is supported.`);
    }
    if (profileDir) {
      // A persistent context owns its own browser process; Playwright returns
      // no Browser handle for it, so `context` is the lifecycle authority.
      context = await chromium.launchPersistentContext(profileDir, { headless });
      return context;
    }
    browser = await chromium.launch({ headless });
    context = await browser.newContext();
    return browser;
  }

  function getBrowser() {
    return browser;
  }

  function getProfileDir() {
    return profileDir;
  }

  /**
   * Get the current page, creating one if needed. Navigates to url if provided.
   */
  async function getPage(url) {
    if (!context) {
      throw new Error('Browser not launched. Call launch() first.');
    }
    if (!currentPage || currentPage.isClosed()) {
      currentPage = context.pages().find((page) => !page.isClosed()) || (await context.newPage());
    }
    if (url) {
      await currentPage.goto(url, { waitUntil: 'domcontentloaded' });
    }
    return currentPage;
  }

  /**
   * Always create a new page. Navigates to url if provided.
   */
  async function newPage(url) {
    if (!context) {
      throw new Error('Browser not launched. Call launch() first.');
    }
    currentPage = await context.newPage();
    if (url) {
      await currentPage.goto(url, { waitUntil: 'domcontentloaded' });
    }
    return currentPage;
  }

  async function closeBrowser() {
    const closable = browser || context;
    if (closable) {
      try {
        await closable.close();
      } catch (_) {
        // Browser may already be disconnected
      }
      browser = null;
      context = null;
      currentPage = null;
    }
  }

  function isConnected() {
    if (browser) {
      return browser.isConnected();
    }
    return context !== null;
  }

  return {
    launch,
    getBrowser,
    getProfileDir,
    getPage,
    newPage,
    closeBrowser,
    isConnected,
  };
}

module.exports = { createBrowserManager };
