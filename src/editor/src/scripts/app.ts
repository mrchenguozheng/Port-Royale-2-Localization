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
  dirtyIds: [] as string[],
  size: 24,
  problems: {} as Record<string, Problem[]>,
  /** 术语一致性： id -> ["Frigate：应为「巡防舰」", …] */
  terms: {} as Record<string, string[]>,
  /** 人工审核勾选：当前语言已勾选的 id 集合 */
  reviewed: new Set<string>(),
  reviewedCount: 0,
  /** 当前正在编辑的那一条（同一时间只允许一条） */
  activeId: null as string | null,
  loading: false,
};

const $ = (id: string) => document.getElementById(id)!;

function initTabs() {
  for (const t of document.querySelectorAll('.tab')) {
    t.addEventListener('click', () => setView((t as HTMLElement).dataset.view || 'editor'));
  }
  setView(location.hash === '#start' ? 'start' : 'editor');
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
    if (loadingShown) {
      const b = box();
      if (b) b.hidden = true;
      loadingShown = false;
    }
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
  const panel = document.getElementById('view-start');
  const ws = document.querySelector('.workspace') as HTMLElement | null;
  const sb = document.querySelector('.statusbar') as HTMLElement | null;
  if (panel) panel.hidden = !start;
  if (ws) ws.hidden = start;
  if (sb) sb.hidden = start;
  document.body.classList.toggle('view-start', start);
  for (const t of document.querySelectorAll('.tab')) {
    t.classList.toggle('active', (t as HTMLElement).dataset.view === view);
  }
  const hash = start ? '#start' : location.pathname;
  history.replaceState(null, '', hash);
}

async function boot() {
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

  const savedFilter = saved(LS_FILTER);
  if (savedFilter && ['all', 'unreviewed', 'reviewed', 'attention'].includes(savedFilter)) {
    S.filter = savedFilter;
  }
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

  try {
    const f = await api<{ ids: string[]; count: number }>(
      '/api/review-flags?lang=' + encodeURIComponent(S.lang));
    S.reviewed = new Set(f.ids || []);
    S.reviewedCount = f.count || 0;
  } catch { S.reviewed = new Set(); S.reviewedCount = 0; }

  initTabs();
  fill($('lang'), S.langs, S.lang);
  await loadSideList();

  applySize();
  await reload(true);
  setLoading(false);
  const sp = Number(saved(pageKey()));
  if (sp > 1) await renderPage(sp);
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
async function renderPage(p: number) {
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
  S.activeId = null;
  if (S.rows.length) markActiveInList(S.rows[0].id);
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
  const reviewed = Math.min(S.reviewedCount, S.total);
  const pending = Math.max(0, S.total - reviewed);
  const box = $('stat');
  box.innerHTML = '';

  const plain = (text: string) => box.appendChild(el('span', 'stat-item', text));

  plain(`已审 ${reviewed} 条`);
  const todo = el('a', 'stat-item link', `待审 ${pending} 条`);
  todo.addEventListener('click', () => void nextUnreviewed());
  box.appendChild(todo);
  plain(`共 ${S.total} 条`);
  if (n) {
    const term = el('a', 'stat-item link', `术语待统一 ${n} 条`);
    term.addEventListener('click', () => nextTermIssue());
    box.appendChild(term);
  }
}
function fill(sel: HTMLSelectElement, items: string[], cur: string) {
  sel.innerHTML = '';
  for (const v of items) {
    const o = el('option', undefined, v === FOLLOW ? '（无）' : v);
    (o as HTMLOptionElement).value = v;
    sel.appendChild(o);
  }
  sel.value = cur;
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

interface ListItem { id: string; en: string; zh: string; reviewed: boolean; }

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
    const d = el('div', 'list-item' + (it.reviewed ? ' done' : ''));
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

  const wrap = el('label', 'chk-wrap');
  const box = el('input', 'chk') as HTMLInputElement;
  box.type = 'checkbox';
  box.checked = S.reviewed.has(e.id);
  box.setAttribute('aria-label', '标记这条已审核');
  const lab = el('span', 'chk-label', box.checked ? '已审' : '待审');
  box.addEventListener('change', async () => {
    try {
      const r = await api<{ count: number }>('/api/review-flags',
        { lang: S.lang, id: e.id, on: box.checked });
      S.reviewedCount = r.count;
    } catch {
      box.checked = !box.checked;
      return;
    }
    if (box.checked) S.reviewed.add(e.id); else S.reviewed.delete(e.id);
    lab.textContent = box.checked ? '已审' : '待审';
    row.classList.toggle('reviewed', box.checked);
    const li = $('list').querySelector(`.list-item[data-id="${cssEsc(e.id)}"]`);
    if (li) li.classList.toggle('done', box.checked);
    updateStat();
  });
  wrap.appendChild(box);
  wrap.appendChild(lab);
  top.appendChild(wrap);
  main.appendChild(top);
  if (box.checked) row.classList.add('reviewed');

  const compare = el('div', 'compare');
  const src = el('div', 'col-src');
  src.appendChild(refLine('A', e));
  src.appendChild(refLine('B', e));
  compare.appendChild(src);

  const dst = el('div', 'col-dst');
  const zhBlock = el('div', 'zh-block');
  zhBlock.appendChild(el('div', 'zh-head', langName(S.lang)));
  zhBlock.appendChild(zhCell(e));
  dst.appendChild(zhBlock);
  compare.appendChild(dst);
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
  const box = el('div', 'cell-zh');
  const ed = el('div', 'edit') as HTMLDivElement;
  ed.contentEditable = 'true';
  ed.spellcheck = false;
  ed.appendChild(highlightSpaces(textOf(e)));
  box.appendChild(ed);

  // 中文输入法组合期间不能重绘 DOM，否则会把组合中的字打断
  let composing = false;
  const record = (v: string) => {
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
    const v = editorText(ed);
    const off = caretOffset(ed);
    ed.replaceChildren(highlightSpaces(v));
    setCaretOffset(ed, off);
    record(v);
  };

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
  if (!text) return f;

  let buf = '';
  let run = false;
  const flush = () => {
    if (run) { f.appendChild(el('span', 'hl-sp run', buf)); buf = ''; run = false; }
  };

  for (const ch of text) {
    if (ch === ' ') { buf += ch; run = true; }   // 连续合并，避免上百个节点
    else { flush(); f.appendChild(document.createTextNode(ch)); }
  }
  flush();
  return f;
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

$('lang').addEventListener('change', (ev) => {
  S.lang = (ev.target as HTMLSelectElement).value;
  remember(LS_LANG, S.lang);
  // 换编辑语言等于换了一列数据：审核勾选也要换一份，再把当前页重画。
  void (async () => {
    try {
      const f = await api<{ ids: string[]; count: number }>(
        '/api/review-flags?lang=' + encodeURIComponent(S.lang));
      S.reviewed = new Set(f.ids || []);
      S.reviewedCount = f.count || 0;
    } catch { S.reviewed = new Set(); S.reviewedCount = 0; }
    await loadSideList();
    await reload(true);
    const sp = Number(saved(pageKey()));
    if (sp > 1) await renderPage(sp);
  })();
});
$('size').addEventListener('change', (ev) => {
  S.size = Number((ev.target as HTMLSelectElement).value);
  applySize();
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
    row.classList.add('flash');
    row.scrollIntoView({ block: 'center', behavior: 'smooth' });
    window.setTimeout(() => row.classList.remove('flash'), 2500);
  }
  return true;
}

async function unreviewedIds(): Promise<string[]> {
  const c = await api<{ ids: string[] }>(
    `/api/count?filter=unreviewed&lang=${encodeURIComponent(S.lang)}`);
  return c.ids || [];
}

let randomBusy = false;

async function randomUnreviewed() {
  if (randomBusy) return;
  randomBusy = true;
  const btn = $('randomUnrev') as HTMLButtonElement;
  if (btn) btn.disabled = true;
  try {
    const ids = await unreviewedIds();
    if (!ids.length) { $('stat').textContent = '没有未审核的条目了'; return; }
    await jumpToId(ids[Math.floor(Math.random() * ids.length)]);
  } catch (err) {
    $('stat').textContent = '随机跳转失败：' + (err as Error).message;
  } finally {
    window.setTimeout(() => {
      randomBusy = false;
      if (btn) btn.disabled = false;
    }, 400);
  }
}

async function prevUnreviewed() {
  try {
    const ids = await unreviewedIds();
    if (!ids.length) { $('stat').textContent = '没有未审核的条目了'; return; }
    const cur = S.rows.length ? S.rows[0].id : '';
    const i = cur ? ids.indexOf(cur) : 0;
    await jumpToId(ids[(i - 1 + ids.length) % ids.length]);
  } catch (err) {
    $('stat').textContent = '跳转失败：' + (err as Error).message;
  }
}

async function nextUnreviewed() {
  try {
    const ids = await unreviewedIds();
    if (!ids.length) { $('stat').textContent = '没有未审核的条目了'; return; }
    const cur = S.rows.length ? S.rows[0].id : '';
    const i = cur ? ids.indexOf(cur) : -1;
    await jumpToId(ids[(i + 1) % ids.length]);
  } catch (err) {
    $('stat').textContent = '跳转失败：' + (err as Error).message;
  }
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

$('randomUnrev').addEventListener('click', () => void randomUnreviewed());
$('prevUnrev').addEventListener('click', () => void prevUnreviewed());
$('nextUnrev').addEventListener('click', () => void nextUnreviewed());
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
      tags: string[]; en: string; zh: string; reviewed: boolean;
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
    line('审核', c.reviewed ? '已勾选' : '未勾选');

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
