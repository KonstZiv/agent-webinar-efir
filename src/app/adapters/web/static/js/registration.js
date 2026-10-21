// The registration form on top of htmx and Cloudflare Turnstile (docs/requirements.md,
// section 5). No other libraries; the logic is v1's register.js plus the button that waits
// for Turnstile.
//
// The button is enabled in the HTML, so without JavaScript the form is a plain POST and the
// server answers with the whole page. With JavaScript it stays disabled until Turnstile has
// given a token, and again once the token expires or the widget is reset. While a request is
// in flight the button says «Надсилаємо…» (its data-busy-label). A failed request shows the
// hidden «network or server» message and resets the widget: the request may have spent its
// single-use token. After htmx puts a new form or the success screen into #register, the new
// widget is rendered and focus moves to the first error or to the screen's title.
//
// Turnstile renders nothing by itself (api.js?render=explicit): this script renders each widget
// once, with its callbacks, from the widget's data-* attributes. api.js and this script load in
// either order: api.js calls onload=registrationTurnstileLoad when it is ready, and if it ran
// before this script defined that function, start() renders the widget instead.
(function () {
  "use strict";

  const SECTION_ID = "register";
  let tokenReady = false;

  function section() {
    return document.getElementById(SECTION_ID);
  }

  function inSection(event) {
    const target = event.detail && event.detail.target;
    return Boolean(target && target.id === SECTION_ID);
  }

  function submitButton(root) {
    return root ? root.querySelector("button[type=submit][data-busy-label]") : null;
  }

  function syncButton() {
    const button = submitButton(section());
    if (button && !button.dataset.idleLabel) button.disabled = !tokenReady;
  }

  function tokenGiven(token) {
    tokenReady = Boolean(token);
    syncButton();
  }

  function tokenGone() {
    tokenReady = false;
    syncButton();
  }

  function setBusy(busy) {
    const button = submitButton(section());
    if (!button) return;
    if (busy) {
      button.dataset.idleLabel = button.textContent;
      button.textContent = button.dataset.busyLabel;
      button.disabled = true;
    } else if (button.dataset.idleLabel) {
      button.textContent = button.dataset.idleLabel;
      delete button.dataset.idleLabel;
    }
  }

  // The token is spent or gone: the button waits for the next one, whichever htmx event came
  // last (without an answer htmx sends afterRequest first, then sendError).
  function resetTurnstile(root) {
    tokenReady = false;
    syncButton();
    if (!root || !window.turnstile) return;
    for (const widget of root.querySelectorAll(".cf-turnstile")) {
      try {
        window.turnstile.reset(widget);
      } catch {
        // Not rendered yet: it will produce its first token by itself.
      }
    }
  }

  function showNetworkError() {
    const root = section();
    resetTurnstile(root);
    const message = root && root.querySelector("[data-network-error]");
    if (!message) return;
    message.hidden = false;
    message.focus({ preventScroll: false });
  }

  function renderTurnstile(root) {
    if (!root || !window.turnstile) return; // api.js will call registrationTurnstileLoad
    for (const widget of root.querySelectorAll(".cf-turnstile")) {
      if (widget.dataset.rendered) continue;
      window.turnstile.render(widget, {
        sitekey: widget.dataset.sitekey,
        language: widget.dataset.language,
        theme: widget.dataset.theme,
        callback: tokenGiven,
        "expired-callback": tokenGone,
        "error-callback": tokenGone,
      });
      widget.dataset.rendered = "true";
    }
  }

  // api.js calls it by name (onload=registrationTurnstileLoad) once window.turnstile is ready.
  window.registrationTurnstileLoad = function () {
    renderTurnstile(section());
  };

  function moveFocus(root) {
    const target = root.querySelector(
      '[aria-invalid="true"], [data-focus], .form-error[role="alert"]:not([hidden])',
    );
    if (target) target.focus();
  }

  document.addEventListener("htmx:beforeRequest", (event) => {
    if (!inSection(event)) return;
    const message = section().querySelector("[data-network-error]");
    if (message) message.hidden = true;
    setBusy(true);
  });

  document.addEventListener("htmx:afterRequest", (event) => {
    if (!inSection(event)) return;
    setBusy(false);
    syncButton();
  });

  // No answer at all, or an answer htmx does not put into the page (e.g. 502 from the proxy).
  document.addEventListener("htmx:sendError", (event) => {
    if (inSection(event)) showNetworkError();
  });
  document.addEventListener("htmx:responseError", (event) => {
    if (inSection(event)) showNetworkError();
  });

  // The old widget leaves the page with the swap: let Turnstile forget it first.
  document.addEventListener("htmx:beforeSwap", (event) => {
    if (!inSection(event) || !event.detail.shouldSwap) return;
    tokenReady = false;
    if (!window.turnstile) return;
    for (const widget of section().querySelectorAll(".cf-turnstile")) {
      try {
        window.turnstile.remove(widget);
      } catch {
        // Not rendered yet: nothing to clean up.
      }
    }
  });

  document.addEventListener("htmx:afterSettle", (event) => {
    if (!inSection(event)) return;
    const root = section();
    syncButton();
    renderTurnstile(root);
    moveFocus(root);
  });

  function start() {
    syncButton();
    renderTurnstile(section()); // api.js may have run first
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
