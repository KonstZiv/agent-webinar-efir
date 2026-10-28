// The teacher's page of the attendance (docs/requirements.md, section 9a; texts: docs/copy.md,
// 14.4). No libraries. The HTML is a shell without data: this script takes the admin token from
// the form, keeps it in the sessionStorage of this tab only (no cookie, no localStorage) and
// fetches everything from the admin API with "Authorization: Bearer <token>".
//
// The screens: login -> start -> board (the code, the countdown, the counter) -> summary.
// A 401 on any request wipes the token and shows the login again. The countdown follows the
// server's clock: the offset comes from the "Date" header of the responses. The addresses of the
// participants (entries[].email) are never put into the page or the console: the screen is shown
// in Teams. Texts with values come from the JSON in the page (#checkin-admin-config); this file
// has no texts of its own.
(function () {
  "use strict";

  const TOKEN_KEY = "checkin-admin-token";
  const POLL_MS = 5000;
  const TICK_MS = 1000;
  const NO_VALUE = "—";

  const config = JSON.parse(document.getElementById("checkin-admin-config").textContent);
  const texts = config.texts;
  const groupPattern = new RegExp("^" + config.group_pattern + "$");

  const $ = (id) => document.getElementById(id);
  const screens = {
    login: $("admin-login"),
    start: $("admin-start"),
    board: $("admin-board"),
    summary: $("admin-summary"),
  };

  let token = readToken();
  let clockOffset = 0; // server time minus the browser's, in milliseconds
  let current = null; // the check-in on the board: {id, closesAt}
  let tickTimer = null;
  let pollTimer = null;
  let finishing = false;

  // --- the token: sessionStorage of this tab, every access guarded -------------------------

  function readToken() {
    try {
      return window.sessionStorage.getItem(TOKEN_KEY) || "";
    } catch (error) {
      return "";
    }
  }

  function writeToken(value) {
    token = value;
    try {
      if (value) {
        window.sessionStorage.setItem(TOKEN_KEY, value);
      } else {
        window.sessionStorage.removeItem(TOKEN_KEY);
      }
    } catch (error) {
      // The storage is not available: the token lives until the page is closed.
    }
  }

  // --- helpers ---------------------------------------------------------------------------

  function fill(template, values) {
    return template.replace(/\{(\w+)\}/g, (match, name) =>
      Object.prototype.hasOwnProperty.call(values, name) ? String(values[name]) : match,
    );
  }

  function show(name) {
    Object.keys(screens).forEach((key) => {
      screens[key].hidden = key !== name;
    });
  }

  function setNetworkError(visible) {
    $("admin-error").hidden = !visible;
  }

  function serverNow() {
    return Date.now() + clockOffset;
  }

  function lessonDate() {
    // YYYY-MM-DD in Kyiv: the lesson's date is the teacher's day, not the browser's.
    return new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Kyiv" }).format(new Date());
  }

  function stopTimers() {
    window.clearInterval(tickTimer);
    window.clearInterval(pollTimer);
    tickTimer = null;
    pollTimer = null;
  }

  // --- the admin API ---------------------------------------------------------------------

  class Unauthorized extends Error {}

  // Resolves to {status, body}; rejects with Unauthorized on 401 (the token is wiped and the
  // login shown) and with a plain Error when the network fails or the server is unavailable.
  async function api(method, path, payload) {
    const options = { method: method, headers: { Authorization: "Bearer " + token } };
    if (payload !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(payload);
    }
    let response;
    try {
      response = await window.fetch(path, options);
    } catch (error) {
      setNetworkError(true);
      throw new Error("network");
    }
    const sent = Date.parse(response.headers.get("Date") || "");
    if (!Number.isNaN(sent)) {
      clockOffset = sent - Date.now();
    }
    if (response.status === 401) {
      rejectToken();
      throw new Unauthorized();
    }
    if (response.status === 503 || response.status >= 500) {
      setNetworkError(true);
      throw new Error("server");
    }
    setNetworkError(false);
    let body = null;
    try {
      body = await response.json();
    } catch (error) {
      body = null;
    }
    return { status: response.status, body: body };
  }

  function rejectToken() {
    stopTimers();
    writeToken("");
    current = null;
    $("admin-login-error").hidden = false;
    $("admin-token").value = "";
    show("login");
    $("admin-token").focus();
  }

  // --- login -----------------------------------------------------------------------------

  screens.login.addEventListener("submit", (event) => {
    event.preventDefault();
    const value = $("admin-token").value.trim();
    if (!value) {
      return;
    }
    $("admin-login-error").hidden = true;
    writeToken(value);
    $("admin-token").value = "";
    begin();
  });

  // --- start -----------------------------------------------------------------------------

  async function begin() {
    // An open check-in survives a reload of the page: the freshest open one is shown again.
    let listed;
    try {
      listed = await api("GET", "/admin/checkins");
    } catch (error) {
      if (!(error instanceof Unauthorized)) {
        window.setTimeout(begin, POLL_MS);
      }
      return;
    }
    const open = (Array.isArray(listed.body) ? listed.body : [])
      .filter((item) => Date.parse(item.closes_at) > serverNow())
      .sort((a, b) => b.id - a.id)[0];
    if (open) {
      showBoard(open, null);
      return;
    }
    await showStart(listed.body);
  }

  async function showStart(checkins) {
    stopTimers();
    current = null;
    $("admin-start-error").hidden = true;
    $("admin-minutes").value = config.default_minutes;
    show("start");
    const groups = new Set();
    (Array.isArray(checkins) ? checkins : []).forEach((item) => {
      if (item.group) {
        groups.add(item.group);
      }
    });
    try {
      const known = await api("GET", "/admin/groups");
      Object.keys(known.body || {}).forEach((code) => groups.add(code));
    } catch (error) {
      // The list is a convenience; the field works without it.
    }
    const list = $("admin-groups");
    list.textContent = "";
    Array.from(groups)
      .sort()
      .forEach((code) => {
        const option = document.createElement("option");
        option.value = code;
        list.appendChild(option);
      });
    $("admin-group").focus();
  }

  function startError(text) {
    const box = $("admin-start-error");
    box.textContent = text;
    box.hidden = false;
  }

  screens.start.addEventListener("submit", async (event) => {
    event.preventDefault();
    const group = $("admin-group").value.trim();
    const minutes = Number($("admin-minutes").value);
    if (!groupPattern.test(group)) {
      startError(texts.group_invalid);
      return;
    }
    if (!Number.isInteger(minutes) || minutes < config.min_minutes || minutes > config.max_minutes) {
      startError(texts.minutes_invalid);
      return;
    }
    $("admin-start-error").hidden = true;
    let answer;
    try {
      answer = await api("POST", "/admin/checkins", {
        lesson_date: lessonDate(),
        group: group,
        window_minutes: minutes,
      });
    } catch (error) {
      return;
    }
    if (answer.status === 201) {
      showBoard(answer.body, answer.body.posted);
    } else if (answer.status === 409) {
      showBoard(answer.body, null); // the group already has an open check-in: show that one
    } else {
      setNetworkError(true);
    }
  });

  // --- the board -------------------------------------------------------------------------

  function showBoard(checkin, posted) {
    stopTimers();
    finishing = false;
    current = { id: checkin.id, closesAt: Date.parse(checkin.closes_at) };
    $("admin-board-group").textContent = fill(texts.group, { group: checkin.group || NO_VALUE });
    $("admin-board-code").textContent = fill(texts.code, { code: checkin.code });
    $("admin-not-posted").hidden = posted !== false;
    renderCounter(checkin.attended || 0);
    show("board");
    tick();
    tickTimer = window.setInterval(tick, TICK_MS);
    pollTimer = window.setInterval(poll, POLL_MS);
    poll();
  }

  function renderCounter(attended) {
    $("admin-board-counter").textContent = fill(texts.counter, { attended: attended });
  }

  function tick() {
    if (current === null) {
      return;
    }
    const left = Math.max(0, Math.ceil((current.closesAt - serverNow()) / 1000));
    const minutes = String(Math.floor(left / 60)).padStart(2, "0");
    const seconds = String(left % 60).padStart(2, "0");
    $("admin-board-countdown").textContent = fill(texts.countdown, {
      time: minutes + ":" + seconds,
    });
    if (left === 0) {
      finish();
    }
  }

  async function poll() {
    if (current === null || finishing) {
      return;
    }
    const id = current.id;
    try {
      const report = await api("GET", "/admin/checkins/" + id);
      if (current !== null && current.id === id && report.status === 200) {
        renderCounter(report.body.attended);
        current.closesAt = Date.parse(report.body.closes_at); // closed from the bot meanwhile
      }
    } catch (error) {
      // The next poll tries again; the network message is already shown.
    }
  }

  $("admin-close").addEventListener("click", async () => {
    if (current === null) {
      return;
    }
    try {
      await api("POST", "/admin/checkins/" + current.id + "/close");
    } catch (error) {
      return;
    }
    finish();
  });

  // --- the summary -----------------------------------------------------------------------

  async function finish() {
    if (current === null || finishing) {
      return;
    }
    finishing = true;
    stopTimers();
    const id = current.id;
    let report;
    try {
      report = await api("GET", "/admin/checkins/" + id);
    } catch (error) {
      if (!(error instanceof Unauthorized) && current !== null) {
        finishing = false;
        window.setTimeout(finish, POLL_MS); // the network is down: try again
      }
      return;
    }
    if (report.status !== 200) {
      finishing = false;
      return;
    }
    renderSummary(report.body);
  }

  function renderSummary(report) {
    // Only counts, ratings and the questions' texts are taken; the addresses are left alone.
    const entries = Array.isArray(report.entries) ? report.entries : [];
    const site = entries.filter((entry) => entry.source === "site").length;
    const telegram = entries.filter((entry) => entry.source === "telegram").length;
    const questions = entries.map((entry) => entry.question).filter((text) => Boolean(text));
    const ratings = report.ratings || {};
    $("admin-summary-count").textContent = fill(texts.summary_count, {
      attended: report.attended,
      site: site,
      telegram: telegram,
    });
    $("admin-summary-ratings").textContent = fill(texts.summary_ratings, {
      r5: ratings["5"] || 0,
      r4: ratings["4"] || 0,
      r3: ratings["3"] || 0,
      r2: ratings["2"] || 0,
      r1: ratings["1"] || 0,
      average: typeof report.average === "number" ? report.average.toFixed(1) : NO_VALUE,
    });
    const button = $("admin-questions-button");
    button.textContent = fill(texts.questions_button, { questions_count: questions.length });
    const list = $("admin-questions");
    list.textContent = "";
    list.hidden = true;
    $("admin-no-questions").hidden = true;
    questions.forEach((text) => {
      const item = document.createElement("li");
      item.textContent = text;
      list.appendChild(item);
    });
    button.hidden = false;
    show("summary");
  }

  $("admin-questions-button").addEventListener("click", () => {
    const hasQuestions = $("admin-questions").children.length > 0;
    $("admin-questions").hidden = !hasQuestions;
    $("admin-no-questions").hidden = hasQuestions;
    $("admin-questions-button").hidden = true;
  });

  $("admin-new").addEventListener("click", async () => {
    current = null;
    try {
      const listed = await api("GET", "/admin/checkins");
      await showStart(listed.body);
    } catch (error) {
      if (!(error instanceof Unauthorized)) {
        await showStart([]);
      }
    }
  });

  // --- start of the page -----------------------------------------------------------------

  if (token) {
    begin();
  } else {
    show("login");
  }
})();
