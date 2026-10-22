// 安装与启动面板的逻辑（合并进工作台后由 index.astro 引入）。
const S = { status: null, timer: 0 };

    const $ = (id) => document.getElementById(id);

    function clearChildren(el) {
      for (const c of Array.from(el.children)) {
        if (c.parentNode === el) {
          try { el.removeChild(c); } catch { /* 组件可能已接管 */ }
        }
      }
    }

    let toastTimer = 0;

    function toast(msg) {
      const a = document.getElementById('toast');
      if (!a) return;
      a.textContent = msg;
      a.open = true;
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => { a.open = false; }, 1800);
    }

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
      const ver = $('ver');
      if (ver) ver.textContent = st.valid ? (st.version || '') : '未选择目录';
      $('statusLine').textContent = st.valid
        ? `语言包：${(st.packs || []).join('、') || '（无）'} · locale.ini：${st.locale || '（空）'}`
        : '';
      $('dir').value = st.dir || '';

      const box = $('langs');
      clearChildren(box);
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
      clearChildren(sel);
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
        toast('读取状态失败：' + err.message);
      }
    }


    async function loadDirs() {
      try {
        const r = await api('/api/start/dirs');
        const ul = $('dirList');
        clearChildren(ul);
        for (const it of r.dirs || []) {
          const li = document.createElement('li');
          const actions = document.createElement('span');
          actions.className = 'dir-actions';
          const label = document.createElement('span');
          label.className = 'dir-label';
          label.textContent = (it.label || '未知版本') + (it.current ? ' · 当前' : '');
          const path = document.createElement('span');
          path.className = 'dir-path';
          path.textContent = it.dir;
          li.appendChild(label);
          li.appendChild(path);
          if (!it.valid) {
            const bad = document.createElement('span');
            bad.className = 'dir-bad';
            bad.textContent = '目录不存在';
            li.appendChild(bad);
          }
          if (!it.current && it.valid) {
            const use = document.createElement('button');
            use.textContent = '使用';
            use.className = 'mini';
            use.addEventListener('click', async () => {
              try {
                const st = await api('/api/start/use', { sha: it.sha });
                fillStatus(st);
                await loadDirs();
              } catch (err) { toast((err as Error).message); }
            });
            actions.appendChild(use);
          }
          const forget = document.createElement('button');
          forget.textContent = '移除';
          forget.className = 'mini';
          forget.addEventListener('click', async () => {
            if (!window.confirm(
              `从已记住的目录里移除这个路径？\n\n${it.dir || ''}\n\n` +
              '不会删除游戏文件，只是不再自动列出。')) return;
            try {
              await api('/api/start/forget', { sha: it.sha });
              await loadDirs();
            } catch (err) { toast((err as Error).message); }
          });
          actions.appendChild(forget);
          li.appendChild(actions);
          ul.appendChild(li);
        }
      } catch (err) {
        clearChildren($('dirList'));
      }
    }

    async function saveDir() {
      toast('检测中…');
      try {
        const st = await api('/api/start/dir', { path: $('dir').value.trim() });
        fillStatus(st);
        const savedDir = st.dir || $('dir').value.trim();
        const savedVer = st.version || '未知版本';
        toast('已记住：' + savedDir + '（' + savedVer + '）');
        await loadDirs();
      } catch (err) {
        toast(err.message);
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
      toast('等待选择目录…');
      try {
        const r = await api('/api/start/pick', {});
        $('dir').value = r.path;
        await saveDir();
      } catch (err) {
        toast((err as Error).message);
      }
    });

    $('pickDir').addEventListener('click', () => void saveDir());
    $('dir').addEventListener('keydown', (ev) => { if (ev.key === 'Enter') void saveDir(); });
    $('buildInjector').addEventListener('click', () => void runJob('build-injector', {}));
    $('buildPacks').addEventListener('click', () => void runJob('build', { langs: chosenLangs() }));
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
    void loadDirs();

    // 每次切回「安装与启动」都刷新一次，目录列表与状态不会停留在旧数据。
    for (const tab of document.querySelectorAll('.tab')) {
      tab.addEventListener('click', () => {
        if ((tab as HTMLElement).dataset.view === 'start') {
          void refresh();
          void loadDirs();
        }
      });
    }