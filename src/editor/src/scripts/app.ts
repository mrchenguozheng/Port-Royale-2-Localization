import '@shoelace-style/shoelace/dist/themes/dark.css';
import '@shoelace-style/shoelace/dist/components/dialog/dialog.js';
import '@shoelace-style/shoelace/dist/components/select/select.js';
import '@shoelace-style/shoelace/dist/components/option/option.js';
import '@shoelace-style/shoelace/dist/components/button/button.js';
import '@shoelace-style/shoelace/dist/components/alert/alert.js';
import '@shoelace-style/shoelace/dist/components/textarea/textarea.js';

// 编辑器的前端逻辑。
//
// 这一层只管三件事：**渲染、筛选、编辑**。
// 校验规则全在后端（Python）—— 因为规则本来就在 translate.py /
// compile_pack.py 里，那是唯一的一份。抄一份到 TS 就多一份实现，
// 两边不一致时没人知道该信哪个。
//
// 接口：
//   GET  /api/langs         -> {editable, all}
//   GET  /api/count         -> {count, ids}
//   GET  /api/entries?off&limit
//   GET  /api/search?q=     -> [entry]
//   POST /api/check         -> [{level, text}]
//   POST /api/patch         -> {ok, written, changed}
//   POST /api/newlang       -> {ok, code, from}   复制一份现成语言当模板
//
// 一页一取，不做「滚动到哪加载到哪」。
// 之前那套虚拟滚动有两个绕不过去的毛病，都是它自己的机制带来的：
//   * 占位块按「剩余条数 × 估算行高」撑高度，估算必然不准，
//     拖动滑块跳到底部时落点在一大片空白里；
//   * 用户跳到哪，就得从当前位置一路加载到哪 —— 拖一次到底
//     等于把三千多条全拉一遍。
// 现在的做法是明确分页：一次只取当页，页码、总数、每页条数都写在底栏上。
// 翻页时把改动留在 edits 里，跨页编辑照样能一次保存。

interface Problem {
  level: 'error' | 'warn';
  text: string;
}

interface Entry {
  id: string;
  ctx: string;
  /** 参考语言里缺这个 id 的那些语言代码（版本差异），由服务端给出。 */
  missing?: string[];
  [lang: string]: string | string[] | undefined;
}

const FOLLOW = '';                 // 参照下拉里的「（无）」

//: 每页固定一条：翻页就是逐条过。
const PAGE_SIZE = 1;
//: 每页条数存在浏览器里，下次打开沿用上次的选择。
const LS_LANG = 'pr2.lang';
const LS_SIZE = 'pr2.size';
const LS_SIZES = 'pr2.sizes';
const PRESET_SIZES = [14, 16, 18, 20, 24, 28, 32, 40, 48];
const LS_REFA = 'pr2.refA';
const LS_REFB = 'pr2.refB';
const LS_FILTER = 'pr2.filter';
const LS_PAGE = 'pr2.page.';

function saved(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}

function remember(key: string, value: string): void {
  try { localStorage.setItem(key, value); } catch { /* 隐私模式等，忽略 */ }
}

let infoSeq = 0;

const S = {
  langs: [] as string[],
  refLangs: [] as string[],
  lang: 'zh',
  filter: 'all',
  refA: 'en',
  refB: 'fr',
  //: 当前页的条目（已含服务端返回的全部语言字段）
  rows: [] as Entry[],
  page: 1,
  pageSize: PAGE_SIZE,
  //: 全部条数：未搜索时是总条数，搜索时是命中数
  total: 0,
  //: 搜索结果。null 表示没在搜索，整表按 offset/limit 分页取
  filtered: null as Entry[] | null,
  //: id -> 用户改过的文本。翻页不清空，保存时按它提交。
  edits: new Map<string, string>(),
  //: id -> 加载时的原文。改回原样就把这条从"未保存"里去掉。
  orig: new Map<string, string>(),
  //: id -> 英文原文里每种占位符需要的个数
  req: {} as Record<string, Record<string, number>>,
  undo: {} as Record<string, string[]>,
  last: {} as Record<string, string>,
  suppressUndo: false,
  seed: {} as Record<string, string>,
  curMeaning: new Map<string, string>(),
  curId: '',
  meaningSaved: {} as Record<string, boolean>,
  dirtyIds: [] as string[],
  size: 14,
  customSizes: [] as number[],
  problems: {} as Record<string, Problem[]>,
  /** 术语一致性： id -> ["Frigate：应为「巡防舰」", …] */
  terms: {} as Record<string, string[]>,
  /** 人工审核勾选：当前语言已勾选的 id 集合 */
  /** 当前正在编辑的那一条（同一时间只允许一条） */
  activeId: null as string | null,
  loading: false,
};

const $ = (id: string) => document.getElementById(id)!;

function initTabs() {
  for (const t of document.querySelectorAll('.tab')) {
    t.addEventListener('click', () => {
      const view = (t as HTMLElement).dataset.view || 'editor';
      void (async () => {
        if (view === 'start' && !(await guardLeave())) return;
        setView(view);
      })();
    });
  }
  setView(location.pathname.replace(/\/$/, '') === '/install' || location.hash === '#start' ? 'start' : 'editor');
}

let loadingTimer = 0;
let loadingShown = false;

/** 载入提示：超过 120ms 才显示，避免本地快速请求闪一下。 */
function setLoading(on: boolean) {
  const box = () => document.getElementById('loading');
  if (on) {
    clearTimeout(loadingTimer);
    loadingTimer = window.setTimeout(() => {
      const b = box();
      if (b) { b.hidden = false; loadingShown = true; }
    }, 120);
  } else {
    clearTimeout(loadingTimer);
    const b = box();
    if (b) b.hidden = true;
    loadingShown = false;
  }
}

function el(tag: string, cls?: string, text?: string): HTMLElement {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

async function api<T>(path: string, body?: unknown): Promise<T> {
  const opt: RequestInit = body === undefined
    ? {}
    : {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      };
  const r = await fetch(path, opt);
  if (!r.ok) {
    const t = await r.text();
    let msg = t || ('HTTP ' + r.status);
    try {
      const j = JSON.parse(t);
      if (j && j.detail) msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail);
    } catch { /* 不是 JSON 就用原文 */ }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

// ── 载入 ────────────────────────────────────────────────

function setView(view: string) {
  const start = view === 'start';
  const editor = document.getElementById('view-editor');
  const panel = document.getElementById('view-start');
  if (editor) editor.hidden = start;
  if (panel) panel.hidden = !start;
  document.body.classList.toggle('view-start', start);
  for (const t of document.querySelectorAll('.tab')) {
    t.classList.toggle('active', (t as HTMLElement).dataset.view === view);
  }
  history.replaceState(null, '', start ? '/install' : (S.rows[0] ? `/translate/${S.lang}/${S.page}` : `/translate/${S.lang}`));
}

async function boot() {
  const initialPath = location.pathname;
  if (location.protocol === 'file:') {
    showBootError('这是用文件方式打开的。请双击 start.bat，通过本地服务打开页面。');
    return;
  }
  setLoading(true);
  const d = await api<{ editable: string[]; all: string[]; base: string }>('/api/langs');
  S.langs = d.editable;
  S.refLangs = d.all;

  S.lang = S.langs.includes('zh') ? 'zh' : (S.langs[0] || '');


  // 上次选的编辑语言与参照语言
  const savedLang = saved(LS_LANG);
  if (savedLang && S.langs.includes(savedLang)) S.lang = savedLang;
  const savedA = saved(LS_REFA);
  if (savedA && S.refLangs.includes(savedA)) S.refA = savedA;
  const savedB = saved(LS_REFB);
  if (savedB !== null && (savedB === FOLLOW || S.refLangs.includes(savedB))) S.refB = savedB;

  const mFull = initialPath.match(/^\/translate\/([A-Za-z][A-Za-z-]*)\/(.+)$/);
  if (mFull && S.langs.includes(mFull[1])) S.lang = mFull[1];

  S.filter = 'all';
  // 参照默认取基准语言（en.gog_1.1.2.3 这类带来源与版本的名字）。
  S.refA = d.all.includes(d.base) ? d.base : (d.all[0] || '');
  S.refB = S.refLangs.includes('fr.gog_1.1.2.42') ? 'fr.gog_1.1.2.42' : FOLLOW;

  // 术语一致性检查：术语表当规则，标在对应行上（慢一点也没关系，只取一次）
  try {
    const t = await api<{ issues: Record<string, string[]> }>('/api/terms?lang=' + encodeURIComponent(S.lang));
    S.terms = t.issues || {};
  } catch {
    S.terms = {};
  }


  initTabs();
  fill($('lang'), S.langs, S.lang);
  await loadSideList();

  const savedSize = Number(saved(LS_SIZE));
  if (Number.isFinite(savedSize) && savedSize >= 8 && savedSize <= 96) S.size = savedSize;
  try {
    const arr = JSON.parse(saved(LS_SIZES) || '[]');
    if (Array.isArray(arr)) {
      S.customSizes = arr.map(Number).filter((n) => Number.isFinite(n) && n >= 8 && n <= 96);
    }
  } catch { /* 忽略坏值 */ }
  fillSizeSelect();
  applySize();
  await reload(true);
  setLoading(false);
  const sp = Number(saved(pageKey()));
  if (sp > 1) await renderPage(sp);

  const mFullHash = initialPath.match(/^\/translate\/[A-Za-z][A-Za-z-]*\/(?:0x)?([0-9a-f]{8})$/i);
  const mFullNum = initialPath.match(/^\/translate\/[A-Za-z][A-Za-z-]*\/(\d+)$/);
  if (mFullHash) {
    await jumpToId('0x' + mFullHash[1].toLowerCase());
  } else if (mFullNum) {
    await renderPage(Number(mFullNum[1]));
  }
  updatePath();
}

function syncScrollers() {
  const panes = Array.from(
    document.querySelectorAll('.col-src .body, .col-src .seed-body'),
  ) as HTMLElement[];
  if (panes.length < 2) return;
  let lock = false;
  for (const p of panes) {
    if ((p as HTMLElement & { _sync?: boolean })._sync) continue;
    (p as HTMLElement & { _sync?: boolean })._sync = true;
    p.addEventListener('scroll', () => {
      if (lock) return;
      lock = true;
      const max = p.scrollHeight - p.clientHeight;
      const ratio = max > 0 ? p.scrollTop / max : 0;
      for (const q of panes) {
        if (q === p) continue;
        const m2 = q.scrollHeight - q.clientHeight;
        if (m2 > 0) q.scrollTop = ratio * m2;
      }
      window.requestAnimationFrame(() => { lock = false; });
    });
  }
}

function updatePath() {
  if (document.body.classList.contains('view-start')) return;
  const row = S.rows[0];
  const path = row ? `/translate/${S.lang}/${S.page}` : `/translate/${S.lang}`;
  if (location.pathname !== path) history.replaceState(null, '', path);
}

function pageKey(): string {
  return LS_PAGE + S.lang + '.' + S.filter;
}

/** 重新取「一共多少条」；resetPage=false 时留在当前页。 */
async function reload(resetPage = true) {
  const c = await api<{ count: number; ids: string[] }>(
    `/api/count?filter=${S.filter}&lang=${encodeURIComponent(S.lang)}`);
  S.filtered = null;
  S.total = c.count;
  if (resetPage) S.page = 1;
  await renderPage(S.page);
}

function pageCount(): number {
  return Math.max(1, Math.ceil(S.total / S.pageSize));
}

/** 取第 p 页并渲染。越界会被夹回有效范围。 */
async function guardLeave(): Promise<boolean> {
  if (!S.dirtyIds.length) return true;
  const ok = window.confirm('当前条目还有未保存的改动，先保存再离开？');
  if (!ok) return false;
  await save();
  return S.dirtyIds.length === 0;
}

window.addEventListener('beforeunload', (ev) => {
  if (!S.dirtyIds.length) return;
  ev.preventDefault();
  ev.returnValue = '';
});

async function renderPage(p: number) {
  if (!(await guardLeave())) return;
  setLoading(true);
  const pages = pageCount();
  p = Math.min(Math.max(1, p), pages);
  S.page = p;

  remember(pageKey(), String(p));
  const off = (p - 1) * S.pageSize;
  let rows: Entry[];

  if (S.filtered) {
    // 搜索结果已经全在手里，切片即可 —— 不再向服务端要一遍。
    rows = S.filtered.slice(off, off + S.pageSize);
  } else {
    const want = Math.min(S.pageSize, S.total - off);
    rows = await api<Entry[]>(
      `/api/entries?offset=${off}&limit=${want}`
      + `&filter=${S.filter}&lang=${encodeURIComponent(S.lang)}`);
  }

  setLoading(false);
  S.rows = rows;
  for (const e of rows) {
    if (!S.orig.has(e.id)) S.orig.set(e.id, (e[S.lang] as string) || '');
  }

  drawRows();
  updatePager();
  updateStat();
  $('rows').scrollTop = 0;      // 翻页后回到页首，不然会停在上一页的位置上
}

function drawRows() {
  clearRows();
  const frag = document.createDocumentFragment();
  for (const e of S.rows) frag.appendChild(rowOf(e));
  $('rows').appendChild(frag);
  syncScrollers();
  updatePath();
  S.activeId = null;
  if (S.rows.length) {
    markActiveInList(S.rows[0].id);
    void loadEntryInfo(S.rows[0].id);
  }
  void loadContexts(S.rows);
}

/** 只清 .row，别动 #rows 本身。 */
function clearRows() {
  for (const r of $('rows').querySelectorAll('.row')) r.remove();
}

function updatePager() {
  const pages = pageCount();
  ($('pageInput') as HTMLInputElement).value = String(S.page);
  $('pageCount').textContent = `共 ${S.total} 条`;
  ($('prev') as HTMLButtonElement).disabled = S.page <= 1;
  ($('next') as HTMLButtonElement).disabled = S.page >= pages;
  ($('first') as HTMLButtonElement).disabled = S.page <= 1;
  ($('last') as HTMLButtonElement).disabled = S.page >= pages;
}

function nextTermIssue() {
  const issues = Object.keys(S.terms);
  if (!issues.length) return;
  const bad = new Set(issues);
  const order = sideItems.map((x) => x.id);
  const cur = S.rows.length ? S.rows[0].id : '';
  const start = cur ? Math.max(0, order.indexOf(cur)) : -1;
  for (let k = 1; k <= order.length; k++) {
    const id = order[(start + k) % order.length];
    if (bad.has(id)) { void jumpToId(id); return; }
  }
}

function updateStat() {
  const n = Object.keys(S.terms).length;
  const box = $('stat');
  box.innerHTML = '';

  const plain = (text: string) => box.appendChild(el('span', 'stat-item', text));

  plain(`共 ${S.total} 条`);
  if (n) {
    const term = el('a', 'stat-item link', `术语待统一 ${n} 条`);
    term.addEventListener('click', () => nextTermIssue());
    box.appendChild(term);
  }
}
function fill(sel: HTMLElement, items: string[], cur: string) {
  sel.innerHTML = '';
  const tag = sel.tagName === 'SL-SELECT' ? 'sl-option' : 'option';
  for (const v of items) {
    const o = document.createElement(tag) as HTMLElement & { value: string };
    o.value = v;
    o.textContent = v === FOLLOW ? '（无）' : v;
    sel.appendChild(o);
  }
  (sel as HTMLElement & { value: string }).value = cur;
}

let toastTimer = 0;

function toast(msg: string) {
  const a = document.getElementById('toast') as HTMLElement & { toast?: () => void };
  if (!a) return;
  a.textContent = msg;
  if (typeof a.toast === 'function') {
    a.toast();
    return;
  }
  a.classList.add('show');
  window.setTimeout(() => a.classList.remove('show'), 1800);
}

function fillSizeSelect() {
  const sel = $('size') as HTMLSelectElement;
  const all = Array.from(new Set([...PRESET_SIZES, ...S.customSizes]))
    .sort((a, b) => a - b);
  if (!all.includes(S.size)) all.push(S.size);
  sel.innerHTML = '';
  for (const n of all.sort((a, b) => a - b)) {
    const o = document.createElement('sl-option') as HTMLElement & { value: string };
    o.value = String(n);
    o.textContent = String(n);
    sel.appendChild(o);
  }
  (sel as HTMLElement & { value: string }).value = String(S.size);
}

function saveSizePrefs() {
  remember(LS_SIZE, String(S.size));
  remember(LS_SIZES, JSON.stringify(S.customSizes));
}

function applySize() {
  document.documentElement.style.setProperty('--text-size', S.size + 'px');
}

// ── 筛选 ────────────────────────────────────────────────

function refList(): string[] {
  return [S.refA, S.refB]
    .filter((v) => v !== FOLLOW)
    .filter((v, i, a) => a.indexOf(v) === i);
}

/** 搜索走服务端：正文没全量在前端，前端过滤等于把整表拉下来再筛。 */
async function filter() {
  const q = $('q').value.trim().toLowerCase();

  if (!q) {
    await reload();
    return;
  }

  setLoading(true);
  S.loading = true;
  try {
    const found = await api<Entry[]>(
      '/api/search?q=' + encodeURIComponent(q)
      + `&filter=${S.filter}&lang=${encodeURIComponent(S.lang)}`);
    S.filtered = found;
    S.total = found.length;
    S.page = 1;
    await renderPage(1);
  } catch (err) {
    // 别再把失败咽掉：列表清空、条数不动，看着像「搜索没反应」。
    $('stat').textContent = '搜索失败：' + (err as Error).message;
  } finally {
    S.loading = false;
    setLoading(false);
  }
}

// ── 左侧条目列表 ────────────────────────────────────────

interface ListItem { id: string; en: string; zh: string; }

let sideItems: ListItem[] = [];

async function loadSideList() {
  try {
    sideItems = await api<ListItem[]>('/api/list?lang=' + encodeURIComponent(S.lang));
    drawSideList();
  } catch {
    $('list').textContent = '列表加载失败：后端版本可能过旧，重启编辑器再试。';
  }
}

function drawSideList() {
  const box = $('list');
  box.innerHTML = '';
  const frag = document.createDocumentFragment();
  sideItems.forEach((it, i) => {
    const d = el('div', 'list-item');
    d.dataset.id = it.id;
    const head = el('div', 'li-head');
    head.appendChild(el('span', 'li-no', '#' + (i + 1)));
    head.appendChild(el('span', 'li-id', it.id));
    d.appendChild(head);
    d.appendChild(el('div', 'li-text', it.en || it.zh || '（空）'));
    d.addEventListener('click', () => void jumpToId(it.id));
    frag.appendChild(d);
  });
  box.appendChild(frag);
}

function markActiveInList(id: string) {
  const box = $('list');
  for (const it of box.querySelectorAll('.list-item.active')) it.classList.remove('active');
  const cur = box.querySelector(`.list-item[data-id="${cssEsc(id)}"]`);
  if (cur) {
    cur.classList.add('active');
    cur.scrollIntoView({ block: 'nearest' });
  }
}

// ── 渲染 ────────────────────────────────────────────────

/* 一行 = id + 上下堆叠的「参照…参照 / 译文」。
 * 译文在中间：它是唯一要改的那块，放中间视线落点正好。 */
function refLine(which: 'A' | 'B', e: Entry): HTMLElement {
  const d = el('div', 'ref-block');

  const sel = el('select', 'ref-pick') as HTMLSelectElement;
  for (const code of S.refLangs) {
    const o = el('option', undefined, code) as HTMLOptionElement;
    o.value = code;
    sel.appendChild(o);
  }
  const none = el('option', undefined, '（无）') as HTMLOptionElement;
  none.value = FOLLOW;
  sel.appendChild(none);
  sel.value = which === 'A' ? S.refA : S.refB;
  sel.addEventListener('change', () => {
    if (which === 'A') { S.refA = sel.value; remember(LS_REFA, sel.value); }
    else { S.refB = sel.value; remember(LS_REFB, sel.value); }
    drawRows();
    void loadContexts(S.rows);
  });
  const head = el('div', 'ref-head');
  head.appendChild(sel);
  d.appendChild(head);

  const chosen = which === 'A' ? S.refA : S.refB;
  let cell: HTMLElement;
  if (!chosen || chosen === FOLLOW) {
    cell = el('div', 'body cell-ref', '（未选参照）');
  } else {
    const gone = !!e.missing && e.missing.indexOf(chosen) >= 0;
    cell = gone
      ? el('div', 'body cell-ref miss', '（该版本无此条）')
      : el('div', 'body cell-ref', (e[chosen] as string) || '（空）');
  }
  d.appendChild(cell);
  return d;
}

/* 一条 = 左「语境」+ 右「id/审核 + 参照 A/B + 译文」。
 * 参照语言的选择器就贴在参照文本前面，换语言不用回头顶。 */
function setEditorText(text: string) {
  const ed = zhEditor();
  if (!ed) return;
  S.suppressUndo = true;
  ed.replaceChildren(renderRich(text));
  ed.dispatchEvent(new Event('input', { bubbles: true }));
  S.suppressUndo = false;
  ed.focus();
}

function undoEdit(id: string) {
  const st = S.undo[id] || [];
  if (!st.length) return;
  const prev = st.pop() as string;
  setEditorText(prev);
  void loadEntryInfo(id);
}

async function copySeed(id: string) {
  const seed = S.seed[id];
  if (seed === undefined) return;
  const ed = zhEditor();
  const cur = ed ? editorText(ed) : '';
  if (cur) {
    const st = S.undo[id] || (S.undo[id] = []);
    st.push(cur);
    if (st.length > 20) st.shift();
  }
  setEditorText(seed);
  void loadEntryInfo(id);
}

let seedId = '';

async function editMeaning(id: string, token: string, cur: string) {
  const val = window.prompt('占位符 ' + token + ' 的含义（留空恢复自动判断）', cur);
  if (val === null) return;
  try {
    await api('/api/placeholder-meaning',
      { lang: S.lang, id, token, meaning: val.trim() });
    void loadEntryInfo(id);
  } catch (err) {
    const box = document.getElementById('infoBar');
    if (box) box.textContent = '含义保存失败：' + (err as Error).message;
  }
}

function diffNodes(a: string, b: string): DocumentFragment {
  const f = document.createDocumentFragment();
  let i = 0;
  while (i < a.length && i < b.length && a[i] === b[i]) i += 1;
  let j = 0;
  while (j < a.length - i && j < b.length - i &&
         a[a.length - 1 - j] === b[b.length - 1 - j]) j += 1;
  f.appendChild(document.createTextNode(b.slice(0, i)));
  const mark = document.createElement('mark');
  mark.textContent = b.slice(i, b.length - j);
  f.appendChild(mark);
  f.appendChild(document.createTextNode(b.slice(b.length - j)));
  return f;
}

async function openRules(id: string) {
  try {
    const r = await api<{ stages: { label: string; text: string }[] }>(
      `/api/rule-trace?lang=${encodeURIComponent(S.lang)}&id=${encodeURIComponent(id)}`);
    $('ruleModal').setAttribute('label', '规则轨迹 · ' + id);
    const box = $('ruleStages');
    box.innerHTML = '';
    let prev: string | null = null;
    for (const st of r.stages) {
      const row = el('div', 'rule-stage');
      row.appendChild(el('div', 'rule-label', st.label));
      const body = el('div', 'rule-text');
      body.appendChild(prev === null ? document.createTextNode(st.text) : diffNodes(prev, st.text));
      row.appendChild(body);
      box.appendChild(row);
      prev = st.text;
    }
    try {
      const hr = await api<{ text: string; same: boolean;
        hits: { start: number; end: number; type: string; label: string }[] }>(
        `/api/rule-hits?lang=${encodeURIComponent(S.lang)}&id=${encodeURIComponent(id)}`);
      const row = el('div', 'rule-stage');
      row.appendChild(el('div', 'rule-label',
        hr.same ? '命中标注' : '命中标注（当前译文与初版文字不同，无法标注）'));
      const body = el('div', 'rule-text');
      let pos = 0;
      for (const hit of (hr.hits || []).slice().sort((a, b) => a.start - b.start)) {
        if (hit.start < pos) continue;
        body.appendChild(document.createTextNode(hr.text.slice(pos, hit.start)));
        const mark = document.createElement('span');
        mark.className = 'hit hit-' + hit.type;
        mark.textContent = hr.text.slice(hit.start, hit.end);
        mark.title = hit.label;
        body.appendChild(mark);
        pos = hit.end;
      }
      body.appendChild(document.createTextNode(hr.text.slice(pos)));
      row.appendChild(body);
      box.appendChild(row);
    } catch { /* 标注失败不影响阶段展示 */ }
    ($('ruleModal') as any).show?.();
  } catch (err) {
    $('stat').textContent = '规则轨迹读取失败：' + (err as Error).message;
  }
}

async function openSeed(id: string) {
  try {
    const r = await api<{ text: string }>(
      `/api/seed?lang=${encodeURIComponent(S.lang)}&id=${encodeURIComponent(id)}`);
    seedId = id;
    const ta = $('seedText') as HTMLTextAreaElement;
    ta.value = r.text;
    ta.setAttribute('readonly', '');
    ($('seedSave') as HTMLButtonElement).disabled = true;
    $('seedLockInfo').textContent =
      '初版默认锁定。解锁后只能改这一条，保存或关闭后重新锁定。';
    ($('seedModal') as any).show?.();
    ta.focus();
  } catch (err) {
    $('stat').textContent = '读取初版失败：' + (err as Error).message;
  }
}

async function unlockSeed() {
  if (!window.confirm('只解锁这一条的初版，且仅本次修改有效。继续？')) return;
  const ta = $('seedText') as HTMLTextAreaElement;
  ta.removeAttribute('readonly');
  ($('seedSave') as HTMLButtonElement).disabled = false;
  $('seedLockInfo').textContent = '已解锁（仅本次修改）。保存或关闭后重新锁定。';
  ta.focus();
}

async function saveSeed() {
  try {
    const ta = $('seedText') as HTMLTextAreaElement;
    await api('/api/seed', { lang: S.lang, id: seedId, text: ta.value });
    ta.setAttribute('readonly', '');
    ($('seedSave') as HTMLButtonElement).disabled = true;
    $('seedLockInfo').textContent = '初版已保存，已重新锁定。工作文本未变。';
  } catch (err) {
    $('seedLockInfo').textContent = '保存失败：' + (err as Error).message;
  }
}

function closeSeed() {
  ($('seedModal') as any).hide?.();
  ($('seedText') as HTMLTextAreaElement).readOnly = true;
  ($('seedSave') as HTMLButtonElement).disabled = true;
}

async function setTermRule(id: string, term: string, skip: boolean) {
  try {
    await api('/api/hash-rule', { id, term, skip });
    const t = await api<{ issues: Record<string, string[]>; count: number }>(
      '/api/terms?lang=' + encodeURIComponent(S.lang));
    S.terms = t.issues || {};
    redraw(id);
    void loadEntryInfo(id);
    updateStat();
  } catch (err) {
    const box = document.getElementById('infoBar');
    if (box) box.textContent = '规则保存失败：' + (err as Error).message;
  }
}

async function loadEntryInfo(id: string) {
  const seq = ++infoSeq;
  const box = document.getElementById('infoBar');
  if (!box) return;
  try {
    const r = await api<{ placeholders: { token: string; meaning: string }[];
      tags: string[]; spaces: number[]; length: number; en_len: number }>(
      `/api/entry-info?lang=${encodeURIComponent(S.lang)}&id=${encodeURIComponent(id)}`);
    if (seq !== infoSeq || box !== document.getElementById('infoBar')) return;
    box.textContent = '';
    const ph = r.placeholders || [];
    const meaning = new Map(ph.map((p) => [p.token, p.meaning]));
    S.curMeaning = meaning;
    if (!S.meaningSaved[id] && ph.length) {
      S.meaningSaved[id] = true;
      const map: Record<string, string> = {};
      for (const p of ph) map[p.token] = p.meaning;
      void api('/api/placeholder-meanings', { lang: S.lang, id, meanings: map }).catch(() => {
        S.meaningSaved[id] = false;
      });
    }
    document.querySelectorAll('.ph-token').forEach((node) => {
      const elx = node as HTMLElement;
      const m = meaning.get(elx.dataset.token || '');
      if (!m) return;
      elx.dataset.meaning = m;
      setTokenMeaning(elx, elx.dataset.token || '', m);
    });
    const counts = r.counts || [];
    S.req[id] = {};
    for (const c of counts) S.req[id][c.token] = c.en;
    if (!counts.length) {
      box.appendChild(el('span', 'info-ph', '占位符：无'));
    }
    let badCount = 0;
    for (const c of counts) {
      const chip = el('span', 'ph-chip');
      if (c.en !== c.zh) {
        chip.classList.add('ph-bad');
        badCount += 1;
      }
      if (c.en > 1) chip.appendChild(el('span', 'ph-x', '×' + c.en));
      chip.appendChild(el('span', 'ph-tok', c.token));
      chip.appendChild(el('span', 'ph-mean',
        meaning.has(c.token) ? (meaning.get(c.token) || '（空）') : '原文没有'));
      const editMean = el('button', 'mini ph-btn', '改');
      editMean.title = '修改这个占位符在本条里的含义';
      editMean.addEventListener('click', () =>
        void editMeaning(id, c.token, meaning.get(c.token) || ''));
      chip.appendChild(editMean);
      box.appendChild(chip);
    }
    if (badCount) {
      box.appendChild(el('span', 'info-warn',
        `占位符数量不符：${badCount} 个（原文与译文必须逐个数一致）`));
    }
    let rules: { skip_terms?: string[] } = {};
    try {
      rules = (await api<{ rules: { skip_terms?: string[] } }>(
        `/api/hash-rules?id=${encodeURIComponent(id)}`)).rules || {};
    } catch { rules = {}; }
    const skipped = new Set(rules.skip_terms || []);
    for (const issue of S.terms[id] || []) {
      const term = issue.split('：应为')[0];
      if (skipped.has(term)) continue;
      const chip = el('span', 'term-chip');
      chip.appendChild(el('span', 'term-text', '术语：' + issue));
      const b = el('button', 'mini', '忽略');
      b.title = '这条不用这个术语';
      b.addEventListener('click', () => void setTermRule(id, term, true));
      chip.appendChild(b);
      box.appendChild(chip);
    }
    for (const term of skipped) {
      const chip = el('span', 'term-chip term-off');
      chip.appendChild(el('span', 'term-text', '已忽略：' + term));
      const b = el('button', 'mini', '恢复');
      b.addEventListener('click', () => void setTermRule(id, term, false));
      chip.appendChild(b);
      box.appendChild(chip);
    }

    const actions = el('span', 'info-actions');
    const ruleBtn = el('button', 'mini', '规则');
    ruleBtn.title = '查看这条译文逐阶段套用的格式化规则';
    ruleBtn.addEventListener('click', () => void openRules(id));
    actions.appendChild(ruleBtn);
    const undoBtn = el('button', 'mini', '撤销');
    undoBtn.title = '撤销上一次编辑';
    undoBtn.addEventListener('click', () => undoEdit(id));
    actions.appendChild(undoBtn);
    box.appendChild(actions);
    try {
      const sd = await api<{ text: string }>(
        `/api/seed?lang=${encodeURIComponent(S.lang)}&id=${encodeURIComponent(id)}`);
      S.seed[id] = sd.text;
      const body = document.querySelector('.seed-inline .seed-body');
      if (body) body.textContent = sd.text;
      const sb = document.querySelector('.seed-inline');
      const ed = zhEditor();
      const norm = (t: string) => t.replace(/\s+/g, '');
      if (sb && ed) sb.classList.toggle('diff', norm(ed.textContent || '') !== norm(sd.text));
    } catch {
      const body = document.querySelector('.seed-inline .seed-body');
      if (body) body.textContent = '（没有初版）';
    }

    const extraSp = r.extra_spaces || 0;
    box.appendChild(el('span', 'info-sp',
      extraSp > 0 ? `空格：多 ${extraSp} 处` : '空格：与干净文本一致'));
    if (r.tags && r.tags.length) {
      box.appendChild(el('span', 'info-tag', '标记：' + r.tags.join('、')));
    }
  } catch (err) {
    box.textContent = '提示读取失败：' + (err as Error).message;
  }
}

function zhEditor(): HTMLElement | null {
  return document.querySelector('.cell-zh .edit') as HTMLElement | null;
}

function insertAtCaret(text: string) {
  const ed = zhEditor();
  if (!ed) return;
  ed.focus();
  const sel = window.getSelection();
  if (sel && sel.rangeCount && ed.contains(sel.anchorNode)) {
    const range = sel.getRangeAt(0);
    range.deleteContents();
    range.insertNode(document.createTextNode(text));
    range.collapse(false);
    sel.removeAllRanges();
    sel.addRange(range);
  } else {
    ed.appendChild(document.createTextNode(text));
  }
  ed.dispatchEvent(new Event('input', { bubbles: true }));
}

function removeToken(tok: string) {
  const ed = zhEditor();
  if (!ed) return;
  const text = ed.textContent || '';
  ed.textContent = text.split(tok).join('');
  ed.dispatchEvent(new Event('input', { bubbles: true }));
  ed.focus();
}

function rowOf(e: Entry): HTMLElement {
  const row = el('div', 'row');
  row.dataset.id = e.id;

  // 左：语境（展开）
  const side = el('div', 'ctx-side');
  const ctx = el('div', 'ctx-inline');
  ctx.dataset.id = e.id;
  ctx.appendChild(el('div', 'ctx-head', '语境'));
  side.appendChild(ctx);

  const main = el('div', 'card-main');

  const top = el('div', 'card-top');
  top.appendChild(el('span', 'cell-no', '#' + S.page));
  top.appendChild(el('div', 'cell-id', e.id));

  main.appendChild(top);
  const info = el('div', 'info-bar');
  info.id = 'infoBar';
  main.appendChild(info);

  const compare = el('div', 'compare');

  // 左栏：初版、原文 A、原文 B；右栏：译文编辑
  const left = el('div', 'col-src');

  const seedBox = el('div', 'seed-inline ref-block');
  const seedHead = el('div', 'ref-head');
  seedHead.appendChild(el('span', 'ref-label', '初版'));
  const seedCopy = el('button', 'mini seed-edit', '复制到译文');
  seedCopy.title = '用初版覆盖编辑框（可撤销）';
  seedCopy.addEventListener('click', () => void copySeed(e.id));
  seedHead.appendChild(seedCopy);
  const seedEdit = el('button', 'mini seed-edit', '解锁编辑');
  seedEdit.title = '逐条解锁，仅本次修改有效';
  seedEdit.addEventListener('click', () => void openSeed(e.id));
  seedHead.appendChild(seedEdit);
  seedBox.appendChild(seedHead);
  const seedBody = el('div', 'seed-body', '（读取中…）');
  seedBox.appendChild(seedBody);
  left.appendChild(seedBox);

  left.appendChild(refLine('A', e));
  left.appendChild(refLine('B', e));
  compare.appendChild(left);

  const right = el('div', 'col-dst');
  const zhBlock = el('div', 'zh-block');
  zhBlock.appendChild(el('div', 'zh-head', langName(S.lang)));
  zhBlock.appendChild(zhCell(e));
  right.appendChild(zhBlock);
  compare.appendChild(right);

  main.appendChild(compare);

  const flags = el('div', 'flags');
  const ps = S.problems[e.id];
  const ts = S.terms[e.id];
  const parts = (ps || []).map((p) => p.text).concat(ts || []);
  if (parts.length) flags.textContent = parts.join('\n');
  if (ts && ts.length) flags.classList.add('term');
  main.appendChild(flags);

  const zh = textOf(e);
  if (isPlaceholder(zh)) row.classList.add('untranslated');
  if (ps && ps.some((p) => p.level === 'error')) row.classList.add('bad');

  row.appendChild(main);
  row.appendChild(side);
  return row;
}

/** 当前该显示/保存的译文：用户改过就用改动，否则用加载时的原文。 */
function textOf(e: Entry): string {
  const ed = S.edits.get(e.id);
  return ed === undefined ? ((e[S.lang] as string) || '') : ed;
}

function line(tag: string, body: HTMLElement): HTMLElement {
  const d = el('div', 'line');
  d.appendChild(el('div', 'tag', tag));
  d.appendChild(body);
  return d;
}

/* 译文格：contenteditable，空格直接渲染成带底色的 span。
 * 不再用「透明 textarea + 覆盖层」，从根上避免两层排版不一致。 */
function editorText(root: HTMLElement): string {
  let out = '';
  const walk = (node: Node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      out += node.nodeValue || '';
      return;
    }
    if (node.nodeName === 'BR') {
      out += '\n';
      return;
    }
    const elem = node as HTMLElement;
    if (elem.classList && elem.classList.contains('ph-mean-inline')) {
      return;                       // 显示用的含义，不属于正文
    }
    if (elem.classList && elem.classList.contains('hl-sp')) {
      out += elem.textContent || '';
      return;
    }
    const block = elem.nodeName === 'DIV';
    elem.childNodes.forEach(walk);
    if (block) out += '\n';
  };
  root.childNodes.forEach(walk);
  return out;
}

function caretOffset(root: HTMLElement): number {
  const sel = window.getSelection();
  if (!sel || !sel.rangeCount) return 0;
  const range = sel.getRangeAt(0).cloneRange();
  const pre = range.cloneRange();
  pre.selectNodeContents(root);
  pre.setEnd(range.endContainer, range.endOffset);
  return pre.toString().length;
}

function setCaretOffset(root: HTMLElement, offset: number) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let left = offset;
  let node = walker.nextNode();
  while (node) {
    const len = (node.nodeValue || '').length;
    if (left <= len) {
      const r = document.createRange();
      r.setStart(node, left);
      r.collapse(true);
      const sel = window.getSelection();
      if (sel) { sel.removeAllRanges(); sel.addRange(r); }
      return;
    }
    left -= len;
    node = walker.nextNode();
  }
}

function zhCell(e: Entry): HTMLElement {
  S.last[e.id] = S.last[e.id] ?? textOf(e);
  const box = el('div', 'cell-zh');
  const ed = el('div', 'edit') as HTMLDivElement;
  ed.contentEditable = 'true';
  ed.spellcheck = false;
  ed.appendChild(renderRich(textOf(e)));
  box.appendChild(ed);

  // 中文输入法组合期间不能重绘 DOM，否则会把组合中的字打断
  let composing = false;
  const record = (v: string) => {
    if (!S.suppressUndo) {
      const prev = S.last[e.id];
      if (prev !== undefined && prev !== v) {
        const st = S.undo[e.id] || (S.undo[e.id] = []);
        st.push(prev);
        if (st.length > 20) st.shift();
      }
    }
    S.last[e.id] = v;
    if (v === (S.orig.get(e.id) ?? '')) {
      S.edits.delete(e.id);
      S.dirtyIds = S.dirtyIds.filter((x) => x !== e.id);
    } else {
      S.edits.set(e.id, v);
      if (!S.dirtyIds.includes(e.id)) S.dirtyIds.push(e.id);
    }
    setDirty(S.dirtyIds.length > 0);
  };
  const repaint = () => {
    const fixed = enforceTokens(e.id, editorText(ed));
    const off = caretOffset(ed);
    ed.replaceChildren(renderRich(fixed));
    setCaretOffset(ed, off);
    record(fixed);
    const sb = document.querySelector('.seed-inline');
    if (sb) {
      const seed = S.seed[e.id];
      const norm = (t: string) => t.replace(/\s+/g, '');
      sb.classList.toggle('diff', !!seed && norm(seed) !== norm(fixed));
    }
  };

  ed.addEventListener('dragover', (ev) => ev.preventDefault());
  ed.addEventListener('drop', (ev) => {
    const dt = (ev as DragEvent).dataTransfer;
    const tok = dt ? dt.getData('text/plain') : '';
    if (!tok) return;
    ev.preventDefault();
    const span = tokenSpan(tok);
    const doc = document as Document & {
      caretRangeFromPoint?: (x: number, y: number) => Range | null;
    };
    const range = doc.caretRangeFromPoint
      ? doc.caretRangeFromPoint((ev as DragEvent).clientX, (ev as DragEvent).clientY)
      : null;
    if (range && ed.contains(range.startContainer)) {
      range.deleteContents();
      range.insertNode(span);
      range.collapse(false);
    } else {
      ed.appendChild(span);
    }
    const dragging = document.querySelector('.ph-token.dragging') as HTMLElement | null;
    if (dragging && dragging !== span) dragging.remove();
    ed.dispatchEvent(new Event('input', { bubbles: true }));
  });

  ed.addEventListener('focus', () => { void activateRow(e.id, ed); });
  ed.addEventListener('blur', () => void check(e.id));
  ed.addEventListener('compositionstart', () => { composing = true; });
  ed.addEventListener('compositionend', () => {
    composing = false;
    repaint();
  });
  ed.addEventListener('input', () => {
    if (composing) {
      record(editorText(ed));
      return;
    }
    repaint();
  });
  ed.addEventListener('keydown', (ev) => {
    const e2 = ev as KeyboardEvent;
    if (e2.key === 'Enter' && (e2.ctrlKey || e2.metaKey)) {
      e2.preventDefault();
      const row = ed.closest('.row') as HTMLElement | null;
      const next = row && row.nextElementSibling;
      const nx = next && next.querySelector('.edit') as HTMLElement | null;
      void saveOne(e.id).then(() => { if (nx) nx.focus(); });
    }
  });
  return box;
}

/** 把文本里的空格换成带底色的 span。连续多个合并，颜色略深。
 *
 *  为什么要标空格：引擎按空格切词，整串汉字会被当成一个超宽单词
 *  整条丢弃。所以「这里有空格」是判断一条译文能否显示的关键信息，
 *  肉眼看不见就必须画出来。
 *
 *  只替换 U+0020。全角空格 U+3000 不是引擎的分词符，标它会误导。
 */
function highlightSpaces(text: string): DocumentFragment {
  const f = document.createDocumentFragment();
  if (text) f.appendChild(document.createTextNode(text));
  return f;
}


const TOKEN_RX = /@[A-Za-z]\$[A-Za-z0-9_]+\$|%0?\d+[A-Za-z]?|%[A-Za-z]/g;

function tokenSpan(tok: string): HTMLElement {
  const span = el('span', 'ph-token');
  span.contentEditable = 'false';
  span.setAttribute('contenteditable', 'false');
  span.draggable = true;
  span.dataset.token = tok;
  const tokNode = el('span', 'ph-tok-node', tok);
  span.appendChild(tokNode);
  const meaning = S.curMeaning.get(tok);
  if (meaning) setTokenMeaning(span, tok, meaning);
  span.title = '拖动可换位置；占位符不能删除';
  span.addEventListener('dragstart', (ev) => {
    const dt = (ev as DragEvent).dataTransfer;
    if (dt) {
      dt.setData('text/plain', tok);
      dt.effectAllowed = 'move';
    }
    span.classList.add('dragging');
  });
  span.addEventListener('dragend', () => span.classList.remove('dragging'));
  return span;
}

function setTokenMeaning(span: HTMLElement, tok: string, meaning: string) {
  const tokNode = span.querySelector('.ph-tok-node') as HTMLElement | null;
  let mi = span.querySelector('.ph-mean-inline') as HTMLElement | null;
  if (!meaning) {
    if (mi) mi.remove();
    if (tokNode) { tokNode.classList.remove('hide'); tokNode.style.display = ''; }
    return;
  }
  if (tokNode) { tokNode.classList.add('hide'); tokNode.style.display = 'none'; }
  if (!mi) {
    mi = el('span', 'ph-mean-inline');
    mi.contentEditable = 'false';
    span.appendChild(mi);
  }
  mi.textContent = meaning;
  mi.title = tok;
}

function renderRich(text: string): DocumentFragment {
  const f = document.createDocumentFragment();
  if (!text) return f;
  let pos = 0;
  TOKEN_RX.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = TOKEN_RX.exec(text))) {
    if (m.index > pos) f.appendChild(highlightSpaces(text.slice(pos, m.index)));
    f.appendChild(tokenSpan(m[0]));
    pos = m.index + m[0].length;
  }
  if (pos < text.length) f.appendChild(highlightSpaces(text.slice(pos)));
  return f;
}

function countTokens(text: string): Record<string, number> {
  const out: Record<string, number> = {};
  TOKEN_RX.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = TOKEN_RX.exec(text))) out[m[0]] = (out[m[0]] || 0) + 1;
  return out;
}

/** 占位符只许换位置，不许少；少了就在末尾补回来。 */
function enforceTokens(id: string, text: string): string {
  const req = S.req[id] || {};
  const have = countTokens(text);
  let out = text;
  for (const tok of Object.keys(req)) {
    for (let i = have[tok] || 0; i < req[tok]; i += 1) out += tok;
  }
  return out;
}

async function loadContexts(rows: Entry[]) {
  if (!rows.length) return;
  const ids = rows.map((r) => r.id);
  try {
    const data = await api<Record<string, {
      category: string;
      placeholders: { token: string; meaning: string }[];
      neighbors: { id: string; en: string }[];
    }>>(`/api/context-batch?ids=${ids.join(',')}&lang=${encodeURIComponent(S.lang)}`);
    for (const r of rows) {
      const box = document.querySelector(
        `.ctx-inline[data-id="${cssEsc(r.id)}"]`) as HTMLElement | null;
      if (!box) continue;
      const c = data[r.id];
      if (!c) { box.textContent = ''; continue; }
      box.innerHTML = '';
      box.appendChild(el('div', 'ctx-cat', `语境：${c.category}`));
      const ph = (c.placeholders || [])
        .map((p) => `${p.token} → ${p.meaning}`).join('，');
      if (ph) box.appendChild(el('div', 'ctx-ph', `占位符：${ph}`));
      const nb = (c.neighbors || []).slice(0, 4);
      if (nb.length) {
        box.appendChild(el('div', 'ctx-nb-head', '相邻条目'));
        for (const n of nb) {
          const item = el('div', 'ctx-nb-item');
          item.appendChild(el('span', 'ctx-nb-id', n.id));
          item.appendChild(el('span', 'ctx-nb-text', n.en || '（空）'));
          box.appendChild(item);
        }
      }
    }
  } catch { /* 语境只是辅助，取不到不影响编辑 */ }
}

/** 同一时间只编辑一条：切换时把上一条自动存盘，其余行只读。 */
async function activateRow(id: string, ed: HTMLElement) {
  if (S.activeId === id) return;
  if (S.activeId) await saveOne(S.activeId);
  S.activeId = id;
  for (const t of $('rows').querySelectorAll('.edit') as NodeListOf<HTMLElement>) {
    const row = t.closest('.row') as HTMLElement | null;
    const rid = (row && row.dataset.id) || '';
    t.contentEditable = rid === id ? 'true' : 'false';
    t.classList.toggle('ro', rid !== id);
  }
  ed.contentEditable = 'true';
  ed.classList.remove('ro');
}

/** 单条存盘：只提交这一条，不碰其它行。 */
async function saveOne(id: string) {
  const text = S.edits.get(id);
  if (text === undefined) return;
  if (text === (S.orig.get(id) ?? '')) {
    S.edits.delete(id);
    S.dirtyIds = S.dirtyIds.filter((x) => x !== id);
    setDirty(S.dirtyIds.length > 0);
    return;
  }
  try {
    await api('/api/patch', { lang: S.lang, rows: [{ id, text }] });
    S.orig.set(id, text);
    S.edits.delete(id);
    S.dirtyIds = S.dirtyIds.filter((x) => x !== id);
    setDirty(S.dirtyIds.length > 0);
    void check(id);
  } catch { /* 失败就留着改动，等手动保存 */ }
}

function langName(code: string): string {
  const names: Record<string, string> = {
    zh: '中文', ja: '日本語', ko: '한국어', de: 'Deutsch', fr: 'Français', es: 'Español',
  };
  return names[code] ? `${names[code]}（${code}）` : code;
}

function isPlaceholder(t: string): boolean {
  return /^0x[0-9a-f]{8} \| /.test(t);
}

function setDirty(v: boolean) {
  $('dirty').textContent = v ? `● 有未保存的改动（${S.dirtyIds.length} 条）` : '';
  ($('save') as HTMLButtonElement).disabled = !v;
}

// ── 校验 ────────────────────────────────────────────────

async function check(id: string) {
  const e = S.rows.find((x) => x.id === id);
  if (!e) return;

  // 记下请求时的文本，回来后比对：用户可能在等结果时又改了。
  const asked = textOf(e);
  let ps: Problem[];
  try {
    ps = await api<Problem[]>('/api/check', { id, text: asked, lang: S.lang });
  } catch {
    return;                       // 校验失败不该打断编辑
  }
  if (textOf(e) !== asked) return;

  if (ps.length) S.problems[id] = ps;
  else delete S.problems[id];
  redraw(id);
}

function redraw(id: string) {
  const old = $('rows').querySelector(`.row[data-id="${cssEsc(id)}"]`);
  const src = S.rows.find((x) => x.id === id);
  if (!old || !src) return;
  const fresh = rowOf(src);
  old.replaceWith(fresh);
  void loadEntryInfo(id);
}

function cssEsc(s: string): string {
  return String(s).replace(/"/g, '\\"');
}

// ── 保存 ────────────────────────────────────────────────

async function save() {
  if (!S.dirtyIds.length) return;
  $('stat').textContent = '保存中…';
  try {
    const r = await api<{ ok: boolean; written: number; changed: number }>(
      '/api/patch', {
        lang: S.lang,
        rows: S.dirtyIds.map((id) => ({ id, text: S.edits.get(id) ?? '' })),
      });
    for (const id of S.dirtyIds) S.edits.delete(id);
    S.dirtyIds = [];
    setDirty(false);
    updateStat();
    $('stat').textContent = `已保存 ${r.changed} 处（共 ${r.written} 条）`;
  } catch (err) {
    $('stat').textContent = '保存失败：' + (err as Error).message;
  }
}

// ── 添加语言 ────────────────────────────────────────────

/** 打开「添加语言」对话框。
 *
 *  新语言是**复制**一份现成语言：条目数必须与基准表完全一致，
 *  空表在第一次保存时就会被判成"少 3548 条"，复制出来的天然是完整表。
 *  默认拿当前正在编辑的语言当模板（改一门新语言最常见的就是"接着它改"）。
 */
function openAddLang() {
  const err = $('newErr');
  err.textContent = S.dirtyIds.length
    ? `还有 ${S.dirtyIds.length} 条改动没保存 —— 先保存，再新建语言。`
    : '';

  const code = $('newCode') as HTMLInputElement;
  code.value = '';
  ($('newOk') as HTMLButtonElement).disabled = false;

  const from = $('newFrom') as HTMLSelectElement;
  fill(from, S.refLangs, S.refLangs.includes(S.lang) ? S.lang : 'en');

  $('modal').hidden = false;
  code.focus();
}

function closeAddLang() {
  $('modal').hidden = true;
}

/** 一边输入一边问服务端：这个名字能不能用、是不是已经有一份了。
 *
 *  「已存在」在界面上原本完全看不出来（下拉里只列已登记的语言），
 *  等点下去才发现就晚了 —— 而且用户会怀疑是不是被覆盖了。所以这里
 *  当场给出结论，并且把「创建」按钮直接置灰。
 */
async function refreshCodeState() {
  const code = ($('newCode') as HTMLInputElement).value.trim();
  const err = $('newErr');
  const okBtn = $('newOk') as HTMLButtonElement;

  if (!code) {
    err.textContent = '';
    okBtn.disabled = false;        // 让用户能点，看到「先填代码」的提示
    return;
  }

  try {
    const st = await api<{ ok: boolean; reason?: string }>(
      '/api/lang-exists?code=' + encodeURIComponent(code));
    err.textContent = st.ok ? '' : (st.reason || '这个名字不能用');
    okBtn.disabled = !st.ok;
  } catch {
    // 查不到就交回服务端兜底（创建那一步还会再校一次）
    okBtn.disabled = false;
  }
}

async function createLang() {
  const code = ($('newCode') as HTMLInputElement).value.trim();
  const from = ($('newFrom') as HTMLSelectElement).value;
  const err = $('newErr');
  const okBtn = $('newOk') as HTMLButtonElement;

  if (okBtn.disabled) return;      // 已经判定不能用（重名 / 只读 / 格式不对）

  if (S.dirtyIds.length) {
    err.textContent = `还有 ${S.dirtyIds.length} 条改动没保存 —— 先保存，再新建语言。`;
    return;
  }

  err.textContent = '';
  try {
    await api<{ ok: boolean; code: string; from: string }>(
      '/api/newlang', { code, from });
  } catch (e) {
    // 竞态兜底：比如另一个窗口刚好抢先建了同名文件
    err.textContent = (e as Error).message;
    void refreshCodeState();
    return;
  }

  closeAddLang();

  // 语言列表变了：下拉、模板列表都重新填，然后切到新语言、从第 1 页看起。
  const d = await api<{ editable: string[]; all: string[] }>('/api/langs');
  S.langs = d.editable;
  S.refLangs = d.all;
  S.lang = code;
  S.edits.clear();
  S.orig.clear();
  S.dirtyIds = [];
  setDirty(false);

  fill($('lang'), S.langs, code);
  await reload();
  $('stat').textContent = `已新建 ${code}（复制自 ${from}），共 ${S.total} 条待改`;
}

// ── 事件 ────────────────────────────────────────────────

let qTimer = 0;
$('q').addEventListener('input', () => {
  // 搜索要等服务端，别每个键都发一次
  clearTimeout(qTimer);
  qTimer = window.setTimeout(() => void filter(), 200);
});

// 回车＝立刻搜，不必等那 200ms 的防抖
$('q').addEventListener('keydown', (ev) => {
  if (ev.key === 'Enter') {
    ev.preventDefault();
    clearTimeout(qTimer);
    void filter();
  }
});

$('prev').addEventListener('click', () => {
  if (S.page > 1) void renderPage(S.page - 1);
});
$('next').addEventListener('click', () => {
  if (S.page < pageCount()) void renderPage(S.page + 1);
});
$('first').addEventListener('click', () => { if (S.page > 1) void renderPage(1); });
$('last').addEventListener('click', () => {
  const pages = pageCount();
  if (S.page < pages) void renderPage(pages);
});

// 翻页快捷键：焦点不在输入框/文本框/下拉里时，←/→ 翻页，Home/End 首末页。
document.addEventListener('keydown', (ev) => {
  const t = ev.target as HTMLElement | null;
  const tag = (t && t.tagName) || '';
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (t && t.isContentEditable)) {
    return;
  }
  if (ev.key === 'ArrowLeft' || ev.key === 'PageUp') {
    ev.preventDefault();
    if (S.page > 1) void renderPage(S.page - 1);
  } else if (ev.key === 'ArrowRight' || ev.key === 'PageDown') {
    ev.preventDefault();
    if (S.page < pageCount()) void renderPage(S.page + 1);
  } else if (ev.key === 'Home') {
    ev.preventDefault();
    void renderPage(1);
  } else if (ev.key === 'End') {
    ev.preventDefault();
    void renderPage(pageCount());
  }
});
$('pageInput').addEventListener('change', () => {
  const v = Number(($('pageInput') as HTMLInputElement).value);
  if (Number.isFinite(v)) void renderPage(Math.floor(v));
});

$('lang').addEventListener('sl-change', (ev) => {
  const sel = ev.target as HTMLSelectElement;
  const next = sel.value;
  void (async () => {
    if (!(await guardLeave())) {
      sel.value = S.lang;
      return;
    }
    const keepId = S.rows[0] ? S.rows[0].id : '';
    S.lang = next;
    remember(LS_LANG, S.lang);
    // 换编辑语言：重取列表与当前页，不先跳回第 1 条。
    await loadSideList();
    await reload(false);
    if (keepId && S.rows[0]?.id !== keepId) await jumpToId(keepId);
    updatePath();
  })();
});
$('size').addEventListener('sl-change', (ev) => {
  S.size = Number((ev.target as HTMLSelectElement).value);
  applySize();
  saveSizePrefs();
});

$('sizeAdd').addEventListener('click', () => {
  const val = window.prompt('输入字号（8–96，整数）', String(S.size));
  if (val === null) return;
  const n = Math.round(Number(val));
  if (!Number.isFinite(n) || n < 8 || n > 96) {
    toast('字号需在 8–96 之间');
    return;
  }
  if (!PRESET_SIZES.includes(n) && !S.customSizes.includes(n)) S.customSizes.push(n);
  S.size = n;
  fillSizeSelect();
  applySize();
  saveSizePrefs();
});

$('sizeDel').addEventListener('click', () => {
  if (PRESET_SIZES.includes(S.size)) {
    toast('预设字号不能删除');
    return;
  }
  S.customSizes = S.customSizes.filter((n) => n !== S.size);
  S.size = 14;
  fillSizeSelect();
  applySize();
  saveSizePrefs();
});
$('save').addEventListener('click', () => void save());

// 添加语言
let codeTimer = 0;
$('addLang').addEventListener('click', openAddLang);
$('newCancel').addEventListener('click', closeAddLang);
$('newOk').addEventListener('click', () => void createLang());
$('newCode').addEventListener('input', () => {
  clearTimeout(codeTimer);
  codeTimer = window.setTimeout(() => void refreshCodeState(), 250);
});
$('newCode').addEventListener('keydown', (ev) => {
  if (ev.key === 'Enter') {
    ev.preventDefault();
    void createLang();
  }
});
$('modal').addEventListener('click', (ev) => {
  if (ev.target === $('modal')) closeAddLang();     // 点遮罩＝取消
});
document.addEventListener('keydown', (ev) => {
  if (ev.key === 'Escape' && !$('modal').hidden) closeAddLang();
});

window.addEventListener('beforeunload', (ev) => {
  if (!S.dirtyIds.length) return;
  ev.preventDefault();
  ev.returnValue = '';
});

/** 供横幅等外部按钮调用：跳到某条所在页并高亮。 */
async function jumpToId(id: string): Promise<boolean> {
  const f = await api<{ index: number; count: number }>(
    '/api/find?id=' + encodeURIComponent(id));
  if (!f || f.index < 0) return false;

  await reload(true);
  const page = Math.floor(f.index / S.pageSize) + 1;
  if (page > 1) await renderPage(page);

  const row = document.querySelector(`.row[data-id="${cssEsc(id)}"]`);
  if (row) {
    row.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }
  return true;
}

async function jumpToHash(raw: string) {
  let id = raw.trim().toLowerCase();
  if (id.startsWith('0x')) id = id.slice(2);
  if (!/^[0-9a-f]{8}$/.test(id)) {
    $('stat').textContent = 'hash 格式不对：应是 0x 加 8 位十六进制';
    return;
  }
  const ok = await jumpToId('0x' + id);
  if (!ok) $('stat').textContent = '找不到 ' + '0x' + id;
}

// 编辑器习惯：Ctrl+S 保存当前条（没有活动条就整批保存）
document.addEventListener('keydown', (ev) => {
  if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 's') {
    ev.preventDefault();
    if (S.activeId) void saveOne(S.activeId); else void save();
  }
});

$('jumpGo').addEventListener('click', () => void jumpToHash($('jumpHash').value));
let jumpTimer = 0;
let jumpItems: { id: string; en: string; zh: string }[] = [];
let jumpSel = -1;

function hideJumpList() {
  $('jumpList').hidden = true;
  jumpSel = -1;
}

function drawJumpList() {
  const box = $('jumpList');
  box.innerHTML = '';
  if (!jumpItems.length) { box.hidden = true; return; }
  jumpItems.forEach((it, i) => {
    const row = el('div', 'jump-item' + (i === jumpSel ? ' sel' : ''));
    row.appendChild(el('span', 'jump-id', it.id));
    row.appendChild(el('span', 'jump-en', it.en || '（空）'));
    row.addEventListener('mousedown', (ev) => {
      ev.preventDefault();
      void jumpToHash(it.id);
      hideJumpList();
    });
    box.appendChild(row);
  });
  box.hidden = false;
}

async function suggestHashes() {
  const raw = $('jumpHash').value.trim().toLowerCase();
  const q = raw.startsWith('0x') ? raw.slice(2) : raw;
  if (q.length < 2) { jumpItems = []; hideJumpList(); return; }
  try {
    const r = await api<{ ids: { id: string; en: string; zh: string }[]; count: number }>(
      `/api/ids?q=${encodeURIComponent(q)}&lang=${encodeURIComponent(S.lang)}`);
    jumpItems = r.ids;
    jumpSel = -1;
    drawJumpList();
    if (r.count > r.ids.length) {
      $('stat').textContent = `匹配 ${r.count} 条，显示前 ${r.ids.length} 条`;
    }
  } catch { hideJumpList(); }
}

$('jumpHash').addEventListener('input', () => {
  clearTimeout(jumpTimer);
  jumpTimer = window.setTimeout(() => void suggestHashes(), 150);
});
$('jumpHash').addEventListener('blur', () => {
  window.setTimeout(hideJumpList, 150);
});
$('jumpHash').addEventListener('keydown', (ev) => {
  if (ev.key === 'ArrowDown' && jumpItems.length) {
    ev.preventDefault();
    jumpSel = (jumpSel + 1) % jumpItems.length;
    drawJumpList();
  } else if (ev.key === 'ArrowUp' && jumpItems.length) {
    ev.preventDefault();
    jumpSel = (jumpSel - 1 + jumpItems.length) % jumpItems.length;
    drawJumpList();
  } else if (ev.key === 'Enter') {
    ev.preventDefault();
    if (jumpSel >= 0 && jumpItems[jumpSel]) {
      void jumpToHash(jumpItems[jumpSel].id);
      hideJumpList();
    } else {
      void jumpToHash($('jumpHash').value);
    }
  } else if (ev.key === 'Escape') {
    hideJumpList();
  }
});

(window as any).pr2JumpTo = jumpToId;

// ── 语境推断 ────────────────────────────────────────────

async function openCtx(id: string) {
  const modal = $('ctxModal');
  const body = $('ctxBody');
  body.textContent = '正在分析…';
  modal.hidden = false;
  try {
    const c = await api<{
      id: string; category: string; reasons: string[];
      placeholders: { token: string; meaning: string }[];
      tags: string[]; en: string; zh: string;
      neighbors: { id: string; en: string; zh: string }[];
    }>(`/api/context?id=${encodeURIComponent(id)}&lang=${encodeURIComponent(S.lang)}`);

    body.innerHTML = '';
    const line = (label: string, value: string) => {
      const d = el('div', 'ctx-line');
      d.appendChild(el('span', 'ctx-label', label));
      d.appendChild(el('span', 'ctx-value', value || '（无）'));
      body.appendChild(d);
    };
    line('ID', c.id);
    line('推断用途', c.category);
    line('依据', c.reasons.join('；') || '（无）');
    if (c.placeholders.length) {
      line('占位符', c.placeholders.map((p) => `${p.token} → ${p.meaning}`).join('；'));
    }
    if (c.tags.length) line('格式标记', c.tags.join('、'));
    line('原文', c.en);
    line('当前译文', c.zh);

    if (c.neighbors.length) {
      body.appendChild(el('div', 'ctx-head', '表格中相邻的条目（同屏/同功能的可能性高）'));
      for (const n of c.neighbors) {
        const d = el('div', 'ctx-neigh');
        d.appendChild(el('span', 'ctx-id', n.id));
        d.appendChild(el('span', 'ctx-neigh-en', n.en));
        if (n.zh) d.appendChild(el('span', 'ctx-neigh-zh', n.zh));
        body.appendChild(d);
      }
    }
  } catch (err) {
    body.textContent = '读取失败：' + (err as Error).message;
  }
}

$('ruleClose').addEventListener('click', () => { ($('ruleModal') as any).hide?.(); });
$('seedUnlock').addEventListener('click', () => void unlockSeed());
$('seedSave').addEventListener('click', () => void saveSeed());
$('seedClose').addEventListener('click', closeSeed);
$('ctxClose').addEventListener('click', () => { $('ctxModal').hidden = true; });
$('ctxModal').addEventListener('click', (ev) => {
  if (ev.target === $('ctxModal')) $('ctxModal').hidden = true;
});

function showBootError(msg: string) {
  const box = document.getElementById('loading');
  if (!box) return;
  box.hidden = false;
  box.innerHTML = '';
  const text = document.createElement('div');
  text.className = 'boot-error';
  text.textContent = '载入失败：' + msg;
  const retry = document.createElement('button');
  retry.textContent = '重试';
  retry.addEventListener('click', () => location.reload());
  box.appendChild(text);
  box.appendChild(retry);
  $('stat').textContent = '载入失败：' + msg;
}

window.addEventListener('error', (ev) => showBootError(ev.message || '脚本错误'));
window.addEventListener('unhandledrejection', (ev) => {
  const r = ev.reason as Error | undefined;
  showBootError(r && r.message ? r.message : String(ev.reason));
});

boot().catch((err) => showBootError(err && err.message ? err.message : String(err)));
