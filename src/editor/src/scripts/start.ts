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

    function setFontStatus(st) {
      const base = $('fontBaseState');
      const donor = $('fontDonorState');
      const built = $('fontBuildState');
      if (base) {
        const miss = (st.base && st.base.missing) ? st.base.missing.length : 0;
        base.textContent = miss
          ? `缺 ${miss} 个（需从游戏导出）`
          : `已就绪（${st.base.total}/${st.base.total}）`;
        base.className = 'step-state ' + (miss ? 'bad' : 'ok');
      }
      if (donor) {
        const rows = st.languages || [];
        const parts = rows.map((r) => {
          const all = r.donors || [];
          const have = all.filter((d) => d.exists).length;
          return `${r.lang} ${have}/${all.length}`;
        });
        donor.textContent = (parts.join(' · ') || '无 presets') +
          ` · fontTools ${st.fonttools ? '已装' : '缺'}`;
        const allOk = rows.length > 0 && rows.every(
          (r) => (r.donors || []).length && (r.donors || []).every((d) => d.exists));
        donor.className = 'step-state ' + (allOk ? 'ok' : 'bad');
      }
      if (built) {
        const rows = st.languages || [];
        built.textContent = rows.length
          ? rows.map((r) => `${r.lang} ${r.built}/${r.total}`).join(' · ')
          : '未生成';
        const allBuilt = rows.length > 0 && rows.every((r) => r.built === r.total);
        built.className = 'step-state ' + (allBuilt ? 'ok' : 'bad');
      }
      const preset = $('fontPreset');
      if (preset) preset.textContent = st.presets_dir || '';
      const msg = $('fontMsg');
      if (msg) {
        msg.textContent = (st.problems && st.problems.length)
          ? '待处理：' + st.problems.join('；')
          : '字体前置条件齐全。';
      }
    }

    async function loadFontStatus() {
      try {
        setFontStatus(await api('/api/font-status'));
      } catch (err) {
        const msg = $('fontMsg');
        if (msg) msg.textContent = '读取字体状态失败：' + err.message;
      }
    }


    function fmtUptime(sec) {
      const s = Math.max(0, Number(sec) || 0);
      if (s < 60) return `${s} 秒`;
      if (s < 3600) return `${Math.floor(s / 60)} 分钟`;
      return `${Math.floor(s / 3600)} 小时 ${Math.floor((s % 3600) / 60)} 分`;
    }

    async function loadServers() {
      const info = $('srvInfo');
      const ul = $('srvList');
      try {
        const r = await api('/api/server/instances');
        const list = r.instances || [];
        info.textContent = `当前端口 ${r.current} · 运行中的编辑器 ${list.length} 个`;
        clearChildren(ul);
        for (const it of list) {
          const li = document.createElement('li');
          li.textContent =
            `端口 ${it.port} · pid ${it.pid} · 已运行 ${fmtUptime(it.uptime)}` +
            (it.current ? ' · 当前窗口' : '');
          ul.appendChild(li);
        }
      } catch (err) {
        info.textContent = '读取服务状态失败';
        toast('读取服务状态失败：' + err.message);
      }
    }

    async function loadGameState() {
      try {
        const r = await api('/api/start/running');
        const procs = r.procs || [];
        $('gameState').textContent = r.running
          ? '游戏状态：运行中（' + procs.map((p) => `${p.name} pid ${p.pid}`).join('、') + '）'
          : '游戏状态：未运行';
      } catch (err) {
        $('gameState').textContent = '游戏状态：读取失败';
        toast('读取游戏状态失败：' + err.message);
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
    $('srvRefresh').addEventListener('click', () => void loadServers());
    $('checkGame').addEventListener('click', () => void loadGameState());
    $('killGame').addEventListener('click', () => {
      void (async () => {
        if (!window.confirm('强制结束游戏进程？未保存的游戏进度会丢失。')) return;
        try {
          const r = await api('/api/start/kill', {});
          toast(r.message || (r.ok ? '已结束游戏进程' : '结束失败'));
        } catch (err) {
          toast('结束失败：' + err.message);
        }
        await loadGameState();
      })();
    });
    $('dir').addEventListener('keydown', (ev) => { if (ev.key === 'Enter') void saveDir(); });
    $('buildInjector').addEventListener('click', () => void runJob('build-injector', {}));
    $('buildPacks').addEventListener('click', () => void runJob('build', { langs: chosenLangs() }));
    $('deploy').addEventListener('click', () => void runJob('deploy', { langs: chosenLangs() }));

    $('fontCheck').addEventListener('click', () => void loadFontStatus());

    $('fontExport').addEventListener('click', () => {
      void (async () => {
        const dir = ($('dir') as HTMLInputElement).value.trim();
        if (!dir) { toast('先填写游戏目录'); return; }
        const btn = $('fontExport') as HTMLButtonElement;
        btn.disabled = true;
        $('log').textContent = '导出原版字体…';
        try {
          const r = await api('/api/font/export', { dir });
          $('log').textContent = r.output || (r.ok ? '导出完成' : '导出失败');
          setFontStatus(r.status);
          toast(r.ok ? '原版字体已导出' : '导出失败，见日志');
        } catch (err) {
          $('log').textContent = (err as Error).message;
        } finally {
          btn.disabled = false;
        }
      })();
    });

    $('fontStitch').addEventListener('click', () => {
      void (async () => {
        if (!window.confirm('按当前译文重新缝合四个字体？可能需要十几秒。')) return;
        const btn = $('fontStitch') as HTMLButtonElement;
        btn.disabled = true;
        $('log').textContent = '字体缝合中…';
        try {
          const r = await api('/api/font/stitch', { force: true });
          $('log').textContent = (r.log || []).join('\n') +
            (r.message ? '\n' + r.message : '');
          setFontStatus(r.status);
          toast(r.ok ? '字体已缝合' : '缝合失败，见日志');
        } catch (err) {
          $('log').textContent = (err as Error).message;
        } finally {
          btn.disabled = false;
        }
      })();
    });

    $('firstRunEdit').addEventListener('click', () => {
      document.querySelector('.tab[data-view="editor"]')?.dispatchEvent(
        new MouseEvent('click', { bubbles: true }));
    });

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
    void loadServers();
    void loadGameState();
    void loadFontStatus();

    // 每次切回「安装与启动」都刷新一次，目录列表与状态不会停留在旧数据。
    for (const tab of document.querySelectorAll('.tab')) {
      tab.addEventListener('click', () => {
        if ((tab as HTMLElement).dataset.view === 'start') {
          void refresh();
          void loadDirs();
          void loadServers();
          void loadGameState();
          void loadFontStatus();
        }
      });
    }