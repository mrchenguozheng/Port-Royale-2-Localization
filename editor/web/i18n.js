/* Tiny i18n loader for the standalone translator editor.
 *
 * English is the only shipped UI for now. Add i18n/<code>.json to extend it;
 * open the page with ?ui=<code> (or set window.__PR2_UI_LANG__ before this
 * script) to select it. Missing files fall back to English.
 */
(function () {
  "use strict";

  const params = new URLSearchParams(location.search);
  const requested = (window.__PR2_UI_LANG__ || params.get("ui") || "en")
    .toLowerCase().replace(/[^a-z0-9_-]/g, "") || "en";
  const messages = Object.create(null);

  function t(key, vars) {
    let text = messages[key];
    if (text === undefined) return key;
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

  window.I18N_READY = load(requested)
    .catch(() => (requested === "en" ? null : load("en")))
    .then((data) => {
      if (!data) throw new Error("no UI translation");
      Object.assign(messages, data);
      document.documentElement.lang = requested;
      apply(document);
      return requested;
    })
    .catch((err) => {
      console.warn("i18n:", err);
      return requested;
    });
})();
