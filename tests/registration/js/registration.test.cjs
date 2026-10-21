// The registration form's script, registration.js, on a stand-in page (docs/requirements.md,
// section 5): it renders the Turnstile widget itself (render=explicit), whichever of the two
// scripts runs first; the button waits for Turnstile, says «Надсилаємо…» while a request is in
// flight and waits for a new token after a failed one. Run by `node --test` from
// tests/registration/test_lead.py. The page, htmx's events and Turnstile are fakes: the script
// only needs the few calls below.
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SCRIPT = fs.readFileSync(
  path.join(__dirname, "../../../src/app/adapters/web/static/js/registration.js"),
  "utf8",
);

function fakePage() {
  const listeners = {};
  const button = {
    disabled: false, // enabled in the HTML: without JavaScript the form is a plain POST
    textContent: "Зареєструватися",
    dataset: { busyLabel: "Надсилаємо…" },
  };
  const widget = {
    dataset: { sitekey: "site-key", language: "uk", theme: "light" },
    querySelector: () => null,
  };
  const networkError = { hidden: true, focus() {} };
  const section = {
    id: "register",
    querySelector(selector) {
      if (selector.startsWith("button[type=submit]")) return button;
      if (selector === "[data-network-error]") return networkError;
      return null;
    },
    querySelectorAll: (selector) => (selector === ".cf-turnstile" ? [widget] : []),
  };
  const document = {
    readyState: "interactive",
    getElementById: (id) => (id === "register" ? section : null),
    addEventListener(type, listener) {
      (listeners[type] = listeners[type] || []).push(listener);
    },
  };
  return {
    window: {},
    document,
    button,
    widget,
    networkError,
    // htmx dispatches its events on the element; they bubble up to the document.
    fire(type, detail = {}) {
      for (const listener of listeners[type] || []) {
        listener({ detail: { target: section, ...detail } });
      }
    },
  };
}

function fakeTurnstile() {
  return {
    rendered: [],
    resets: 0,
    render(element, options) {
      this.rendered.push({ element, options });
      return `widget-${this.rendered.length}`;
    },
    reset() {
      this.resets += 1;
    },
    remove() {},
  };
}

function load(page) {
  vm.runInNewContext(SCRIPT, { window: page.window, document: page.document });
}

// Turnstile hands a token to the callback the widget was rendered with.
function giveToken(page, token) {
  const [rendered] = page.window.turnstile.rendered;
  rendered.options.callback(token);
}

test("the button waits for Turnstile's token", () => {
  const page = fakePage();
  page.window.turnstile = fakeTurnstile();
  load(page);

  assert.equal(page.button.disabled, true);
  giveToken(page, "token-1");
  assert.equal(page.button.disabled, false);
});

test("a request without an answer leaves the button waiting for a new token", () => {
  const page = fakePage();
  const turnstile = fakeTurnstile();
  page.window.turnstile = turnstile;
  load(page);
  giveToken(page, "token-1");

  page.fire("htmx:beforeRequest");
  assert.equal(page.button.textContent, "Надсилаємо…");
  // No network: htmx sends afterRequest first, then sendError.
  page.fire("htmx:afterRequest");
  page.fire("htmx:sendError");

  assert.equal(page.button.textContent, "Зареєструватися");
  assert.equal(page.networkError.hidden, false);
  assert.equal(turnstile.resets, 1); // the spent token is gone
  assert.equal(page.button.disabled, true);
  giveToken(page, "token-2");
  assert.equal(page.button.disabled, false);
});

test("an answer htmx does not swap in also waits for a new token", () => {
  const page = fakePage();
  page.window.turnstile = fakeTurnstile();
  load(page);
  giveToken(page, "token-1");

  page.fire("htmx:beforeRequest");
  page.fire("htmx:responseError"); // e.g. 502 from the proxy
  page.fire("htmx:afterRequest");

  assert.equal(page.button.disabled, true);
});

test("api.js before the form's script: the script renders the widget once it runs", () => {
  const page = fakePage();
  const turnstile = fakeTurnstile();
  page.window.turnstile = turnstile; // api.js ran first: onload had no function to call

  load(page);

  assert.equal(turnstile.rendered.length, 1);
  const [{ element, options }] = turnstile.rendered;
  assert.equal(element, page.widget);
  assert.deepEqual(
    [options.sitekey, options.language, options.theme],
    ["site-key", "uk", "light"],
  );
  assert.equal(page.button.disabled, true);
  giveToken(page, "token-1");
  assert.equal(page.button.disabled, false);
  options["expired-callback"]();
  assert.equal(page.button.disabled, true);
});

test("api.js after the form's script: its onload renders the widget", () => {
  const page = fakePage();
  load(page);
  const turnstile = fakeTurnstile();

  page.window.turnstile = turnstile;
  page.window.registrationTurnstileLoad(); // api.js?onload=registrationTurnstileLoad

  assert.equal(turnstile.rendered.length, 1);
  giveToken(page, "token-1");
  assert.equal(page.button.disabled, false);
});

test("the widget is rendered once, whichever way comes second", () => {
  const page = fakePage();
  const turnstile = fakeTurnstile();
  page.window.turnstile = turnstile;
  load(page);

  page.window.registrationTurnstileLoad();
  page.fire("htmx:afterSettle");

  assert.equal(turnstile.rendered.length, 1);
});
