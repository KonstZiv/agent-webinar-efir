// Cookie banner and Google Consent Mode v2 (texts: docs/legal/cookie-banner.md). No libraries.
//
// EEA, UK and Swiss visitors (by the browser time zone, or ?cookie_region=eea) see the banner,
// and nothing is requested from Google until they allow analytics. Everyone else gets
// analytics at once. A stored choice (localStorage) always wins over the region. Without a
// measurement id (GA4_MEASUREMENT_ID) there is no analytics, so the banner does not show up
// by itself; the «cookie settings» link still opens it.
// The pure functions are exported for `node --test` (tests/js/consent.test.cjs).
(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  } else {
    api.start(root);
  }
})(typeof window !== "undefined" ? window : globalThis, function () {
  "use strict";

  const STORAGE_KEY = "cookie_consent";
  const CHOICES = ["granted", "denied"];
  const GTAG_URL = "https://www.googletagmanager.com/gtag/js?id=";
  // Cookies of Google Analytics (_ga, _ga_<id>) and Google Ads conversion linking (_gcl_*).
  const TRACKING_COOKIE = /^(_ga|_ga_.+|_gcl_.+)$/;
  // «Allow» covers analytics and ad measurement, not ad personalisation (cookie-banner.md).
  const GRANTED = {
    analytics_storage: "granted",
    ad_storage: "granted",
    ad_user_data: "granted",
    ad_personalization: "denied",
  };
  const DENIED = {
    analytics_storage: "denied",
    ad_storage: "denied",
    ad_user_data: "denied",
    ad_personalization: "denied",
  };

  // With a margin: every zone of these countries in zone.tab (EU, IS, LI, NO, GB, CH, EU
  // outermost regions, Åland, Svalbard, Gibraltar and the Crown Dependencies), tzdata merge
  // targets and zones shared with non-EEA neighbours, and legacy aliases.
  // tests/test_consent_zones.py checks this list against zone.tab.
  const EEA_TIME_ZONES = [
    // zone.tab
    "Africa/Ceuta",
    "America/Cayenne",
    "America/Guadeloupe",
    "America/Marigot",
    "America/Martinique",
    "Arctic/Longyearbyen",
    "Asia/Famagusta",
    "Asia/Nicosia",
    "Atlantic/Azores",
    "Atlantic/Canary",
    "Atlantic/Madeira",
    "Atlantic/Reykjavik",
    "Europe/Amsterdam",
    "Europe/Athens",
    "Europe/Berlin",
    "Europe/Bratislava",
    "Europe/Brussels",
    "Europe/Bucharest",
    "Europe/Budapest",
    "Europe/Busingen",
    "Europe/Copenhagen",
    "Europe/Dublin",
    "Europe/Gibraltar",
    "Europe/Guernsey",
    "Europe/Helsinki",
    "Europe/Isle_of_Man",
    "Europe/Jersey",
    "Europe/Lisbon",
    "Europe/Ljubljana",
    "Europe/London",
    "Europe/Luxembourg",
    "Europe/Madrid",
    "Europe/Malta",
    "Europe/Mariehamn",
    "Europe/Oslo",
    "Europe/Paris",
    "Europe/Prague",
    "Europe/Riga",
    "Europe/Rome",
    "Europe/Sofia",
    "Europe/Stockholm",
    "Europe/Tallinn",
    "Europe/Vaduz",
    "Europe/Vienna",
    "Europe/Vilnius",
    "Europe/Warsaw",
    "Europe/Zagreb",
    "Europe/Zurich",
    "Indian/Mayotte",
    "Indian/Reunion",
    // merge targets and shared zones
    "Africa/Abidjan",
    "Europe/Belgrade",
    "Europe/Monaco",
    "Europe/Podgorica",
    "Europe/San_Marino",
    "Europe/Sarajevo",
    "Europe/Skopje",
    "Europe/Vatican",
    // legacy aliases
    "Atlantic/Jan_Mayen",
    "CET",
    "EET",
    "Eire",
    "Europe/Belfast",
    "Europe/Nicosia",
    "GB",
    "GB-Eire",
    "Iceland",
    "MET",
    "Poland",
    "Portugal",
    "WET",
  ];
  const EEA = new Set(EEA_TIME_ZONES);
  // Zones that say nothing about the region (privacy modes report UTC).
  const UNDETERMINED = new Set(["UTC", "UCT", "GMT", "GMT0", "GMT+0", "GMT-0", "Greenwich", "Universal", "Zulu"]);

  function isEeaTimeZone(timeZone) {
    if (!timeZone || typeof timeZone !== "string") return true;
    if (UNDETERMINED.has(timeZone) || timeZone.startsWith("Etc/")) return true;
    return EEA.has(timeZone);
  }

  function readTimeZone(intl) {
    try {
      return intl.DateTimeFormat().resolvedOptions().timeZone || "";
    } catch {
      return "";
    }
  }

  function forcedEea(search) {
    try {
      return new URLSearchParams(search || "").get("cookie_region") === "eea";
    } catch {
      return false;
    }
  }

  function decide({ timeZone, storedChoice, search, measurementId }) {
    // No measurement id, no analytics: there is nothing to ask consent for.
    if (!measurementId) return { showBanner: false, loadAnalytics: false };
    if (storedChoice === "granted") return { showBanner: false, loadAnalytics: true };
    if (storedChoice === "denied") return { showBanner: false, loadAnalytics: false };
    if (forcedEea(search) || isEeaTimeZone(timeZone)) {
      return { showBanner: true, loadAnalytics: false };
    }
    return { showBanner: false, loadAnalytics: true };
  }

  function readChoice(storage) {
    try {
      const value = storage.getItem(STORAGE_KEY);
      return CHOICES.includes(value) ? value : null;
    } catch {
      return null;
    }
  }

  function saveChoice(storage, value) {
    try {
      storage.setItem(STORAGE_KEY, value);
    } catch {
      // Storage is unavailable: the choice lasts for this page only.
    }
  }

  // Domains a cookie for `host` may have been set on: the host and each parent domain
  // (GA picks the highest one the browser accepts). None for IP addresses and single labels.
  function cookieDomains(host) {
    if (!host || !host.includes(".") || /^[\d.]+$/.test(host) || host.includes(":")) return [];
    const labels = host.split(".");
    const domains = [];
    for (let index = 0; index < labels.length - 1; index += 1) {
      domains.push("." + labels.slice(index).join("."));
    }
    return domains;
  }

  function removeTrackingCookies(win, doc) {
    let names;
    try {
      names = doc.cookie
        .split(";")
        .map((part) => part.split("=")[0].trim())
        .filter((name) => TRACKING_COOKIE.test(name));
    } catch {
      return;
    }
    const host = (win.location && win.location.hostname) || "";
    const scopes = ["", ...cookieDomains(host).map((domain) => "; domain=" + domain)];
    for (const name of names) {
      for (const scope of scopes) {
        doc.cookie = `${name}=; Max-Age=0; path=/${scope}`;
      }
    }
  }

  // A fixed banner must not hide the end of the page (forms, the footer).
  function reserveSpace(body, banner) {
    if (!body || !banner) return;
    body.style.paddingBottom = banner.hidden ? "" : banner.offsetHeight + "px";
  }

  function createAnalytics({ win, doc, measurementId }) {
    let loaded = false;
    let denied = false;
    const disableKey = "ga-disable-" + measurementId;

    function gtag() {
      // gtag.js reads `arguments` objects from dataLayer; arrays are ignored.
      win.dataLayer.push(arguments);
    }

    return {
      load() {
        if (!measurementId) return;
        if (loaded) {
          if (denied) {
            denied = false;
            win[disableKey] = false;
            gtag("consent", "update", Object.assign({}, GRANTED));
          }
          return;
        }
        loaded = true;
        win[disableKey] = false;
        win.dataLayer = win.dataLayer || [];
        win.gtag = gtag;
        gtag("consent", "default", Object.assign({}, GRANTED));
        gtag("js", new Date());
        gtag("config", measurementId);
        const script = doc.createElement("script");
        script.async = true;
        script.src = GTAG_URL + encodeURIComponent(measurementId);
        doc.head.appendChild(script);
      },
      deny() {
        denied = true;
        if (measurementId) win[disableKey] = true; // Google's opt-out: no more hits at all
        if (loaded) gtag("consent", "update", Object.assign({}, DENIED));
        removeTrackingCookies(win, doc);
      },
    };
  }

  function start(win) {
    const doc = win.document;

    function run() {
      const banner = doc.querySelector(".cookie-banner");
      const measurementId = (doc.body && doc.body.dataset.ga4Id) || "";
      const analytics = createAnalytics({ win, doc, measurementId });
      let storage = null;
      try {
        storage = win.localStorage;
      } catch {
        storage = null;
      }

      function setBannerHidden(hidden) {
        if (!banner) return;
        banner.hidden = hidden;
        reserveSpace(doc.body, banner);
      }

      function showBanner() {
        if (!banner) return;
        setBannerHidden(false);
        const first = banner.querySelector("button");
        if (first) first.focus({ preventScroll: true });
      }

      const decision = decide({
        timeZone: readTimeZone(win.Intl),
        storedChoice: readChoice(storage),
        search: win.location.search,
        measurementId,
      });
      if (decision.loadAnalytics) analytics.load();
      if (decision.showBanner) setBannerHidden(false);
      win.addEventListener("resize", () => reserveSpace(doc.body, banner));

      if (banner) {
        banner.addEventListener("click", (event) => {
          const button = event.target.closest("[data-consent]");
          if (!button) return;
          const choice = button.dataset.consent;
          saveChoice(storage, choice);
          setBannerHidden(true);
          if (choice === "granted") analytics.load();
          else analytics.deny();
        });
      }
      for (const link of doc.querySelectorAll("[data-cookie-settings]")) {
        link.addEventListener("click", (event) => {
          event.preventDefault();
          showBanner();
        });
      }
    }

    if (doc.readyState === "loading") doc.addEventListener("DOMContentLoaded", run);
    else run();
  }

  return {
    EEA_TIME_ZONES,
    isEeaTimeZone,
    readTimeZone,
    decide,
    readChoice,
    saveChoice,
    createAnalytics,
    reserveSpace,
    start,
  };
});
