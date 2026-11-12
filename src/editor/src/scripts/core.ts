// 编辑器前端的共用层：状态、DOM/请求助手、分页统计、左侧列表、字号偏好。

export let dialogsReady: Promise<unknown> | null = null;

export function ensureDialogs(): Promise<unknown> {
  if (!dialogsReady) {
    dialogsReady = Promise.all([
      import('@shoelace-style/shoelace/dist/components/dialog/dialog.js'),
      import('@shoelace-style/shoelace/dist/components/button/button.js'),
      import('@shoelace-style/shoelace/dist/components/textarea/textarea.js'),
    ]);
  }
  return dialogsReady;
}

export interface Problem {
  level: 'error' | 'warn';
  text: string;
}

export interface Entry {
  id: string;
  ctx: string;
  /** 参考语言里缺这个 id 的那些语言代码（版本差异），由服务端给出。 */
  missing?: string[];
  [lang: string]: string | string[] | undefined;
}

export const FOLLOW = '';                 // 参照下拉里的「（无）」

//: 每页固定一条：翻页就是逐条过。
export const PAGE_SIZE = 1;
//: 每页条数存在浏览器里，下次打开沿用上次的选择。
export const LS_LANG = 'pr2.lang';
export const LS_SIZE = 'pr2.size';
export const LS_SIZES = 'pr2.sizes';
export const PRESET_SIZES = [14, 16, 18, 20, 24, 28, 32, 40, 48];
export const LS_REFA = 'pr2.refA';
export const LS_REFB = 'pr2.refB';
export const LS_FILTER = 'pr2.filter';
export const LS_PAGE = 'pr2.page.';

export function saved(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}

export function remember(key: string, value: string): void {
  try { localStorage.setItem(key, value); } catch { /* 隐私模式等，忽略 */ }
}

export const S = {
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

export const $ = (id: string) => document.getElementById(id)!;

export let loadingTimer = 0;
export let loadingShown = false;

/** 载入提示：超过 120ms 才显示，避免本地快速请求闪一下。 */
export function setLoading(on: boolean) {
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

export function el(tag: string, cls?: string, text?: string): HTMLElement {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

export async function api<T>(path: string, body?: unknown): Promise<T> {
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

export function setView(view: string) {
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

export function syncScrollers() {
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

export function updatePath() {
  if (document.body.classList.contains('view-start')) return;
  const row = S.rows[0];
  const path = row ? `/translate/${S.lang}/${S.page}` : `/translate/${S.lang}`;
  if (location.pathname !== path) history.replaceState(null, '', path);
}

export function pageKey(): string {
  return LS_PAGE + S.lang + '.' + S.filter;
}

export function pageCount(): number {
  return Math.max(1, Math.ceil(S.total / S.pageSize));
}

export type JumpFn = (id: string) => void;

let jumpHook: JumpFn = () => { /* 由 app.ts 在启动时注入 */ };

/** app.ts 把“跳到某条”接进来；core 不反向 import 页面代码。 */
export function setJumpHook(fn: JumpFn): void { jumpHook = fn; }

export function nextTermIssue() {
  const issues = Object.keys(S.terms);
  if (!issues.length) return;
  const bad = new Set(issues);
  const order = sideItems.map((x) => x.id);
  const cur = S.rows.length ? S.rows[0].id : '';
  const start = cur ? Math.max(0, order.indexOf(cur)) : -1;
  for (let k = 1; k <= order.length; k++) {
    const id = order[(start + k) % order.length];
    if (bad.has(id)) { void jumpHook(id); return; }
  }
}

export function updateStat() {
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
export function clearChildren(el: HTMLElement) {
  for (const c of Array.from(el.children)) {
    if (c.parentNode === el) {
      try { el.removeChild(c); } catch { /* shoelace 可能已经接管 */ }
    }
  }
}

export function fill(sel: HTMLElement, items: string[], cur: string) {
  if (sel.tagName === 'SL-SELECT') clearChildren(sel);
  else sel.innerHTML = '';
  const tag = sel.tagName === 'SL-SELECT' ? 'sl-option' : 'option';
  for (const v of items) {
    const o = document.createElement(tag) as HTMLElement & { value: string };
    o.value = v;
    o.textContent = v === FOLLOW ? '（无）' : v;
    sel.appendChild(o);
  }
  (sel as HTMLElement & { value: string }).value = cur;
}

export let toastTimer = 0;


export function toast(msg: string) {
  const a = document.getElementById('toast') as HTMLElement & { open?: boolean };
  if (!a) return;
  a.textContent = msg;
  a.open = true;
  clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => { a.open = false; }, 1800);
}

export function fillSizeSelect() {
  const sel = $('size') as HTMLSelectElement;
  const all = Array.from(new Set([...PRESET_SIZES, ...S.customSizes]))
    .sort((a, b) => a - b);
  if (!all.includes(S.size)) all.push(S.size);
  clearChildren(sel);
  for (const n of all.sort((a, b) => a - b)) {
    const o = document.createElement('sl-option') as HTMLElement & { value: string };
    o.value = String(n);
    o.textContent = String(n);
    sel.appendChild(o);
  }
  (sel as HTMLElement & { value: string }).value = String(S.size);
}

export function saveSizePrefs() {
  remember(LS_SIZE, String(S.size));
  remember(LS_SIZES, JSON.stringify(S.customSizes));
}

export function applySize() {
  document.documentElement.style.setProperty('--text-size', S.size + 'px');
}

// ── 筛选 ────────────────────────────────────────────────

export function refList(): string[] {
  return [S.refA, S.refB]
    .filter((v) => v !== FOLLOW)
    .filter((v, i, a) => a.indexOf(v) === i);
}

export interface ListItem { id: string; en: string; zh: string; }

export let sideItems: ListItem[] = [];

export async function loadSideList() {
  try {
    sideItems = await api<ListItem[]>('/api/list?lang=' + encodeURIComponent(S.lang));
    drawSideList();
  } catch {
    $('list').textContent = '列表加载失败：后端版本可能过旧，重启编辑器再试。';
  }
}

export function drawSideList() {
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
    d.addEventListener('click', () => void jumpHook(it.id));
    frag.appendChild(d);
  });
  box.appendChild(frag);
}

export function markActiveInList(id: string) {
  const box = $('list');
  for (const it of box.querySelectorAll('.list-item.active')) it.classList.remove('active');
  const cur = box.querySelector(`.list-item[data-id="${cssEsc(id)}"]`);
  if (cur) {
    cur.classList.add('active');
    cur.scrollIntoView({ block: 'nearest' });
  }
}

export function langName(code: string): string {
  const names: Record<string, string> = {
    zh: '中文', ja: '日本語', ko: '한국어', de: 'Deutsch', fr: 'Français', es: 'Español',
  };
  return names[code] ? `${names[code]}（${code}）` : code;
}

export function isPlaceholder(t: string): boolean {
  return /^0x[0-9a-f]{8} \| /.test(t);
}

export function setDirty(v: boolean) {
  $('dirty').textContent = v ? `● 有未保存的改动（${S.dirtyIds.length} 条）` : '';
  ($('save') as HTMLButtonElement).disabled = !v;
}

export function cssEsc(s: string): string {
  return String(s).replace(/"/g, '\\"');
}
