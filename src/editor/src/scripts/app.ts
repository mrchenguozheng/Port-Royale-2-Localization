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
//   POST /api/check         -> [{level, text}]
//   POST /api/save          -> {ok, written}

interface Problem {
  level: 'error' | 'warn';
  text: string;
}

interface Entry {
  id: string;
  ctx: string;
  [lang: string]: string;
}

const FOLLOW = '';                 // 参照下拉里的「（无）」

//: 一批渲染多少条。60 条大约铺满两屏 —— 够滚动条连续，又不至于一次
//: 建太多节点（每条要建 3 行 + 一个 textarea + 空格高亮层）。
const CHUNK = 60;

//: 还没加载的条目，先用这个高度撑出滚动条。没有它的话滚动条只反映
//: 已加载的那几十条，滚到底就「到底了」，而实际还有三千多条没显示。
//: 估不准不要紧：滚到接近底部时会用真实高度替换掉它。
const EST_ROW_H = 92;

const S = {
  langs: [] as string[],
  refLangs: [] as string[],
  lang: 'zh',
  refA: 'en',
  refB: 'fr',
  all: [] as Entry[],          // 已取回正文的条目（按需，可能不连续）
  loaded: 0,                   // 已经渲染到第几条
  total: 0,                    // 筛选后的总条数
  size: 14,
  dirty: false,
  dirtyIds: [] as string[],     // 改过的 id，保存时只提交这些
  problems: {} as Record<string, Problem[]>,
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
  const d = await api<{ editable: string[]; all: string[] }>('/api/langs');
  S.langs = d.editable;
  S.refLangs = d.all;

  S.lang = S.langs.includes('zh') ? 'zh' : (S.langs[0] || '');
  S.refA = 'en';
  S.refB = S.refLangs.includes('fr') ? 'fr' : FOLLOW;

  fill($('lang'), S.langs, S.lang);
  fill($('refA'), S.refLangs, S.refA);
  fill($('refB'), [FOLLOW, ...S.refLangs], S.refB);

  const c = await api<{ count: number; ids: string[] }>('/api/count');
  S.total = c.count;

  applySize();
  await loadMore();          // 只取第一屏
  watchBottom();
}

/** 清掉已渲染的条目，但**保留 #tail**。
 *
 *  ⛔ 别用 main.innerHTML = ''：#tail 是 main 的子节点（滚动条占位 +
 *  IntersectionObserver 的探测点），一起清掉的话 observer 就再也
 *  观测不到它，分段加载会永远停在这一批 —— 表现为「往下滚没反应」。
 *  所以只删 .row。
 */
function clearRows() {
  for (const r of $('rows').querySelectorAll('.row')) r.remove();
}

/** 取下一批正文并追加到 DOM。滚动条到底附近时由 observer 触发。 */
async function loadMore() {
  if (S.loading || S.loaded >= S.total) return;
  S.loading = true;
  const off = S.loaded;
  const want = Math.min(CHUNK, S.total - off);

  let rows: Entry[];
  try {
    rows = await api<Entry[]>(`/api/entries?offset=${off}&limit=${want}`);
  } catch (err) {
    $('stat').textContent = '载入失败：' + (err as Error).message;
    S.loading = false;
    return;
  }

  const main = $('rows');
  const frag = document.createDocumentFragment();
  for (const e of rows) {
    S.all.push(e);
    frag.appendChild(rowOf(e));
  }
  main.insertBefore(frag, $('tail'));

  // 先记账再更新占位：updateTail 用 S.loaded 算「还剩多少」，
  // 顺序反了的话占位会按旧计数算，最后一批永远收不掉。
  S.loaded += rows.length;

  for (const ta of main.querySelectorAll('textarea')) grow(ta);
  updateTail();
  updateStat();

  S.loading = false;
}

/** 底部占位块：既是滚动条的真实长度，也是「快到底了」的探测点。 */
function updateTail() {
  const left = S.total - S.loaded;
  const tail = $('tail');
  if (left <= 0) {
    tail.style.display = 'none';
    tail.textContent = '';
    return;
  }
  tail.style.display = 'flex';
  tail.style.height = (left * EST_ROW_H) + 'px';
  tail.textContent = '往下滚加载其余 ' + left + ' 条';
}

function watchBottom() {
  const io = new IntersectionObserver((es) => {
    if (es.some((e) => e.isIntersecting)) void loadMore();
  }, { rootMargin: '400px' });          // 提前 400px 开始，别等用户看到空
  io.observe($('tail'));
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
  document.body.style.fontSize = S.size + 'px';
}

// ── 筛选 ────────────────────────────────────────────────

function refList(): string[] {
  return [S.refA, S.refB]
    .filter((v) => v !== FOLLOW)
    .filter((v, i, a) => a.indexOf(v) === i);
}

/** 搜索走服务端：正文本来就没在前端，一次拉全量等于把分段的意义抹掉。 */
async function filter() {
  const q = $('q').value.trim().toLowerCase();
  clearRows();                 // 只清 .row，#tail 要留着
  S.all = [];
  S.loaded = 0;

  if (!q) {
    const c = await api<{ count: number; ids: string[] }>('/api/count');
    S.total = c.count;
    await loadMore();
  } else {
    const found = await api<Entry[]>('/api/search?q=' + encodeURIComponent(q));
    S.total = found.length;
    // 搜索命中数一般很少，一次全渲染即可，不再分段。
    S.all = found;
    S.loaded = found.length;
    const frag = document.createDocumentFragment();
    for (const e of found) frag.appendChild(rowOf(e));
    $('rows').insertBefore(frag, $('tail'));
    for (const ta of $('rows').querySelectorAll('textarea')) grow(ta);
  }
  updateTail();
  updateStat();
}

function updateStat() {
  const q = $('q').value.trim();
  $('stat').textContent = q
    ? `${S.loaded} / ${S.total} 条`
    : (S.total > S.loaded ? `${S.loaded} / ${S.total} 条` : `${S.total} 条`);
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
      stack.appendChild(line(k, el('div', 'body cell-ref', e[k] || '（空）')));
    }
  }

  stack.appendChild(line(S.lang, zhCell(e)));
  row.appendChild(stack);

  const flags = el('div', 'flags');
  const ps = S.problems[e.id];
  if (ps && ps.length) flags.textContent = ps.map((p) => p.text).join('\n');
  row.appendChild(flags);

  const zh = e[S.lang] || '';
  if (isPlaceholder(zh)) row.classList.add('untranslated');
  if (ps && ps.some((p) => p.level === 'error')) row.classList.add('bad');

  return row;
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
  const text = e[S.lang] || '';

  const layer = el('div', 'sp-layer');
  layer.appendChild(highlightSpaces(text));
  box.appendChild(layer);

  const ta = document.createElement('textarea');
  ta.value = text;
  ta.spellcheck = false;
  box.appendChild(ta);

  ta.addEventListener('input', () => {
    e[S.lang] = ta.value;
    layer.replaceChildren(highlightSpaces(ta.value));
    grow(ta);
    // 记下改过的 id：分段加载下前端只见过这些，
    // 保存时也只提交这些，后端把其余的保持原样。
    if (!S.dirtyIds.includes(e.id)) S.dirtyIds.push(e.id);
    setDirty(true);
  });
  ta.addEventListener('blur', () => void check(e.id));
  ta.addEventListener('keydown', (ev) => {
    // Ctrl+Enter：去下一条 —— 翻译时最常用的动作
    const e2 = ev as KeyboardEvent;
    if (e2.key === 'Enter' && (e2.ctrlKey || e2.metaKey)) {
      e2.preventDefault();
      const row = ta.closest('.row') as HTMLElement | null;
      // 还没加载到下一条就先补一批，否则跳不过去
      const next = row && row.nextElementSibling;
      const nx = next && next.querySelector('textarea');
      if (nx) nx.focus();
      else { void loadMore().then(() => focusNextAfter(row)); }
    }
  });

  return box;
}

function focusNextAfter(row: HTMLElement | null) {
  if (!row || !row.parentElement) return;
  const nxt = row.nextElementSibling;
  const t = nxt && nxt.querySelector('textarea');
  if (t) t.focus();
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
  S.dirty = v;
  if (!v) S.dirtyIds = [];
  $('dirty').textContent = v ? `● 有未保存的改动（${S.dirtyIds.length} 条）` : '';
  ($('save') as HTMLButtonElement).disabled = !v;
}

// ── 校验 ────────────────────────────────────────────────

async function check(id: string) {
  const e = S.all.find((x) => x.id === id);
  if (!e) return;

  // 记下请求时的文本，回来后比对：用户可能在等结果时又改了。
  const asked = e[S.lang] || '';
  let ps: Problem[];
  try {
    ps = await api<Problem[]>('/api/check', { id, text: asked, lang: S.lang });
  } catch {
    return;                       // 校验失败不该打断编辑
  }
  if ((e[S.lang] || '') !== asked) return;

  if (ps.length) S.problems[id] = ps;
  else delete S.problems[id];
  redraw(id);
}

function redraw(id: string) {
  const old = $('rows').querySelector(`.row[data-id="${cssEsc(id)}"]`);
  const src = S.all.find((x) => x.id === id);
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
// 分段加载之后前端只见过几十条，所以**只提交改动过的**，
// 其余由后端从现有文件原样保留。走 /api/patch 而不是 /api/save：
// 后者要求「条目数与顺序与基准完全一致」，而前端拿不出全部。

async function save() {
  if (!S.dirty) return;
  $('stat').textContent = '保存中…';
  try {
    const r = await api<{ ok: boolean; written: number; changed: number }>(
      '/api/patch', {
        lang: S.lang,
        rows: S.dirtyIds.map((id) => ({
          id,
          text: S.all.find((e) => e.id === id)?.[S.lang] ?? '',
        })),
      });
    setDirty(false);
    updateStat();
    $('stat').textContent = `已保存 ${r.changed} 处（共 ${r.written} 条）`;
  } catch (err) {
    $('stat').textContent = '保存失败：' + (err as Error).message;
  }
}

// ── 事件 ────────────────────────────────────────────────

let qTimer = 0;
$('q').addEventListener('input', () => {
  // 搜索要等服务端，别每个键都发一次
  clearTimeout(qTimer);
  qTimer = window.setTimeout(() => void filter(), 200);
});

$('lang').addEventListener('change', (ev) => {
  S.lang = (ev.target as HTMLSelectElement).value;
  renderLoaded();
});
$('refA').addEventListener('change', (ev) => {
  S.refA = (ev.target as HTMLSelectElement).value;
  renderLoaded();
});
$('refB').addEventListener('change', (ev) => {
  S.refB = (ev.target as HTMLSelectElement).value;
  renderLoaded();
});
$('size').addEventListener('change', (ev) => {
  S.size = Number((ev.target as HTMLSelectElement).value);
  applySize();
  for (const ta of $('rows').querySelectorAll('textarea')) grow(ta);
});
$('save').addEventListener('click', () => void save());

/** 只重画已经加载的条目（换参照语言时用），不重新取数据。 */
function renderLoaded() {
  clearRows();
  const frag = document.createDocumentFragment();
  for (const e of S.all) frag.appendChild(rowOf(e));
  $('rows').insertBefore(frag, $('tail'));
  for (const ta of $('rows').querySelectorAll('textarea')) grow(ta);
}

window.addEventListener('beforeunload', (ev) => {
  if (!S.dirty) return;
  ev.preventDefault();
  ev.returnValue = '';
});

boot().catch((err) => {
  $('stat').textContent = '载入失败：' + err.message;
});
