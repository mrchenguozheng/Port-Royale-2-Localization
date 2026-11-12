// 行渲染与编辑：语境/参照、contenteditable 译文格、占位符、单条保存与校验、
// 条目信息和已保存译文/规则面板。只依赖 ./core。
import {
  S, $, el, api, toast, ensureDialogs, FOLLOW, Entry, Problem, cssEsc, setDirty,
  updateStat, syncScrollers, updatePath, markActiveInList, langName, isPlaceholder,
  remember, LS_REFA, LS_REFB,
} from './core';

export let infoSeq = 0;

export function drawRows() {
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
export function clearRows() {
  for (const r of $('rows').querySelectorAll('.row')) r.remove();
}

// ── 渲染 ────────────────────────────────────────────────

/* 一行 = id + 上下堆叠的「参照…参照 / 译文」。
 * 译文在中间：它是唯一要改的那块，放中间视线落点正好。 */
export function refLine(which: 'A' | 'B', e: Entry): HTMLElement {
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
export function setEditorText(text: string) {
  const ed = zhEditor();
  if (!ed) return;
  S.suppressUndo = true;
  ed.replaceChildren(renderRich(text));
  ed.dispatchEvent(new Event('input', { bubbles: true }));
  S.suppressUndo = false;
  ed.focus();
}

export function undoEdit(id: string) {
  const st = S.undo[id] || [];
  if (!st.length) return;
  const prev = st.pop() as string;
  setEditorText(prev);
  void loadEntryInfo(id);
}

export async function copySaved(id: string) {
  const saved = S.savedText[id];
  if (saved === undefined) return;
  const ed = zhEditor();
  const cur = ed ? editorText(ed) : '';
  if (cur) {
    const st = S.undo[id] || (S.undo[id] = []);
    st.push(cur);
    if (st.length > 20) st.shift();
  }
  setEditorText(saved);
  void loadEntryInfo(id);
}

export let savedId = '';

export async function editMeaning(id: string, token: string, cur: string) {
  const val = window.prompt('占位符 ' + token + ' 的含义（留空恢复自动判断）', cur);
  if (val === null) return;
  try {
    await api('/api/placeholder-meaning',
      { lang: S.lang, id, token, meaning: val.trim() });
    void loadEntryInfo(id);
  } catch (err) {
    const box = document.getElementById('infoBar');
    toast('含义保存失败：' + (err as Error).message);
  }
}

export function diffNodes(a: string, b: string): DocumentFragment {
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

export async function openRules(id: string) {
  try {
    await ensureDialogs();
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
    ($('ruleModal') as any).show?.();
  } catch (err) {
    toast('规则轨迹读取失败：' + (err as Error).message);
  }
}

export async function openSaved(id: string) {
  try {
    await ensureDialogs();
    const r = await api<{ text: string }>(
      `/api/translation?lang=${encodeURIComponent(S.lang)}&id=${encodeURIComponent(id)}`);
    savedId = id;
    const ta = $('savedText') as HTMLTextAreaElement;
    ta.value = r.text;
    ta.setAttribute('readonly', '');
    ($('savedSave') as HTMLButtonElement).disabled = true;
    $('savedLockInfo').textContent =
      '已保存译文默认锁定。解锁后只能改这一条，保存或关闭后重新锁定。';
    ($('savedModal') as any).show?.();
    ta.focus();
  } catch (err) {
    toast('读取已保存译文失败：' + (err as Error).message);
  }
}

export async function unlockSaved() {
  if (!window.confirm('只解锁这一条的已保存译文，且仅本次修改有效。继续？')) return;
  const ta = $('savedText') as HTMLTextAreaElement;
  ta.removeAttribute('readonly');
  ($('savedSave') as HTMLButtonElement).disabled = false;
  $('savedLockInfo').textContent = '已解锁（仅本次修改）。保存或关闭后重新锁定。';
  ta.focus();
}

export async function saveSaved() {
  try {
    const ta = $('savedText') as HTMLTextAreaElement;
    await api('/api/translation', { lang: S.lang, id: savedId, text: ta.value });
    ta.setAttribute('readonly', '');
    ($('savedSave') as HTMLButtonElement).disabled = true;
    $('savedLockInfo').textContent = '译文已保存，已重新锁定。引擎文本未变。';
  } catch (err) {
    toast('保存失败：' + (err as Error).message);
  }
}

export function closeSaved() {
  ($('savedModal') as any).hide?.();
  ($('savedText') as HTMLTextAreaElement).readOnly = true;
  ($('savedSave') as HTMLButtonElement).disabled = true;
}

export async function setTermRule(id: string, term: string, skip: boolean) {
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
    toast('规则保存失败：' + (err as Error).message);
  }
}

export async function loadEntryInfo(id: string) {
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
        meaning.has(c.token) ? (meaning.get(c.token) || '') : ''));
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
        `/api/translation?lang=${encodeURIComponent(S.lang)}&id=${encodeURIComponent(id)}`);
      S.savedText[id] = sd.text;
      const body = document.querySelector('.saved-inline .saved-body');
      if (body) body.textContent = sd.text;
      const sb = document.querySelector('.saved-inline');
      const ed = zhEditor();
      const norm = (t: string) => t.replace(/\s+/g, '');
      if (sb && ed) sb.classList.toggle('diff', norm(ed.textContent || '') !== norm(sd.text));
    } catch {
      const body = document.querySelector('.saved-inline .saved-body');
      if (body) body.textContent = '（没有已保存译文）';
    }

    const extraSp = r.extra_spaces || 0;
    box.appendChild(el('span', 'info-sp',
      extraSp > 0 ? `空格：多 ${extraSp} 处` : '空格：与干净文本一致'));
    if (r.tags && r.tags.length) {
      box.appendChild(el('span', 'info-tag', '标记：' + r.tags.join('、')));
    }
  } catch (err) {
    toast('提示读取失败：' + (err as Error).message);
  }
}

export function zhEditor(): HTMLElement | null {
  return document.querySelector('.cell-zh .edit') as HTMLElement | null;
}

export function rowOf(e: Entry): HTMLElement {
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

  // 左栏：已保存译文、原文 A、原文 B；右栏：译文编辑
  const left = el('div', 'col-src');

  const savedBox = el('div', 'saved-inline ref-block');
  const savedHead = el('div', 'ref-head');
  savedHead.appendChild(el('span', 'ref-label', '已保存译文'));
  const savedCopy = el('button', 'mini saved-edit', '复制到译文');
  savedCopy.title = '用已保存译文覆盖编辑框（可撤销）';
  savedCopy.addEventListener('click', () => void copySaved(e.id));
  savedHead.appendChild(savedCopy);
  const savedEdit = el('button', 'mini saved-edit', '解锁编辑');
  savedEdit.title = '逐条解锁，仅本次修改有效';
  savedEdit.addEventListener('click', () => void openSaved(e.id));
  savedHead.appendChild(savedEdit);
  savedBox.appendChild(savedHead);
  const savedBody = el('div', 'saved-body', '（读取中…）');
  savedBox.appendChild(savedBody);
  left.appendChild(savedBox);

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
export function textOf(e: Entry): string {
  const ed = S.edits.get(e.id);
  return ed === undefined ? ((e[S.lang] as string) || '') : ed;
}

/* 译文格：contenteditable，空格直接渲染成带底色的 span。
 * 不再用「透明 textarea + 覆盖层」，从根上避免两层排版不一致。 */
export function editorText(root: HTMLElement): string {
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

export function caretOffset(root: HTMLElement): number {
  const sel = window.getSelection();
  if (!sel || !sel.rangeCount) return 0;
  const range = sel.getRangeAt(0).cloneRange();
  const pre = range.cloneRange();
  pre.selectNodeContents(root);
  pre.setEnd(range.endContainer, range.endOffset);
  return pre.toString().length;
}

export function setCaretOffset(root: HTMLElement, offset: number) {
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

export function zhCell(e: Entry): HTMLElement {
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
    const sb = document.querySelector('.saved-inline');
    if (sb) {
      const saved = S.savedText[e.id];
      const norm = (t: string) => t.replace(/\s+/g, '');
      sb.classList.toggle('diff', !!saved && norm(saved) !== norm(fixed));
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
export function highlightSpaces(text: string): DocumentFragment {
  const f = document.createDocumentFragment();
  if (text) f.appendChild(document.createTextNode(text));
  return f;
}


export const TOKEN_RX = /@[A-Za-z]\$[A-Za-z0-9_]+\$|%0?\d+[A-Za-z]?|%[A-Za-z]/g;

export function tokenSpan(tok: string): HTMLElement {
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

export function setTokenMeaning(span: HTMLElement, tok: string, meaning: string) {
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

export function renderRich(text: string): DocumentFragment {
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

export function countTokens(text: string): Record<string, number> {
  const out: Record<string, number> = {};
  TOKEN_RX.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = TOKEN_RX.exec(text))) out[m[0]] = (out[m[0]] || 0) + 1;
  return out;
}

/** 占位符只许换位置，不许少；少了就在末尾补回来。 */
export function enforceTokens(id: string, text: string): string {
  const req = S.req[id] || {};
  const have = countTokens(text);
  let out = text;
  for (const tok of Object.keys(req)) {
    for (let i = have[tok] || 0; i < req[tok]; i += 1) out += tok;
  }
  return out;
}

export async function loadContexts(rows: Entry[]) {
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
export async function activateRow(id: string, ed: HTMLElement) {
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
export async function saveOne(id: string) {
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

// ── 校验 ────────────────────────────────────────────────

export async function check(id: string) {
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

export function redraw(id: string) {
  const old = $('rows').querySelector(`.row[data-id="${cssEsc(id)}"]`);
  const src = S.rows.find((x) => x.id === id);
  if (!old || !src) return;
  if (!old.isConnected) return;      // 另一个 redraw 已经换掉了这一行
  const fresh = rowOf(src);
  try {
    old.replaceWith(fresh);
  } catch {
    return;
  }
  void loadEntryInfo(id);
}
