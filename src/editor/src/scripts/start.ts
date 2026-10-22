// 安装与启动面板的逻辑（合并进工作台后由 index.astro 引入）。
const S = { status: null, timer: 0 };

    const $ = (id) => document.getElementById(id);

    async function api(path, body) {
      const opt = body === undefined ? {} : {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      };
      const r = await fetch(path, opt);
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail || data.error || ('HTTP ' + r.status));
      return data;
    }

    function fillStatus(st) {
      S.status = st;
      $('ver').textContent = st.valid ? (st.version || '') : '未选择目录';
      $('statusLine').textContent = st.valid
        ? `语言包：${(st.packs || []).join('、') || '（无）'} · locale.ini：${st.locale || '（空）'}`
        : '';
      $('dir').value = st.dir || '';

      const box = $('langs');
      box.innerHTML = '';
      for (const code of st.langs || []) {
        const lab = document.createElement('label');
        lab.className = 'lang';
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.checked = (st.packs || []).includes(code) || (st.langs || []).length === 1;
        cb.value = code;
        lab.appendChild(cb);
        lab.appendChild(document.createTextNode(code));
        box.appendChild(lab);
      }

      const sel = $('launchLang');
      sel.innerHTML = '';
      for (const code of st.packs || []) {
        const o = document.createElement('option');
        o.value = code;
        o.textContent = code;
        sel.appendChild(o);
      }
      if (st.locale) sel.value = st.locale;
    }

    async function refresh() {
      try {
        fillStatus(await api('/api/start/status'));
      } catch (err) {
        $('dirMsg').textContent = '读取状态失败：' + err.message;
      }
    }

    async function saveDir() {
      $('dirMsg').textContent = '检测中…';
      try {
        const st = await api('/api/start/dir', { path: $('dir').value.trim() });
        fillStatus(st);
        $('dirMsg').textContent = '已记住：' + st.dir;
      } catch (err) {
        $('dirMsg').textContent = err.message;
      }
    }

    function chosenLangs() {
      return Array.from($('langs').querySelectorAll('input:checked')).map((x) => x.value);
    }

    async function pollJob() {
      try {
        const st = await api('/api/start/job');
        $('log').textContent = (st.lines || []).join('\n');
        $('log').scrollTop = $('log').scrollHeight;
        if (st.running) return;
        if (S.timer) { clearInterval(S.timer); S.timer = 0; }
        if (st.done && st.error) $('log').textContent += '\n[错误] ' + st.error;
        await refresh();
      } catch { /* ignore */ }
    }

    function startPolling() {
      if (S.timer) return;
      S.timer = setInterval(pollJob, 400);
      void pollJob();
    }

    async function runJob(kind, body) {
      try {
        const r = await api('/api/start/' + kind, body);
        if (!r.ok) { $('log').textContent = r.error || '启动失败'; return; }
        $('log').textContent = '任务已开始…';
        startPolling();
      } catch (err) {
        $('log').textContent = err.message;
      }
    }

    $('browseDir').addEventListener('click', async () => {
      $('dirMsg').textContent = '等待选择目录…';
      try {
        const r = await api('/api/start/pick', {});
        $('dir').value = r.path;
        await saveDir();
      } catch (err) {
        $('dirMsg').textContent = (err as Error).message;
      }
    });

    $('pickDir').addEventListener('click', () => void saveDir());
    $('dir').addEventListener('keydown', (ev) => { if (ev.key === 'Enter') void saveDir(); });
    $('build').addEventListener('click', () => void runJob('build', { langs: chosenLangs() }));
    $('deploy').addEventListener('click', () => void runJob('deploy', { langs: chosenLangs() }));

    $('setLang').addEventListener('click', async () => {
      try {
        const st = await api('/api/start/lang', { lang: $('launchLang').value });
        fillStatus(st);
        $('log').textContent = '游戏语言已设为 ' + st.lang;
      } catch (err) { $('log').textContent = err.message; }
    });

    $('play').addEventListener('click', async () => {
      try {
        const r = await api('/api/start/launch', { lang: $('launchLang').value });
        $('log').textContent = r.message || '';
      } catch (err) { $('log').textContent = err.message; }
    });
    $('vanilla').addEventListener('click', async () => {
      try {
        const r = await api('/api/start/launch', { vanilla: true });
        $('log').textContent = r.message || '';
      } catch (err) { $('log').textContent = err.message; }
    });
    $('openEditor').addEventListener('click', () => { document.querySelector('.tab[data-view="editor"]')?.dispatchEvent(new MouseEvent('click', {bubbles: true})); });

    void refresh();