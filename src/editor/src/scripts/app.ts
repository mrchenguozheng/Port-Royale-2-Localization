import '@shoelace-style/shoelace/dist/themes/light.css';
import '@shoelace-style/shoelace/dist/components/select/select.js';
import '@shoelace-style/shoelace/dist/components/option/option.js';
import '@shoelace-style/shoelace/dist/components/alert/alert.js';

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
import {
  S, $, el, api, saved, remember, setLoading, toast, fill, fillSizeSelect,
  saveSizePrefs, applySize, pageKey, pageCount, updatePath, updateStat, setDirty,
  cssEsc, loadSideList, setView, setJumpHook, FOLLOW, PRESET_SIZES,
  LS_LANG, LS_REFA, LS_REFB, LS_SIZE, LS_SIZES, Entry,
} from './core';
import { drawRows, saveOne, unlockSaved, saveSaved, closeSaved } from './rows';

export function initTabs() {
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

export async function boot() {
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

  // 先算目标页，再一次性加载：避免「先到第 1 条、再跳目标」的中间态。
  let targetPage = 0;
  const mHash = initialPath.match(/^\/translate\/[A-Za-z][A-Za-z-]*\/(?:0x)?([0-9a-f]{8})$/i);
  const mNum = initialPath.match(/^\/translate\/[A-Za-z][A-Za-z-]*\/(\d+)$/);
  if (mHash) {
    try {
      const f = await api<{ index: number }>(
        '/api/find?id=' + encodeURIComponent('0x' + mHash[1].toLowerCase()));
      if (f && f.index >= 0) targetPage = Math.floor(f.index / S.pageSize) + 1;
    } catch { /* 找不到就按第 1 页 */ }
  } else if (mNum) {
    targetPage = Number(mNum[1]);
  }

  if (targetPage > 0) {
    S.page = targetPage;
    await reload(false);           // 保持目标页，不重置
  } else {
    await reload(true);
    const sp = Number(saved(pageKey()));
    if (sp > 1) await renderPage(sp);
  }
  setLoading(false);
  updatePath();
}

export async function reload(resetPage = true) {
  const c = await api<{ count: number; ids: string[] }>(
    `/api/count?filter=${S.filter}&lang=${encodeURIComponent(S.lang)}`);
  S.filtered = null;
  S.total = c.count;
  if (resetPage) S.page = 1;
  await renderPage(S.page);
}

/** 取第 p 页并渲染。越界会被夹回有效范围。 */
export async function guardLeave(): Promise<boolean> {
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

export async function renderPage(p: number) {
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

export function updatePager() {
  const pages = pageCount();
  ($('pageInput') as HTMLInputElement).value = String(S.page);
  $('pageCount').textContent = `共 ${S.total} 条`;
  ($('prev') as HTMLButtonElement).disabled = S.page <= 1;
  ($('next') as HTMLButtonElement).disabled = S.page >= pages;
  ($('first') as HTMLButtonElement).disabled = S.page <= 1;
  ($('last') as HTMLButtonElement).disabled = S.page >= pages;
}

export async function filter() {
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
    toast('搜索失败：' + (err as Error).message);
  } finally {
    S.loading = false;
    setLoading(false);
  }
}

// ── 保存 ────────────────────────────────────────────────

export async function save() {
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
    toast('保存失败：' + (err as Error).message);
  }
}

// ── 添加语言 ────────────────────────────────────────────

/** 打开「添加语言」对话框。
 *
 *  新语言是**复制**一份现成语言：条目数必须与基准表完全一致，
 *  空表在第一次保存时就会被判成"少 3548 条"，复制出来的天然是完整表。
 *  默认拿当前正在编辑的语言当模板（改一门新语言最常见的就是"接着它改"）。
 */
export function openAddLang() {
  const err = $('newErr');
  err.textContent = S.dirtyIds.length
    ? `还有 ${S.dirtyIds.length} 条改动没保存 —— 先保存，再新建语言。`
    : '';

  const code = $('newCode') as HTMLInputElement;
  code.value = '';
  ($('newOk') as HTMLButtonElement).disabled = false;

  const from = $('newFrom') as HTMLSelectElement;
  // 默认模板必须存在且与基准表对齐；fr 这类条数不一致的会在服务端被拒绝。
  const def = S.refLangs.includes(S.lang)
    ? S.lang
    : (S.refLangs.includes(S.refA) ? S.refA
      : (S.refLangs.find((x) => x.startsWith('en')) || S.refLangs[0] || ''));
  fill(from, S.refLangs, def);

  $('modal').hidden = false;
  code.focus();
}

export function closeAddLang() {
  $('modal').hidden = true;
}

/** 一边输入一边问服务端：这个名字能不能用、是不是已经有一份了。
 *
 *  「已存在」在界面上原本完全看不出来（下拉里只列已登记的语言），
 *  等点下去才发现就晚了 —— 而且用户会怀疑是不是被覆盖了。所以这里
 *  当场给出结论，并且把「创建」按钮直接置灰。
 */
export async function refreshCodeState() {
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

export async function createLang() {
  const code = ($('newCode') as HTMLInputElement).value.trim();
  const from = ($('newFrom') as HTMLSelectElement).value;
  const err = $('newErr');
  const okBtn = $('newOk') as HTMLButtonElement;

  if (okBtn.disabled) return;      // 已经判定不能用（重名 / 只读 / 格式不对）

  if (S.dirtyIds.length) {
    err.textContent = `还有 ${S.dirtyIds.length} 条改动没保存 —— 先保存，再新建语言。`;
    toast(err.textContent);
    return;
  }

  err.textContent = '';
  toast('正在创建 ' + code + ' …');
  let made: {
    code: string; from: string; aligned: boolean; dropped: number; filled: number;
    presets?: { added: boolean; source: string | null };
    presets_error?: string;
  };
  try {
    made = await api<typeof made>(
      '/api/newlang', { code, from });
  } catch (e) {
    // 竞态兜底：比如另一个窗口刚好抢先建了同名文件
    err.textContent = (e as Error).message;
    toast('创建失败：' + (e as Error).message);
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
  const pmsg = made.presets?.added
    ? `；字体 presets 已加（模板 ${made.presets.source || '空'}）`
    : made.presets_error
      ? `；字体 presets 未加：${made.presets_error}`
      : '';
  $('stat').textContent = `已新建 ${code}（复制自 ${from}），共 ${S.total} 条待改${pmsg}`;
  toast(made.aligned
    ? `已创建 ${code}${pmsg}`
    : `已创建 ${code}：模板多 ${made.dropped} 条已忽略，缺 ${made.filled} 条用 ${made.from.split('.')[0]} 基准补齐${pmsg}`);
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
document.addEventListener('click', (ev) => {
  const el = ev.target as HTMLElement | null;
  if (el && el.closest('#newOk')) {
    ev.preventDefault();
    void createLang();
  }
});
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

setJumpHook((id) => { void jumpToId(id); });

// ── 语境推断 ────────────────────────────────────────────

$('ruleClose').addEventListener('click', () => { ($('ruleModal') as any).hide?.(); });
$('savedUnlock').addEventListener('click', () => void unlockSaved());
$('savedSave').addEventListener('click', () => void saveSaved());
$('savedClose').addEventListener('click', closeSaved);

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

window.addEventListener('error', (ev) => {
  console.error('[pr2] window error', ev.error || ev.message);
  const err = ev.error as Error | undefined;
  const stack = err && err.stack ? '\n' + err.stack.split('\n').slice(1, 4).join('\n') : '';
  showBootError((ev.message || '脚本错误') + stack);
});
window.addEventListener('unhandledrejection', (ev) => {
  const r = ev.reason as Error | undefined;
  showBootError(r && r.message ? r.message : String(ev.reason));
});

boot().catch((err) => showBootError(err && err.message ? err.message : String(err)));
