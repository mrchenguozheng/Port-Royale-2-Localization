/* Tiny i18n loader for the standalone translator editor.
 *
 * English is the only shipped UI for now. Add i18n/<code>.json to extend it;
 * open the page with ?ui=<code> (or set window.__PR2_UI_LANG__ before this
 * script) to select it. Missing or empty values fall back to English.
 */
(function () {
  "use strict";

  const params = new URLSearchParams(location.search);
  const requested = (window.__PR2_UI_LANG__ || params.get("ui") || "en")
    .toLowerCase().replace(/[^a-z0-9_-]/g, "") || "en";
  const messages = Object.create(null);
  const base = Object.create(null);

  function textOf(key) {
    const value = messages[key];
    if (typeof value === "string" && value.trim()) return value;
    const fallback = base[key];
    if (typeof fallback === "string" && fallback.trim()) return fallback;
    return key;
  }

  function t(key, vars) {
    let text = textOf(key);
    if (vars) {
      for (const [name, value] of Object.entries(vars)) {
        text = text.split("{" + name + "}").join(String(value));
      }
    }
    return text;
  }

  function apply(root) {
    const scope = root || document;
    scope.querySelectorAll("[data-i18n]").forEach((el) => {
      el.textContent = t(el.getAttribute("data-i18n"));
    });
    scope.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
      el.setAttribute("placeholder", t(el.getAttribute("data-i18n-placeholder")));
    });
    scope.querySelectorAll("[data-i18n-title]").forEach((el) => {
      el.setAttribute("title", t(el.getAttribute("data-i18n-title")));
    });
  }

  function load(code) {
    return fetch("/i18n/" + code + ".json", {cache: "no-cache"})
      .then((r) => {
        if (!r.ok) throw new Error("missing " + code);
        return r.json();
      });
  }

  window.PR2_I18N = {lang: requested, t, apply};
  window.t = t;
  window.applyI18n = apply;

  const english = load("en").catch((err) => {
    console.warn("i18n: no English base:", err);
    return {};
  });
  const selected = requested === "en" ? Promise.resolve(null)
    : load(requested).catch((err) => {
      console.warn("i18n: falling back to English:", err);
      return null;
    });

  window.I18N_READY = Promise.all([english, selected]).then(([en, chosen]) => {
    if (en && typeof en === "object") Object.assign(base, en);
    if (chosen && typeof chosen === "object") {
      for (const [key, value] of Object.entries(chosen)) {
        if (typeof value === "string" && value.trim()) messages[key] = value;
      }
    }
    document.documentElement.lang = requested;
    apply(document);
  });
})();
