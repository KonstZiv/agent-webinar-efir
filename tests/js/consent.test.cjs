// Unit tests for the cookie banner logic (static/js/consent.js), run by `node --test`.
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const consent = require("../../src/app/adapters/web/static/js/consent.js");

const GRANTED_DEFAULTS = {
  analytics_storage: "granted",
  ad_storage: "granted",
  ad_user_data: "granted",
  ad_personalization: "denied",
};
const ALL_DENIED = {
  analytics_storage: "denied",
  ad_storage: "denied",
  ad_user_data: "denied",
  ad_personalization: "denied",
};
const MEASUREMENT_ID = "G-TEST";

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

function decide(overrides) {
  return consent.decide({
    timeZone: "Europe/Berlin",
    storedChoice: null,
    search: "",
    measurementId: MEASUREMENT_ID,
    ...overrides,
  });
}

test("EEA, UK and Swiss time zones need the banner", () => {
  for (const zone of [
    "Europe/Berlin",
    "Europe/Zagreb",
    "Europe/Ljubljana",
    "Atlantic/Reykjavik",
    "Europe/Luxembourg",
    "Europe/London",
    "Europe/Zurich",
    "Atlantic/Canary",
    "Asia/Nicosia",
    "Europe/Belgrade",
    "CET",
  ]) {
    assert.equal(consent.isEeaTimeZone(zone), true, zone);
  }
});

test("Ukraine and other regions do not", () => {
  for (const zone of ["Europe/Kiev", "Europe/Kyiv", "America/New_York", "Asia/Tokyo"]) {
    assert.equal(consent.isEeaTimeZone(zone), false, zone);
  }
});

test("an undetermined time zone counts as EEA", () => {
  for (const zone of ["", undefined, null, "UTC", "GMT", "Etc/UTC", "Etc/Unknown", "Etc/GMT+2"]) {
    assert.equal(consent.isEeaTimeZone(zone), true, String(zone));
  }
});

test("a failing Intl gives an empty time zone", () => {
  const broken = {
    DateTimeFormat() {
      throw new Error("no Intl");
    },
  };
  assert.equal(consent.readTimeZone(broken), "");
  assert.equal(consent.readTimeZone(Intl), Intl.DateTimeFormat().resolvedOptions().timeZone);
});

test("EEA without a choice: banner, no analytics", () => {
  assert.deepEqual(decide({ timeZone: "Europe/Berlin" }), {
    showBanner: true,
    loadAnalytics: false,
  });
});

test("outside the EEA without a choice: analytics at once, no banner", () => {
  assert.deepEqual(decide({ timeZone: "Europe/Kiev" }), {
    showBanner: false,
    loadAnalytics: true,
  });
});

test("?cookie_region=eea forces EEA behaviour; there is no way to switch it off", () => {
  const forced = decide({ timeZone: "Europe/Kyiv", search: "?utm_source=x&cookie_region=eea" });
  assert.deepEqual(forced, { showBanner: true, loadAnalytics: false });

  const other = decide({ timeZone: "Europe/Berlin", search: "?cookie_region=other" });
  assert.deepEqual(other, { showBanner: true, loadAnalytics: false });
});

test("a stored choice wins over the region", () => {
  assert.deepEqual(
    decide({ timeZone: "Europe/Berlin", storedChoice: "granted", search: "?cookie_region=eea" }),
    { showBanner: false, loadAnalytics: true },
  );
  assert.deepEqual(decide({ timeZone: "Europe/Kiev", storedChoice: "denied" }), {
    showBanner: false,
    loadAnalytics: false,
  });
});

test("without a measurement id there is nothing to consent to: no banner, no analytics", () => {
  for (const measurementId of ["", undefined, null]) {
    for (const overrides of [
      { timeZone: "Europe/Berlin" },
      { timeZone: "Europe/Kyiv" },
      { timeZone: "Europe/Kyiv", search: "?cookie_region=eea" },
      { timeZone: "Europe/Berlin", storedChoice: "granted" },
    ]) {
      assert.deepEqual(
        decide({ ...overrides, measurementId }),
        { showBanner: false, loadAnalytics: false },
        `${String(measurementId)} ${JSON.stringify(overrides)}`,
      );
    }
  }
});

test("the stored choice survives broken storage", () => {
  const broken = {
    getItem() {
      throw new Error("blocked");
    },
    setItem() {
      throw new Error("blocked");
    },
  };
  assert.equal(consent.readChoice(broken), null);
  assert.doesNotThrow(() => consent.saveChoice(broken, "granted"));

  const values = {};
  const storage = {
    getItem: (key) => (key in values ? values[key] : null),
    setItem: (key, value) => {
      values[key] = value;
    },
  };
  consent.saveChoice(storage, "denied");
  assert.equal(values.cookie_consent, "denied");
  assert.equal(consent.readChoice(storage), "denied");
  values.cookie_consent = "maybe";
  assert.equal(consent.readChoice(storage), null);
});

test("loading analytics sets consent defaults before config and inserts gtag once", () => {
  const { win, doc, appended } = fakeDom();
  const analytics = consent.createAnalytics({ win, doc, measurementId: MEASUREMENT_ID });

  analytics.load();
  analytics.load();

  const entries = calls(win);
  assert.deepEqual(entries[0], ["consent", "default", GRANTED_DEFAULTS]);
  assert.equal(entries[1][0], "js");
  assert.deepEqual(entries[2], ["config", MEASUREMENT_ID]);
  assert.equal(entries.length, 3);
  assert.equal(appended.length, 1);
  assert.equal(appended[0].src, "https://www.googletagmanager.com/gtag/js?id=G-TEST");
  assert.equal(appended[0].async, true);
});

test("without a measurement id nothing is loaded", () => {
  const { win, doc, appended } = fakeDom();
  consent.createAnalytics({ win, doc, measurementId: "" }).load();

  assert.equal(appended.length, 0);
  assert.deepEqual(calls(win), []);
});

test("allowing again after a rejection grants consent in the same view", () => {
  const { win, doc, appended } = fakeDom();
  const analytics = consent.createAnalytics({ win, doc, measurementId: MEASUREMENT_ID });
  analytics.load();
  analytics.deny();

  analytics.load();

  assert.deepEqual(calls(win).at(-1), ["consent", "update", GRANTED_DEFAULTS]);
  assert.equal(win["ga-disable-G-TEST"], false);
  assert.equal(appended.length, 1);
});

test("rejecting after loading denies consent, disables GA and removes GA and Ads cookies", () => {
  const { win, doc, cookieWrites } = fakeDom(
    "www.example.com",
    "_ga=GA1.1.1; _ga_ABC123=GS1.1; _gcl_au=1.1.1; _gcl_aw=GCL.1; _gcl_gb=GCL.2; other=1",
  );
  const analytics = consent.createAnalytics({ win, doc, measurementId: MEASUREMENT_ID });
  analytics.load();

  analytics.deny();

  assert.deepEqual(calls(win).at(-1), ["consent", "update", ALL_DENIED]);
  assert.equal(win["ga-disable-G-TEST"], true);
  for (const name of ["_ga", "_ga_ABC123", "_gcl_au", "_gcl_aw", "_gcl_gb"]) {
    assert.ok(cookieWrites.includes(`${name}=; Max-Age=0; path=/`), name);
    assert.ok(cookieWrites.includes(`${name}=; Max-Age=0; path=/; domain=.example.com`), name);
  }
  assert.ok(!cookieWrites.some((write) => write.startsWith("other=")));
});

test("cookies are removed for every parent domain of the current host, not a fixed one", () => {
  const { win, doc, cookieWrites } = fakeDom("app-production.up.railway.app", "_ga=GA1.1.1");
  consent.createAnalytics({ win, doc, measurementId: MEASUREMENT_ID }).deny();

  assert.deepEqual(cookieWrites, [
    "_ga=; Max-Age=0; path=/",
    "_ga=; Max-Age=0; path=/; domain=.app-production.up.railway.app",
    "_ga=; Max-Age=0; path=/; domain=.up.railway.app",
    "_ga=; Max-Age=0; path=/; domain=.railway.app",
  ]);
});

test("on an IP address or localhost only host cookies are removed", () => {
  for (const host of ["127.0.0.1", "localhost", "[::1]"]) {
    const { win, doc, cookieWrites } = fakeDom(host, "_ga=GA1.1.1");
    consent.createAnalytics({ win, doc, measurementId: MEASUREMENT_ID }).deny();
    assert.deepEqual(cookieWrites, ["_ga=; Max-Age=0; path=/"], host);
  }
});

test("the page keeps room for the visible banner so it covers nothing", () => {
  const body = { style: {} };
  const banner = { hidden: false, offsetHeight: 280 };

  consent.reserveSpace(body, banner);
  assert.equal(body.style.paddingBottom, "280px");

  banner.hidden = true;
  consent.reserveSpace(body, banner);
  assert.equal(body.style.paddingBottom, "");
});

test("rejecting before loading inserts nothing", () => {
  const { win, doc, appended } = fakeDom();
  consent.createAnalytics({ win, doc, measurementId: MEASUREMENT_ID }).deny();

  assert.equal(appended.length, 0);
  assert.equal(win["ga-disable-G-TEST"], true);
});
