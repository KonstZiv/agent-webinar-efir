// generate_lead, the cookie webinar_lead and the GA client id of the form, in consent.js
// (docs/requirements.md, section 9; docs/contract.md, sections 5 and 10). Run by `node --test`
// from tests/registration/test_lead.py. Ported from v1 (tests/js/consent.test.cjs).
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const consent = require("../../../src/app/adapters/web/static/js/consent.js");

const MEASUREMENT_ID = "G-TEST";
const LEAD_COOKIE =
  "webinar_lead=1; Domain=.pythoncourse.me; Path=/; Max-Age=31536000; Secure; SameSite=Lax";

function fakeDom(hostname = "www.example.com", cookies = "") {
  const appended = [];
  const cookieWrites = [];
  const doc = {
    head: { appendChild: (element) => appended.push(element) },
    createElement: (tag) => ({ tagName: tag.toUpperCase() }),
    get cookie() {
      return cookies;
    },
    set cookie(value) {
      cookieWrites.push(value);
    },
  };
  const win = { location: { hostname } };
  return { win, doc, appended, cookieWrites };
}

function calls(win) {
  return (win.dataLayer || []).map((entry) => Array.from(entry));
}

function withPage(dom, { lead = false, inputs = [] } = {}) {
  const marker = { dataset: {} };
  dom.doc.querySelector = (selector) => (selector === "[data-lead]" && lead ? marker : null);
  dom.doc.querySelectorAll = (selector) => (selector === 'input[name="ga_client_id"]' ? inputs : []);
  return dom;
}

function idleAnalytics(dom) {
  return consent.createAnalytics({ win: dom.win, doc: dom.doc, measurementId: MEASUREMENT_ID });
}

function loadedAnalytics(dom) {
  const analytics = idleAnalytics(dom);
  analytics.load();
  return analytics;
}

function leadEvents(win) {
  return calls(win).filter((entry) => entry[0] === "event" && entry[1] === "generate_lead");
}

test("the success screen sends generate_lead; the browser is marked once gtag has sent it", () => {
  const dom = withPage(fakeDom(), { lead: true });
  const analytics = loadedAnalytics(dom);

  assert.equal(consent.reportLead({ doc: dom.doc, analytics }), true);

  const events = leadEvents(dom.win);
  assert.equal(events.length, 1);
  assert.equal(typeof events[0][2].event_callback, "function");
  // A blocked gtag.js never calls back, so the browser stays unmarked.
  assert.deepEqual(dom.cookieWrites, []);
  events[0][2].event_callback();
  events[0][2].event_callback();
  assert.deepEqual(dom.cookieWrites, [LEAD_COOKIE]);
});

test("one success screen sends the event once, even before gtag calls back", () => {
  const dom = withPage(fakeDom(), { lead: true });
  const analytics = loadedAnalytics(dom);

  consent.reportLead({ doc: dom.doc, analytics });
  assert.equal(consent.reportLead({ doc: dom.doc, analytics }), false);

  assert.equal(leadEvents(dom.win).length, 1);
});

test("a browser that already sent the lead, here or on v1, sends nothing", () => {
  const dom = withPage(fakeDom(undefined, "_ga=GA1.1.1; webinar_lead=1"), { lead: true });
  const analytics = loadedAnalytics(dom);

  assert.equal(consent.reportLead({ doc: dom.doc, analytics }), false);

  assert.deepEqual(leadEvents(dom.win), []);
  assert.deepEqual(dom.cookieWrites, []);
});

test("no lead without loaded analytics, after rejection, or without the success screen", () => {
  const notLoaded = withPage(fakeDom(), { lead: true });
  assert.equal(consent.reportLead({ doc: notLoaded.doc, analytics: idleAnalytics(notLoaded) }), false);
  assert.deepEqual(notLoaded.win.dataLayer, undefined);

  const rejected = withPage(fakeDom(), { lead: true });
  const analytics = loadedAnalytics(rejected);
  analytics.deny();
  assert.equal(consent.reportLead({ doc: rejected.doc, analytics }), false);
  assert.deepEqual(leadEvents(rejected.win), []);

  const pageView = withPage(fakeDom(), { lead: false });
  assert.equal(consent.reportLead({ doc: pageView.doc, analytics: loadedAnalytics(pageView) }), false);
  assert.deepEqual(leadEvents(pageView.win), []);
  assert.deepEqual(pageView.cookieWrites, []);
});

test("no lead without a measurement id", () => {
  const dom = withPage(fakeDom(), { lead: true });
  const analytics = consent.createAnalytics({ win: dom.win, doc: dom.doc, measurementId: "" });
  analytics.load();

  assert.equal(consent.reportLead({ doc: dom.doc, analytics }), false);
  assert.deepEqual(dom.cookieWrites, []);
});

test("allowing analytics on the success screen sends the lead", () => {
  // An EEA visitor may register first and click «Дозволити» afterwards.
  const dom = withPage(fakeDom(), { lead: true });
  const analytics = idleAnalytics(dom);
  assert.equal(consent.reportLead({ doc: dom.doc, analytics }), false);

  consent.grant({ doc: dom.doc, analytics });

  assert.equal(leadEvents(dom.win).length, 1);
});

test("other cookies with a similar name do not count as the lead mark", () => {
  assert.equal(consent.hasLeadCookie("webinar_lead=1"), true);
  assert.equal(consent.hasLeadCookie("a=1; webinar_lead=1; b=2"), true);
  assert.equal(consent.hasLeadCookie("old_webinar_lead=1; webinar_leads=1"), false);
  assert.equal(consent.hasLeadCookie(""), false);
});

test("the form gets the GA client id only while analytics is active", () => {
  const input = { value: "" };
  const active = withPage(fakeDom(), { inputs: [input] });
  consent.syncClientId({ doc: active.doc, analytics: loadedAnalytics(active) });

  const request = calls(active.win).find((entry) => entry[0] === "get");
  assert.deepEqual(request.slice(0, 3), ["get", MEASUREMENT_ID, "client_id"]);
  request[3]("123456789.1234567890");
  assert.equal(input.value, "123456789.1234567890");

  const untouched = { value: "" };
  const idle = withPage(fakeDom(), { inputs: [untouched] });
  consent.syncClientId({ doc: idle.doc, analytics: idleAnalytics(idle) });
  assert.equal(idle.win.dataLayer, undefined);
  assert.equal(untouched.value, "");
});

test("rejecting clears the GA client id, also from a late gtag answer", () => {
  const input = { value: "" };
  const dom = withPage(fakeDom(), { inputs: [input] });
  const analytics = loadedAnalytics(dom);
  consent.syncClientId({ doc: dom.doc, analytics });
  const late = calls(dom.win).find((entry) => entry[0] === "get")[3];
  consent.syncClientId({ doc: dom.doc, analytics });
  calls(dom.win).filter((entry) => entry[0] === "get")[1][3]("111.222");
  assert.equal(input.value, "111.222");

  consent.reject({ doc: dom.doc, analytics });
  assert.equal(input.value, "");

  late("333.444");
  assert.equal(input.value, "");
});
