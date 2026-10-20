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

const PAGE_SIZES = [50, 100, 200];
const DEFAULT_PAGE_SIZE = 100;

const S = {
  langs: [] as string[],
  refLangs: [] as string[],
  lang: 'zh',
  refA: 'en',
  refB: 'fr',
  //: 当前页的条目（已含服务端返回的全部语言字段）
  rows: [] as Entry[],
  page: 1,
  pageSize: DEFAULT_PAGE_SIZE,
  //: 全部条数：未搜索时是总条数，搜索时是命中数
  total: 0,
  //: 搜索结果。null 表示没在搜索，整表按 offset/limit 分页取
  filtered: null as Entry[] | null,
  //: id -> 用户改过的文本。翻页不清空，保存时按它提交。
  edits: new Map<string, string>(),
  //: id -> 加载时的原文。改回原样就把这条从"未保存"里去掉。
  orig: new Map<string, string>(),
  dirtyIds: [] as string[],
  size: 14,
  problems: {} as Record<string, Problem[]>,
  /** 术语一致性： id -> ["Frigate：应为「巡防舰」", …] */
  terms: {} as Record<string, string[]>,
  loading: false,
};

const $ = (id: string) => document.getElementById(id)!;

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

async function boot() {
  const d = await api<{ editable: string[]; all: string[]; base: string }>('/api/langs');
  S.langs = d.editable;
  S.refLangs = d.all;

  S.lang = S.langs.includes('zh') ? 'zh' : (S.langs[0] || '');
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

  fill($('lang'), S.langs, S.lang);
  fill($('refA'), S.refLangs, S.refA);
  fill($('refB'), [FOLLOW, ...S.refLangs], S.refB);
  fillPageSizes();

  applySize();
  await reload();
}

/** 重新取「一共多少条」，然后回到第 1 页。 */
async function reload() {
  const c = await api<{ count: number; ids: string[] }>('/api/count');
  S.filtered = null;
  S.total = c.count;
  S.page = 1;
  await renderPage(1);
}

function pageCount(): number {
  return Math.max(1, Math.ceil(S.total / S.pageSize));
}

/** 取第 p 页并渲染。越界会被夹回有效范围。 */
async function renderPage(p: number) {
  const pages = pageCount();
  p = Math.min(Math.max(1, p), pages);
  S.page = p;

  const off = (p - 1) * S.pageSize;
  let rows: Entry[];

  if (S.filtered) {
    // 搜索结果已经全在手里，切片即可 —— 不再向服务端要一遍。
    rows = S.filtered.slice(off, off + S.pageSize);
  } else {
    const want = Math.min(S.pageSize, S.total - off);
    rows = await api<Entry[]>(`/api/entries?offset=${off}&limit=${want}`);
  }

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
  for (const ta of $('rows').querySelectorAll('textarea')) grow(ta);
}

/** 只清 .row，别动 #rows 本身。 */
function clearRows() {
  for (const r of $('rows').querySelectorAll('.row')) r.remove();
}

function updatePager() {
  const pages = pageCount();
  ($('pageInput') as HTMLInputElement).value = String(S.page);
  $('pageCount').textContent = '/ ' + pages;
  ($('prev') as HTMLButtonElement).disabled = S.page <= 1;
  ($('next') as HTMLButtonElement).disabled = S.page >= pages;
}

function updateStat() {
  const pages = pageCount();
  const n = Object.keys(S.terms).length;
  $('stat').textContent = `第 ${S.page} / ${pages} 页 · 共 ${S.total} 条`
    + (n ? ` · 术语待统一 ${n} 条` : '');
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

function fillPageSizes() {
  const sel = $('pageSize') as HTMLSelectElement;
  sel.innerHTML = '';
  for (const n of PAGE_SIZES) {
    const o = el('option', undefined, String(n));
    (o as HTMLOptionElement).value = String(n);
    sel.appendChild(o);
  }
  sel.value = String(S.pageSize);
}

function applySize() {
  document.body.style.fontSize = S.size + 'px';
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

  S.loading = true;
  try {
    const found = await api<Entry[]>('/api/search?q=' + encodeURIComponent(q));
    S.filtered = found;
    S.total = found.length;
    S.page = 1;
    await renderPage(1);
  } catch (err) {
    // 别再把失败咽掉：列表清空、条数不动，看着像「搜索没反应」。
    $('stat').textContent = '搜索失败：' + (err as Error).message;
  } finally {
    S.loading = false;
  }
}

// ── 渲染 ────────────────────────────────────────────────

/* 一行 = id + 上下堆叠的「参照…参照 / 译文」。
 * 译文在中间：它是唯一要改的那块，放中间视线落点正好。 */
function rowOf(e: Entry): HTMLElement {
  const row = el('div', 'row');
  row.dataset.id = e.id;

  row.appendChild(el('div', 'cell-id', e.id));

  const stack = el('div', 'stack');

  const refs = refList();
  if (!refs.length) {
    stack.appendChild(line('参照', el('div', 'body cell-ref', '（未选参照）')));
  } else {
    for (const k of refs) {
      // 这一版原版表里没有这个 id：明确标出来，别让它和「空字符串」混为一谈。
      const gone = !!e.missing && e.missing.indexOf(k) >= 0;
      const cell = gone
        ? el('div', 'body cell-ref miss', '（该版本无此条）')
        : el('div', 'body cell-ref', (e[k] as string) || '（空）');
      stack.appendChild(line(k, cell));
    }
  }

  stack.appendChild(line(S.lang, zhCell(e)));
  row.appendChild(stack);

  const flags = el('div', 'flags');
  const ps = S.problems[e.id];
  const ts = S.terms[e.id];
  const parts = (ps || []).map((p) => p.text).concat(ts || []);
  if (parts.length) flags.textContent = parts.join('\n');
  if (ts && ts.length) flags.classList.add('term');
  row.appendChild(flags);

  const zh = textOf(e);
  if (isPlaceholder(zh)) row.classList.add('untranslated');
  if (ps && ps.some((p) => p.level === 'error')) row.classList.add('bad');

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

/* 译文格 = 高亮层（垫在下面）+ textarea（透明在上面）。 */
function zhCell(e: Entry): HTMLElement {
  const box = el('div', 'cell-zh');
  const text = textOf(e);

  const layer = el('div', 'sp-layer');
  layer.appendChild(highlightSpaces(text));
  box.appendChild(layer);

  const ta = document.createElement('textarea');
  ta.value = text;
  ta.spellcheck = false;
  box.appendChild(ta);

  ta.addEventListener('input', () => {
    const v = ta.value;
    layer.replaceChildren(highlightSpaces(v));
    grow(ta);
    if (v === (S.orig.get(e.id) ?? '')) {
      // 改回原样：不用再提交这一条
      S.edits.delete(e.id);
      S.dirtyIds = S.dirtyIds.filter((x) => x !== e.id);
    } else {
      S.edits.set(e.id, v);
      if (!S.dirtyIds.includes(e.id)) S.dirtyIds.push(e.id);
    }
    setDirty(S.dirtyIds.length > 0);
  });
  ta.addEventListener('blur', () => void check(e.id));
  ta.addEventListener('keydown', (ev) => {
    // Ctrl+Enter：去下一条 —— 翻译时最常用的动作（页内最后一条就停）
    const e2 = ev as KeyboardEvent;
    if (e2.key === 'Enter' && (e2.ctrlKey || e2.metaKey)) {
      e2.preventDefault();
      const row = ta.closest('.row') as HTMLElement | null;
      const next = row && row.nextElementSibling;
      const nx = next && next.querySelector('textarea');
      if (nx) nx.focus();
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

function isPlaceholder(t: string): boolean {
  return /^0x[0-9a-f]{8} \| /.test(t);
}

function grow(ta: HTMLTextAreaElement) {
  ta.style.height = 'auto';
  void ta.offsetWidth;          // 强制回流，让 scrollHeight 变成真值
  ta.style.height = (ta.scrollHeight + 2) + 'px';
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
  const ta = fresh.querySelector('textarea');
  if (ta) grow(ta);
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
  fill($('refB'), [FOLLOW, ...S.refLangs], S.refB);
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
$('pageInput').addEventListener('change', () => {
  const v = Number(($('pageInput') as HTMLInputElement).value);
  if (Number.isFinite(v)) void renderPage(Math.floor(v));
});
$('pageSize').addEventListener('change', () => {
  S.pageSize = Number(($('pageSize') as HTMLSelectElement).value) || DEFAULT_PAGE_SIZE;
  void renderPage(1);
});

$('lang').addEventListener('change', (ev) => {
  S.lang = (ev.target as HTMLSelectElement).value;
  // 换编辑语言等于换了一列数据：把当前页重画，改动仍按 id 留在 edits 里。
  void renderPage(S.page);
});
$('refA').addEventListener('change', (ev) => {
  S.refA = (ev.target as HTMLSelectElement).value;
  drawRows();
});
$('refB').addEventListener('change', (ev) => {
  S.refB = (ev.target as HTMLSelectElement).value;
  drawRows();
});
$('size').addEventListener('change', (ev) => {
  S.size = Number((ev.target as HTMLSelectElement).value);
  applySize();
  for (const ta of $('rows').querySelectorAll('textarea')) grow(ta);
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

boot().catch((err) => {
  $('stat').textContent = '载入失败：' + err.message;
});
