const PAGE = 100;
const EN = "en.gog_1.1.2.3";

const state = {
  lang: "",
  offset: 0,
  total: 0,
  rows: [],
  dirty: new Map(),
  problems: new Map(),
  search: "",
  searchRows: null,
};

const $ = (id) => document.getElementById(id);

async function api(path, body) {
  const opt = body === undefined ? {} : {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body),
  };
  const res = await fetch(path, opt);
  const text = await res.text();
  let data;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) {
    const msg = data && data.error ? data.error : (typeof data === "string" ? data : res.statusText);
    throw new Error(msg || ("HTTP " + res.status));
  }
  return data;
}

function setMessage(text, error) {
  const el = $("message");
  el.textContent = text || "";
  el.className = error ? "problem error" : "muted";
}

function target(row) {
  return state.dirty.has(row.id) ? state.dirty.get(row.id) : (row[state.lang] || "");
}

function render() {
  const tbody = $("rows");
  tbody.textContent = "";
  const rows = state.rows;
  if (!rows.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 4;
    td.className = "empty";
    td.textContent = state.total ? "No rows on this page." : "No entries found.";
    tr.appendChild(td);
    tbody.appendChild(tr);
    updatePager();
    return;
  }
  for (const row of rows) {
    const tr = document.createElement("tr");
    if (state.dirty.has(row.id)) tr.classList.add("dirty");

    const id = document.createElement("td");
    id.className = "id";
    id.textContent = row.id;

    const en = document.createElement("td");
    en.className = "en";
    en.textContent = row[EN] || "";

    const trCell = document.createElement("td");
    trCell.className = "tr";
    const ta = document.createElement("textarea");
    ta.value = target(row);
    ta.rows = 3;
    ta.addEventListener("input", () => {
      state.dirty.set(row.id, ta.value);
      tr.classList.add("dirty");
      $("save").disabled = state.dirty.size === 0;
      setMessage("");
    });
    ta.addEventListener("blur", () => {
      void checkRow(row, ta, trCell);
    });
    trCell.appendChild(ta);

    const status = document.createElement("td");
    status.className = "status";
    const problems = state.problems.get(row.id);
    if (problems && problems.length) {
      for (const p of problems) {
        const span = document.createElement("span");
        span.className = "problem " + (p.level === "error" ? "error" : "warn");
        span.textContent = p.text;
        status.appendChild(span);
      }
      if (problems.some((p) => p.level === "error")) tr.classList.add("error");
    }

    tr.append(id, en, trCell, status);
    tbody.appendChild(tr);
  }
  updatePager();
}

async function checkRow(row, ta, cell) {
  try {
    const problems = await api("/api/check", {
      id: row.id, text: ta.value, lang: state.lang,
    });
    state.problems.set(row.id, problems || []);
    const tr = ta.closest("tr");
    const old = cell.querySelectorAll(".problem");
    old.forEach((x) => x.remove());
    tr.classList.toggle("error",
      (problems || []).some((p) => p.level === "error"));
    for (const p of problems || []) {
      const span = document.createElement("span");
      span.className = "problem " + (p.level === "error" ? "error" : "warn");
      span.textContent = p.text;
      cell.appendChild(span);
    }
  } catch (err) {
    setMessage("Validation failed: " + err.message, true);
  }
}

function updatePager() {
  const shown = state.searchRows !== null ? state.searchRows.length : state.rows.length;
  const start = state.offset + 1;
  const end = state.offset + shown;
  $("pageInfo").textContent = state.total
    ? (start + "–" + end + " of " + state.total)
    : "0 entries";
  $("prev").disabled = state.offset <= 0;
  $("next").disabled = state.offset + shown >= state.total;
  $("stats").textContent = state.total + " entries · " + state.lang;
}

async function loadLanguages() {
  const data = await api("/api/langs");
  const langs = data.editable || [];
  const sel = $("lang");
  sel.textContent = "";
  for (const code of langs) {
    const opt = document.createElement("option");
    opt.value = code;
    opt.textContent = code;
    sel.appendChild(opt);
  }
  if (!langs.length) {
    setMessage("No editable language found.", true);
    return false;
  }
  const m = location.pathname.match(/^\/translate\/([^/]+)/);
  const wanted = m && langs.includes(m[1]) ? m[1] : langs[0];
  sel.value = wanted;
  state.lang = wanted;
  return true;
}

async function loadPage() {
  state.search = "";
  state.searchRows = null;
  state.problems.clear();
  const count = await api("/api/count?filter=all&lang=" + encodeURIComponent(state.lang));
  state.total = count.count || 0;
  state.offset = Math.min(state.offset, Math.max(0, state.total - 1));
  state.rows = await api(
    "/api/entries?offset=" + state.offset + "&limit=" + PAGE +
    "&filter=all&lang=" + encodeURIComponent(state.lang));
  render();
  setMessage("");
}

async function doSearch() {
  const q = $("search").value.trim();
  if (!q) { await clearSearch(); return; }
  if (state.dirty.size && !confirm("You have unsaved changes. Search anyway?")) return;
  const rows = await api("/api/search?q=" + encodeURIComponent(q) +
                         "&lang=" + encodeURIComponent(state.lang));
  state.search = q;
  state.searchRows = rows || [];
  state.rows = state.searchRows;
  state.total = state.rows.length;
  state.offset = 0;
  state.problems.clear();
  render();
  $("prev").disabled = true;
  $("next").disabled = true;
  $("pageInfo").textContent = state.total + " result(s)";
  setMessage("Search: " + q);
}

async function clearSearch() {
  $("search").value = "";
  state.search = "";
  state.searchRows = null;
  state.offset = 0;
  await loadPage();
}

async function save() {
  if (!state.dirty.size) return;
  const rows = [];
  for (const [id, text] of state.dirty) rows.push({id, text});
  $("save").disabled = true;
  try {
    const res = await api("/api/patch", {lang: state.lang, rows});
    state.dirty.clear();
    const byId = new Map(state.rows.map((r) => [r.id, r]));
    for (const row of rows) {
      const original = byId.get(row.id);
      if (original) original[state.lang] = row.text;
    }
    render();
    setMessage("Saved " + (res.changed ?? rows.length) + " row(s).");
  } catch (err) {
    setMessage("Save failed: " + err.message, true);
    $("save").disabled = state.dirty.size === 0;
  }
}

async function switchLanguage() {
  if (state.dirty.size && !confirm("You have unsaved changes. Switch language anyway?")) {
    $("lang").value = state.lang;
    return;
  }
  state.lang = $("lang").value;
  state.offset = 0;
  state.dirty.clear();
  await loadPage();
}

$("lang").addEventListener("change", () => void switchLanguage());
$("save").addEventListener("click", () => void save());
$("prev").addEventListener("click", async () => {
  if (state.offset <= 0) return;
  state.offset = Math.max(0, state.offset - PAGE);
  state.searchRows = null;
  await loadPage();
});
$("next").addEventListener("click", async () => {
  state.offset += PAGE;
  state.searchRows = null;
  await loadPage();
});
$("doSearch").addEventListener("click", () => void doSearch());
$("clearSearch").addEventListener("click", () => void clearSearch());
$("search").addEventListener("keydown", (e) => {
  if (e.key === "Enter") void doSearch();
});

(async () => {
  try {
    if (!(await loadLanguages())) return;
    await loadPage();
  } catch (err) {
    setMessage("Failed to load: " + err.message, true);
  }
})();
