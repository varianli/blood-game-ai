/* 主持人大屏 */
(function () {
  var DEFAULT_NAMES = ['林岚', '周澈', '陈星', '苏禾', '顾言', '唐悦'];
  var $ = function (id) { return document.getElementById(id); };
  var room = null, hk = null, joinUrl = '', offset = 0, S = null, lastV = -1;
  var roomAiDraft = { key: '', model: '', open: false };
  var memoryDraft = {
    game: '', initialized: false, open: false,
    names: [], generator: '', nInfos: '', nQuestions: ''
  };

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function post(url, body) {
    return fetch(url, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    }).then(function (r) { return r.json(); });
  }
  function toast(msg) {
    var d = document.createElement('div');
    d.className = 'toast'; d.textContent = msg;
    document.body.appendChild(d);
    setTimeout(function () { d.remove(); }, 4000);
  }
  function showQrUnavailable() {
    var box = $('qr');
    if (!box) return;
    box.innerHTML = '<div class="qr-missing">二维码暂时无法生成' +
      '<span>请让玩家直接输入右侧网址</span></div>';
  }

  /* ---------------- 名单编辑 ---------------- */

  function addName(v) {
    var w = document.createElement('div');
    w.className = 'ntag';
    var i = document.createElement('input');
    i.value = v || ''; i.placeholder = '姓名'; i.maxLength = 12;
    var b = document.createElement('button');
    b.textContent = '×'; b.title = '删掉';
    b.onclick = function () { w.remove(); };
    w.appendChild(i); w.appendChild(b);
    $('names').appendChild(w);
    return i;
  }
  function getNames() {
    return Array.prototype.map.call($('names').querySelectorAll('input'),
      function (i) { return i.value.trim(); }).filter(Boolean);
  }
  DEFAULT_NAMES.forEach(addName);
  $('addName').onclick = function () { addName('').focus(); };

  /* ---------------- 玩法预设 ---------------- */

  var gameId = new URLSearchParams(location.search).get('game') || 'classic';
  var kind = 'deduce';
  function isMemoryGame(gid) {
    return ['blitz', 'classic', 'hardcore'].indexOf(gid) >= 0;
  }
  var LEVEL_HELP = {
    '简单': '常识热身：多数普通成年人可以直接回忆作答，适合第一次参与。',
    '中等': '知识挑战：需要扎实通识或一步联想，干扰项来自相邻概念。',
    '困难': '高手竞赛：至少六成题考精确细节或两步联想，并自动过滤送分题。'
  };
  function syncLevelHint() {
    $('levelHelp').textContent = LEVEL_HELP[$('level').value] || '';
  }
  $('level').onchange = syncLevelHint;
  syncLevelHint();

  fetch('/api/games').then(function (r) { return r.json(); }).then(function (d) {
    var g = (d.games || []).filter(function (x) { return x.id === gameId; })[0];
    if (!g) return;
    $('gName').textContent = g.emoji + '　' + g.name;
    $('gDesc').textContent = g.desc;
    kind = g.engine;
    // 把玩法预设填进表单，主持人还可以继续手改
    Object.keys(g.preset || {}).forEach(function (k) {
      if ($(k)) $(k).value = g.preset[k];
    });
    syncLevelHint();
    // 各玩法用得上的设置不一样，藏掉用不上的
    var trivia = kind === 'trivia';
    $('triviaBox').classList.toggle('hide', !trivia);
    $('triviaTimingFlow').classList.toggle('hide', !trivia);
    $('timingTitle').textContent = trivia ? '知识问答 · 各环节时间' : '玩法节奏';
    $('timingHint').textContent = trivia
      ? '作答、公布答案与实时排行榜的停留时间都可以单独调整。'
      : '每一阶段都可以按现场节奏调整。';
    $('namesBox').classList.toggle('hide', trivia || kind === 'draw');
    $('infoBox').classList.toggle('hide', kind !== 'deduce');
    $('ninfoBox').classList.toggle('hide', kind !== 'deduce');
    $('describeBox').classList.toggle('hide', kind !== 'undercover');
    $('sourceBox').classList.toggle('hide', kind !== 'deduce');
    if (kind === 'vote')
      $('namesLabel').textContent = '参与的人（出题时会参考，实际投票用的是进房间的玩家）';
    var qLabel = { trivia: '题目数量', vote: '题目数量',
                   undercover: '玩几轮', draw: '画几幅' }[kind];
    if (qLabel) $('qLabel').textContent = qLabel;
  }).catch(function () { });

  /* ---------------- 建房 ---------------- */

  function settingsPayload() {
    var p = { names: getNames() };
    ['info_sec', 'question_sec', 'reveal_sec', 'board_sec',
      'n_infos', 'n_questions'].forEach(function (k) {
        p[k] = parseInt($(k).value, 10) || 1;
      });
    p.generator = $('generator').value;
    p.auto = $('auto').checked;
    p.model = $('model').value.trim();
    p.topic = $('topic').value;
    p.level = $('level').value;
    p.describe_sec = parseInt($('describe_sec').value, 10) || 90;
    if ($('api_key').value.trim()) p.api_key = $('api_key').value.trim();
    p.game = gameId;
    return p;
  }

  $('create').onclick = function () {
    if (getNames().length < 2) { toast('至少要有 2 个人物'); return; }
    $('create').disabled = true;
    post('/api/host/create', settingsPayload()).then(function (r) {
      room = r.room; hk = r.hk;
      $('api_key').value = '';
      joinUrl = (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
        ? (r.join && r.join[0]) || (location.origin + '/p?room=' + room)
        : location.origin + '/p?room=' + room;
      try {
        localStorage.setItem('xzyx_host',
          JSON.stringify({ room: room, hk: hk, url: joinUrl, game: gameId }));
      } catch (e) { }
      $('setup').classList.add('hide');
      $('stage').classList.remove('hide');
      $('tRoom').textContent = room;
      act('generate');
      poll();
    }).catch(function () {
      $('create').disabled = false; toast('创建失败，服务没跑起来？');
    });
  };

  // 刷新页面后自动恢复控制权；如果是从游戏厅带着 keep 回来的，直接换掉当前房间的玩法
  try {
    var keep = new URLSearchParams(location.search).get('keep');
    var saved = JSON.parse(localStorage.getItem('xzyx_host') || 'null');
    if (saved && saved.room) {
      fetch('/api/state?room=' + saved.room + '&hk=' + saved.hk + '&since=0')
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (s) {
          if (!s || !s.host) return;
          room = saved.room; hk = saved.hk; joinUrl = saved.url;
          $('setup').classList.add('hide');
          $('stage').classList.remove('hide');
          $('tRoom').textContent = room;
          // 从游戏厅挑了别的玩法回来 —— 换掉当前房间的游戏，玩家不用重扫码
          if (keep && s.game !== gameId) {
            switchToGame(gameId);
          }
          poll();
        }).catch(function () { });
    }
  } catch (e) { }

  function switchToGame(gid) {
    var needsMemorySetup = isMemoryGame(gid);
    gameId = gid;
    memoryDraft.initialized = false;
    memoryDraft.open = needsMemorySetup;
    try {
      var saved = JSON.parse(localStorage.getItem('xzyx_host') || 'null');
      if (saved) {
        saved.game = gid;
        localStorage.setItem('xzyx_host', JSON.stringify(saved));
      }
    } catch (e) { }
    return act('switch_game', { game: gid }).then(function () {
      if (!needsMemorySetup) return act('generate');
      toast('已切换到 Memory，请确认人物与出题方式后生成');
    });
  }

  /* ---------------- 控制 ---------------- */

  function act(action, payload) {
    return post('/api/host/act',
      { room: room, hk: hk, action: action, payload: payload || {} });
  }
  $('bPause').onclick = function () { act(S && S.paused ? 'resume' : 'pause'); };
  $('bSkip').onclick = function () { act('skip'); };
  $('bNext').onclick = function () { act('skip'); };
  // 回游戏厅挑别的玩法。带上房间号，这样在首页选中的游戏会直接换到当前房间，
  // 玩家不用重新扫码，整晚总分也接着累加。
  $('bHub').onclick = function () {
    location.href = room ? '/?room=' + encodeURIComponent(room) : '/';
  };

  // 投屏时原生 confirm 弹窗经常被忽略甚至被全屏模式吞掉，改成按钮上就地二次确认
  var lobbyArm = 0;
  $('bLobby').onclick = function () {
    var b = $('bLobby');
    if (Date.now() < lobbyArm) {
      lobbyArm = 0;
      b.textContent = '回大厅';
      b.classList.remove('gold');
      act('lobby');
      return;
    }
    lobbyArm = Date.now() + 4000;
    b.textContent = '再点一次 = 回大厅';
    b.classList.add('gold');
    setTimeout(function () {
      if (Date.now() >= lobbyArm && lobbyArm) {
        lobbyArm = 0;
        b.textContent = '回大厅';
        b.classList.remove('gold');
      }
    }, 4100);
  };
  document.addEventListener('keydown', function (e) {
    if (!room || e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
    if (S && S.phase === 'lobby') return;      // 大厅里快捷键一律不生效
    if (e.code === 'Space') { e.preventDefault(); $('bPause').click(); }
    if (e.code === 'ArrowRight') { e.preventDefault(); act('skip'); }
    if (e.code === 'ArrowLeft') { e.preventDefault(); act('prev_info'); }
  });

  /* ---------------- 轮询 ---------------- */

  function poll() {
    fetch('/api/state?room=' + room + '&hk=' + hk + '&since=' + lastV)
      .then(function (r) { return r.json(); })
      .then(function (s) {
        if (s.error) { toast('房间没了，刷新页面重开'); return; }
        offset = s.now - Date.now();
        S = s;
        if (s.v !== lastV) { lastV = s.v; render(); }
        setTimeout(poll, 30);
      })
      .catch(function () { setTimeout(poll, 1200); });
  }

  function remain() {
    if (!S || !S.deadline) return null;
    return Math.max(0, S.deadline - (Date.now() + offset));
  }

  /* ---------------- 渲染 ---------------- */

  var PHASE_CN = {
    lobby: '等待玩家', briefing: '放信息', question: '答题中',
    reveal: '公布答案', scoreboard: '排行榜', final: '本局结束'
  };

  function render() {
    var c = $('center'), s = S;
    $('tGame').textContent = s.game_name || '血之游戏';
    $('tPhase').textContent = PHASE_CN[s.phase] || s.phase;
    $('tCount').textContent = s.count + ' 人';
    $('bPause').textContent = s.paused ? '继续' : '暂停';
    $('bPause').classList.toggle('hide', !s.deadline && !s.paused);
    $('bSkip').classList.toggle('hide', s.phase === 'lobby');
    $('bNext').classList.toggle('hide',
      !(s.phase === 'scoreboard' && !s.settings.auto));
    renderLiveRanking(s);

    if (s.phase === 'lobby') return renderLobby(c, s);
    if (s.kind === 'draw' && s.draw) return renderDraw(c, s);
    if (s.kind === 'undercover' && s.phase === 'assign') return renderAssign(c, s);
    if (s.kind === 'undercover' && s.phase === 'describe') return renderDescribe(c, s);
    if (s.kind === 'undercover' && s.phase === 'reveal') return renderUcReveal(c, s);
    if (s.kind === 'vote' && s.phase === 'reveal') return renderVoteResult(c, s);
    if ((s.kind === 'vote' || s.kind === 'undercover') && s.phase === 'question')
      return renderVoteAsk(c, s);
    if (s.phase === 'briefing') return renderBriefing(c, s);
    if (s.phase === 'question') return renderQuestion(c, s, false);
    if (s.phase === 'reveal') return renderQuestion(c, s, true);
    if (s.phase === 'scoreboard') return renderBoard(c, s, false);
    if (s.phase === 'final') return renderBoard(c, s, true);
  }

  function renderLiveRanking(s) {
    var panel = $('liveRanking');
    if (!panel) return;
    var board = s.board || [];
    var rows = board.map(function (p) {
      var crown = p.rank === 1 ? '👑' : p.rank;
      return '<div class="live-rank-row rank-' + p.rank +
        (p.online ? '' : ' offline') + '">' +
        '<span class="live-rank-no">' + crown + '</span>' +
        '<span class="live-rank-name">' + esc(p.name) + '</span>' +
        (p.gain ? '<span class="live-rank-gain">+' + p.gain + '</span>' : '') +
        '<strong>' + p.score + '</strong></div>';
    }).join('');

    panel.innerHTML =
      '<div class="live-ranking-head"><div><span class="live-dot"></span>' +
      '实时排行榜</div><span class="live-ranking-count">' + s.count +
      ' 人</span></div>' +
      (rows ? '<div class="live-ranking-list">' + rows + '</div>' :
        '<div class="live-ranking-empty">玩家加入后，排名会在这里实时更新</div>');
  }

  // 下一套题的预生成状态（只有 DeepSeek 模式才会预生成）
  function nextTag(s) {
    var n = s.next_gen || {};
    if (n.status === 'running')
      return '<div class="note" id="preNote">⏳ 后台正在预生成下一套题' +
        '<span id="preSec"></span></div>';
    if (n.status === 'ok' || s.next_ready)
      return '<div class="note" style="color:var(--ok)">✔ 下一套题已就绪，' +
        '「再来一局」不用等</div>';
    if (n.status === 'error')
      return '<div class="note warn">预生成没成功：' + esc(n.msg || '') +
        '（不影响这一局）</div>';
    return '';
  }

  function roomAiPanel(s) {
    var configured = !!s.api_key_set;
    var source = '尚未生成题库';
    var sourceClass = 'idle';
    if (s.set_source === 'deepseek') {
      source = '当前题库：DeepSeek';
      sourceClass = 'ok';
    } else if (s.set_source) {
      source = s.difficulty_guaranteed === false
        ? '当前题库：基础兜底 · 难度已降级'
        : '当前题库：本地生成';
      sourceClass = s.difficulty_guaranteed === false ? 'warn' : 'ok';
    }
    return '<details class="room-ai-panel" id="roomAiPanel"' +
      (roomAiDraft.open ? ' open' : '') + '>' +
      '<summary><span>房间 AI 设置</span>' +
      '<span class="ai-state ' + (configured ? 'ok' : 'idle') + '">' +
      (configured ? '密钥已配置' : '尚未配置密钥') + '</span>' +
      '<span class="ai-source ' + sourceClass + '">' + esc(source) + '</span></summary>' +
      '<div class="room-ai-panel-body"><div class="grid2">' +
      '<label class="frow"><span class="label">DeepSeek 模型</span>' +
      '<input class="field" id="roomAiModel" maxlength="100"></label>' +
      '<label class="frow"><span class="label">更新 API Key</span>' +
      '<input class="field" id="roomApiKey" type="password" maxlength="512" ' +
      'autocomplete="off" spellcheck="false" placeholder="sk-...（不回显已保存密钥）"></label>' +
      '</div><div class="note">密钥只保存在这个房间的服务端内存中，不会发送给玩家，' +
      '也不会写入浏览器存储。</div>' +
      '<button class="btn ghost" id="saveRoomAi">保存并重新出题</button></div></details>';
  }

  function captureRoomAiDraft() {
    var panel = $('roomAiPanel');
    if (!panel) return;
    roomAiDraft.open = panel.open;
    if ($('roomAiModel')) roomAiDraft.model = $('roomAiModel').value;
    if ($('roomApiKey')) roomAiDraft.key = $('roomApiKey').value;
  }

  function ensureMemoryDraft(s) {
    if (memoryDraft.initialized && memoryDraft.game === s.game) return;
    memoryDraft.game = s.game;
    memoryDraft.initialized = true;
    memoryDraft.names = (s.settings.names || DEFAULT_NAMES).slice(0, 20);
    memoryDraft.generator = s.settings.generator || 'local';
    memoryDraft.nInfos = String(s.settings.n_infos || 30);
    memoryDraft.nQuestions = String(s.settings.n_questions || 15);
  }

  function memorySettingsPanel(s) {
    if (!isMemoryGame(s.game)) return '';
    ensureMemoryDraft(s);
    var names = memoryDraft.names.map(function (name, index) {
      return '<div class="memory-name-row">' +
        '<input class="field memory-name-input" maxlength="12" value="' +
        esc(name) + '" aria-label="人物 ' + (index + 1) + '">' +
        '<button type="button" class="memory-name-remove" data-index="' + index +
        '" aria-label="删除人物 ' + (index + 1) + '">×</button></div>';
    }).join('');
    var options = [
      ['local', '本地随机生成 · 秒出且答案可靠'],
      ['polish', '本地计算 + DeepSeek 润色'],
      ['ai', 'DeepSeek 全量生成'],
      ['default', '内置默认题库']
    ].map(function (option) {
      return '<option value="' + option[0] + '"' +
        (memoryDraft.generator === option[0] ? ' selected' : '') + '>' +
        option[1] + '</option>';
    }).join('');
    var source = s.has_set ? ('当前已生成：' + (s.set_title || '题库')) : '等待确认设置';
    return '<details class="room-ai-panel memory-lobby-panel" id="memorySettingsPanel"' +
      ((memoryDraft.open || !s.has_set) ? ' open' : '') + '>' +
      '<summary><span>Memory 本局设置</span>' +
      '<span class="ai-state ' + (s.has_set ? 'ok' : 'idle') + '">' +
      esc(source) + '</span></summary>' +
      '<div class="room-ai-panel-body"><div class="memory-lobby-grid">' +
      '<div class="frow memory-names-field"><span class="label">题目人物</span>' +
      '<div class="memory-name-list" id="memoryNameInputs">' + names + '</div>' +
      '<button type="button" class="btn ghost memory-add-name" id="addMemoryName">+ 加一个人物</button></div>' +
      '<div class="memory-mode-fields"><label class="frow"><span class="label">出题方式</span>' +
      '<select class="field" id="memoryGenerator">' + options + '</select></label>' +
      '<div class="grid2"><label class="frow"><span class="label">信息条数</span>' +
      '<input class="field" id="memoryInfoCount" type="number" min="6" max="60" value="' +
      esc(memoryDraft.nInfos) + '"></label>' +
      '<label class="frow"><span class="label">题目数量</span>' +
      '<input class="field" id="memoryQuestionCount" type="number" min="3" max="40" value="' +
      esc(memoryDraft.nQuestions) + '"></label></div>' +
      '<div class="note">选择 DeepSeek 时会使用本房间下方的 AI 设置；人物与模式只影响本局。</div>' +
      '<button class="btn" id="saveMemorySettings">保存设置并生成题库</button></div>' +
      '</div></div></details>';
  }

  function captureMemoryDraft() {
    var panel = $('memorySettingsPanel');
    if (!panel) return;
    memoryDraft.open = panel.open;
    memoryDraft.names = Array.prototype.map.call(
      panel.querySelectorAll('.memory-name-input'),
      function (input) { return input.value; });
    if ($('memoryGenerator')) memoryDraft.generator = $('memoryGenerator').value;
    if ($('memoryInfoCount')) memoryDraft.nInfos = $('memoryInfoCount').value;
    if ($('memoryQuestionCount')) memoryDraft.nQuestions = $('memoryQuestionCount').value;
  }

  function collectMemoryPayload(s) {
    if (!isMemoryGame(s.game)) return {};
    captureMemoryDraft();
    var names = memoryDraft.names.map(function (name) {
      return name.trim().slice(0, 12);
    }).filter(Boolean).slice(0, 20);
    if (names.length < 2) {
      toast('Memory 至少需要 2 个人物');
      return null;
    }
    var nInfos = Math.max(6, Math.min(60, parseInt(memoryDraft.nInfos, 10) || 30));
    var nQuestions = Math.max(3, Math.min(40,
      parseInt(memoryDraft.nQuestions, 10) || 15));
    memoryDraft.names = names;
    memoryDraft.nInfos = String(nInfos);
    memoryDraft.nQuestions = String(nQuestions);
    return {
      names: names,
      generator: memoryDraft.generator,
      n_infos: nInfos,
      n_questions: nQuestions
    };
  }

  function bindMemorySettings(c, s) {
    var panel = $('memorySettingsPanel');
    if (!panel) return;
    panel.open = memoryDraft.open || !s.has_set;
    panel.ontoggle = function () { memoryDraft.open = panel.open; };

    $('addMemoryName').onclick = function () {
      captureMemoryDraft();
      captureRoomAiDraft();
      if (memoryDraft.names.length >= 20) {
        toast('人物最多 20 个');
        return;
      }
      memoryDraft.names.push('');
      memoryDraft.open = true;
      renderLobby(c, s, true);
      var inputs = document.querySelectorAll('.memory-name-input');
      if (inputs.length) inputs[inputs.length - 1].focus();
    };
    Array.prototype.forEach.call(
      panel.querySelectorAll('.memory-name-remove'), function (button) {
        button.onclick = function () {
          captureMemoryDraft();
          captureRoomAiDraft();
          memoryDraft.names.splice(parseInt(button.getAttribute('data-index'), 10), 1);
          memoryDraft.open = true;
          renderLobby(c, s, true);
        };
      });

    $('memoryGenerator').onchange = function () {
      memoryDraft.generator = $('memoryGenerator').value;
    };
    $('saveMemorySettings').disabled = s.gen.status === 'running';
    $('saveMemorySettings').onclick = function () {
      var payload = collectMemoryPayload(s);
      if (!payload) return;
      var needsAi = payload.generator === 'ai' || payload.generator === 'polish';
      var pendingKey = $('roomApiKey') ? $('roomApiKey').value.trim() : roomAiDraft.key.trim();
      if (needsAi && !s.api_key_set && !pendingKey) {
        roomAiDraft.open = true;
        if ($('roomAiPanel')) $('roomAiPanel').open = true;
        toast('选择 DeepSeek 前，请先在房间 AI 设置中输入 API Key');
        if ($('roomApiKey')) $('roomApiKey').focus();
        return;
      }
      if (pendingKey) payload.api_key = pendingKey;
      $('saveMemorySettings').disabled = true;
      act('settings', payload).then(function () {
        roomAiDraft.key = '';
        if ($('roomApiKey')) $('roomApiKey').value = '';
        return act('generate');
      }).then(function () {
        memoryDraft.open = false;
        toast('Memory 设置已保存，正在生成题库');
      }).catch(function () {
        $('saveMemorySettings').disabled = false;
        toast('保存失败，请检查服务是否仍在运行');
      });
    };
  }

  function renderLobby(c, s, draftReady) {
    if (!draftReady) {
      captureMemoryDraft();
      captureRoomAiDraft();
    }
    var busy = s.gen.status === 'running';
    var memoryNeedsSet = isMemoryGame(s.game) && !s.has_set;
    c.innerHTML =
      '<div class="roomcode">' + esc(s.room) + '</div>' +
      '<div class="joinbox">' +
      '<div class="qr" id="qr"></div>' +
      '<div><div class="label">手机打开这个网址</div>' +
      '<div class="joinurl">' + esc(joinUrl) + '</div>' +
      '<div class="note" style="margin-top:10px">手机需要连同一个 Wi-Fi</div></div>' +
      '</div>' +
      '<div class="chips" id="chips"></div>' +
      '<select class="field" id="swGame" style="max-width:420px"></select>' +
      (s.played && s.played.length
        ? '<div class="note">今晚已经玩过：' + esc(s.played.join('、')) +
          '　（总分累计中）</div>' : '') +
      '<div class="note" style="text-align:center" id="genNote">' +
      (busy ? '⏳ ' : '') + esc(s.gen.msg || '还没生成题库') +
      (busy ? '<span id="genSec"></span>' : '') +
      (s.has_set ? '　·　' + esc(s.set_title) + '（' + s.n_info_total +
        ' 条信息 / ' + s.n_q_total + ' 道题）' : '') + '</div>' +
      memorySettingsPanel(s) +
      roomAiPanel(s) +
      nextTag(s) +
      '<div style="display:flex;gap:14px;flex-wrap:wrap;justify-content:center">' +
      '<button class="btn ghost" id="bGen"' + (busy ? ' disabled' : '') + '>换一套题</button>' +
      '<button class="btn" id="bStart"' + ((busy || memoryNeedsSet) ? ' disabled' : '') +
      ' style="padding:18px 44px;font-size:24px">' +
      (memoryNeedsSet ? '请先确认 Memory 设置' : '开始游戏') + '</button></div>';

    var chips = $('chips');
    if (!s.board.length) {
      chips.innerHTML = '<span class="note">还没有人加入…</span>';
    } else {
      chips.innerHTML = s.board.map(function (p) {
        return '<span class="chip' + (p.online ? ' on' : '') + '">' +
          esc(p.name) + (p.score ? ' <b style="color:var(--gold)">' + p.score + '</b>' : '') +
          '</span>';
      }).join('');
    }
    var sw = $('swGame');
    if (sw) {
      fetch('/api/games').then(function (r) { return r.json(); }).then(function (d) {
        sw.innerHTML = '<option value="">换个游戏…（玩家不用重扫码，总分接着累加）</option>' +
          (d.games || []).map(function (g) {
            return '<option value="' + g.id + '"' + (g.id === s.game ? ' disabled' : '') +
              '>' + g.emoji + ' ' + g.name + '</option>';
          }).join('');
        sw.onchange = function () {
          if (sw.value) switchToGame(sw.value);
        };
      }).catch(function () { });
    }
    bindMemorySettings(c, s);
    var aiPanel = $('roomAiPanel');
    var aiModel = $('roomAiModel');
    var aiKey = $('roomApiKey');
    if (aiPanel) {
      aiPanel.open = roomAiDraft.open;
      aiPanel.ontoggle = function () { roomAiDraft.open = aiPanel.open; };
    }
    if (aiModel) {
      aiModel.value = roomAiDraft.model || s.settings.model || '';
      aiModel.oninput = function () { roomAiDraft.model = aiModel.value; };
    }
    if (aiKey) {
      aiKey.value = roomAiDraft.key;
      aiKey.oninput = function () { roomAiDraft.key = aiKey.value; };
    }
    $('saveRoomAi').onclick = function () {
      var key = aiKey.value.trim();
      var model = aiModel.value.trim();
      if (!key && !s.api_key_set) {
        toast('请先输入 API Key，或在启动配置中设置');
        aiKey.focus();
        return;
      }
      var payload = { model: model };
      var memoryPayload = collectMemoryPayload(s);
      if (memoryPayload === null) return;
      Object.keys(memoryPayload).forEach(function (name) {
        payload[name] = memoryPayload[name];
      });
      if (key) payload.api_key = key;
      $('saveRoomAi').disabled = true;
      act('settings', payload).then(function () {
        roomAiDraft.model = model;
        roomAiDraft.key = '';
        aiKey.value = '';
        return act('generate');
      }).then(function () {
        toast('房间 AI 设置已保存，正在重新出题');
      }).catch(function () {
        $('saveRoomAi').disabled = false;
        toast('保存失败，请检查服务是否仍在运行');
      });
    };
    $('bGen').onclick = function () {
      if (isMemoryGame(s.game)) $('saveMemorySettings').click();
      else act('generate');
    };
    $('bStart').onclick = function () {
      roomAiDraft.key = '';
      act('start');
    };
    fetch('/api/qr?t=' + encodeURIComponent(joinUrl))
      .then(function (r) { return r.ok ? r.text() : ''; })
      .then(function (svg) {
        if (svg && /^\s*<svg[\s>]/i.test(svg) && $('qr')) $('qr').innerHTML = svg;
        else showQrUnavailable();
      })
      .catch(showQrUnavailable);
  }

  function renderBriefing(c, s) {
    var i = s.info || { i: 0, total: 1, text: '' };
    c.innerHTML =
      '<div class="infocard timed-card">' + ring('rg', true) +
      '<div class="no">信息 ' + i.i + ' / ' + i.total + '</div>' +
      '<div class="txt">' + esc(i.text) + '</div></div>' +
      '<div class="progress"><i style="width:' +
      (i.i / Math.max(1, i.total) * 100) + '%"></i></div>' +
      '<div class="note">记住它们 —— 等下的题目要把好几条信息拼起来才能算出答案</div>' +
      '<button class="btn ghost" id="bSkipB">信息看够了，直接开始答题</button>';
    var armed = 0;
    $('bSkipB').onclick = function () {
      var b = $('bSkipB');
      if (Date.now() < armed) { act('skip_briefing'); return; }
      armed = Date.now() + 4000;
      b.textContent = '再点一次 = 跳过剩下的信息，直接答题';
      b.classList.add('gold');
      setTimeout(function () {
        if (Date.now() >= armed) {
          armed = 0;
          b.textContent = '信息看够了，直接开始答题';
          b.classList.remove('gold');
        }
      }, 4100);
    };
  }

  function ring(id, corner) {
    return '<div class="ring' + (corner ? ' ring-corner' : '') + '" id="' + id +
      '" role="timer" aria-label="本阶段倒计时">' +
      '<div class="num" id="' + id + 'n">–</div></div>';
  }

  function renderQuestion(c, s, revealed) {
    var q = s.q; if (!q) { c.innerHTML = ''; return; }
    var rv = s.reveal, total = Math.max(1, s.count);
    var opts = q.options.map(function (o, i) {
      var cls = 'opt k' + i;
      if (revealed) cls += (i === rv.answer ? ' right' : ' dim');
      var n = revealed ? '<span class="n">' + rv.counts[i] + ' 人</span>' : '';
      return '<div class="' + cls + '"><div class="k">' + 'ABCD'[i] + '</div>' +
        '<div class="v">' + esc(o) + '</div>' + n + '</div>';
    }).join('');

    c.innerHTML =
      '<div class="question-card timed-card">' + ring('rg', true) +
      '<div class="label">第 ' + q.no + ' / ' + q.total + ' 题</div>' +
      '<div class="qtext" style="text-align:left;margin-top:8px">' + esc(q.text) + '</div></div>' +
      '<div class="opts">' + opts + '</div>' +
      (revealed
        ? '<div class="explain"><div class="h">✔ 正确答案：' + 'ABCD'[rv.answer] +
        '　' + esc(q.options[rv.answer]) + '</div>' +
        '<div>' + esc(rv.explain) + '</div>' +
        (rv.uses_texts.length
          ? '<div class="src">用到的信息：' +
          rv.uses.map(function (u, k) {
            return '#' + u + ' ' + esc(rv.uses_texts[k] || '');
          }).join('　｜　') + '</div>'
          : '') + '</div>'
        : '<div class="note">已作答 <b id="ansn">' + q.answered + '</b> / ' +
        total + ' 人</div>');
  }

  /* ---------------- 谁最可能 / 卧底 ---------------- */

  function renderVoteAsk(c, s) {
    var q = s.q || {};
    c.innerHTML =
      '<div class="question-card timed-card">' + ring('rg', true) +
      '<div class="label">第 ' + q.no + ' / ' + q.total + ' 题</div>' +
      '<div class="qtext" style="text-align:left;margin-top:8px">' + esc(q.text) + '</div></div>' +
      '<div class="chips" style="gap:14px">' + (s.candidates || []).map(function (x) {
        return '<span class="chip" style="font-size:26px;padding:14px 26px">' +
          esc(x.name) + '</span>';
      }).join('') + '</div>' +
      '<div class="note">已投 <b id="ansn">' + (q.answered || 0) + '</b> / ' +
      s.count + ' 人　（在手机上选人）</div>';
  }

  function voteBars(rows, top) {
    return rows.map(function (x) {
      var w = top > 0 ? Math.round(x.votes / top * 100) : 0;
      return '<div class="brow' + (x.win ? ' r1' : '') + '">' +
        '<span class="nm">' + esc(x.name) + '</span>' +
        '<span style="flex:2;height:16px;background:#2a1119;border-radius:99px;overflow:hidden">' +
        '<i style="display:block;height:100%;width:' + w + '%;background:' +
        (x.win ? 'var(--gold)' : 'var(--blood)') + '"></i></span>' +
        '<span class="sc" style="width:90px;text-align:right">' + x.votes + ' 票</span></div>';
    }).join('');
  }

  function renderVoteResult(c, s) {
    var r = s.vote_result || { rows: [], top: 0 };
    var win = r.rows.filter(function (x) { return x.win; }).map(function (x) { return x.name; });
    c.innerHTML =
      '<div class="qtext">' + esc(s.q ? s.q.text : '') + '</div>' +
      '<div style="font-size:clamp(30px,4vw,58px);font-weight:900;color:var(--gold)">' +
      '👉 ' + esc(win.join(' 、 ')) + '</div>' +
      '<div class="board">' + voteBars(r.rows, r.top) + '</div>' +
      '<div class="note">投给票王的人 +500，被票最多的人 +300</div>';
  }

  function renderAssign(c, s) {
    c.innerHTML =
      '<div class="label">第 ' + (s.round ? s.round.no + ' / ' + s.round.total : '') + ' 轮</div>' +
      '<div class="infocard timed-card">' + ring('rg', true) +
      '<div class="no">看自己的手机</div>' +
      '<div class="txt">每个人手机上都收到了一个词<br>' +
      '<span style="color:var(--blood)">其中一个人拿到的不一样</span></div></div>' +
      '<div class="note">大屏不会显示任何词 —— 免得剧透</div>';
  }

  function renderDescribe(c, s) {
    c.innerHTML =
      '<div class="label">第 ' + (s.round ? s.round.no + ' / ' + s.round.total : '') + ' 轮 · 轮流描述</div>' +
      '<div class="infocard timed-card">' + ring('rg', true) +
      '<div class="txt">按座位顺序，<br>每人用一句话描述自己的词</div></div>' +
      '<div class="chips" style="gap:12px">' + s.board.map(function (p) {
        return '<span class="chip" style="font-size:24px;padding:12px 22px">' +
          esc(p.name) + '</span>';
      }).join('') + '</div>' +
      '<div class="note">不能直接说出那个词　·　时间到自动进入投票</div>';
  }

  function renderUcReveal(c, s) {
    var r = s.uc_reveal || {};
    c.innerHTML =
      '<div style="font-size:clamp(34px,4.6vw,64px);font-weight:900">' +
      (r.caught ? '🎯 卧底被抓到了' : '🕵️ 卧底藏住了') + '</div>' +
      '<div class="infocard" style="padding:34px"><div class="txt" style="font-size:clamp(24px,3vw,44px)">' +
      '卧底是 <span style="color:var(--blood)">' + esc(r.spy_name) + '</span><br>' +
      '<span style="font-size:.72em;color:var(--muted)">他拿到的是「' + esc(r.spy_word) +
      '」，其他人是「' + esc(r.civ_word) + '」</span></div></div>' +
      '<div class="board">' + voteBars(
        (r.rows || []).map(function (x) {
          return { name: x.name, votes: x.votes, win: x.name === r.voted_out_name };
        }), Math.max.apply(null, [1].concat((r.rows || []).map(function (x) { return x.votes; })))) +
      '</div>';
  }

  /* ---------------- 你画我猜 ---------------- */

  var strokeSince = 0, strokeTimer = null, lastRound = -1;

  function renderDraw(c, s) {
    var d = s.draw;
    if (s.phase === 'reveal' || s.phase === 'scoreboard') {
      if (s.phase === 'reveal') {
        c.innerHTML =
          '<div style="font-size:clamp(30px,4vw,58px);font-weight:900">答案：' +
          '<span style="color:var(--gold)">' + esc(d.answer || '') + '</span></div>' +
          (d.winner_name
            ? '<div class="qtext"><b style="color:var(--ok)">' + esc(d.winner_name) +
              '</b> 猜中了　（' + esc(d.winner_text || '') + '）</div>'
            : '<div class="qtext" style="color:var(--muted)">这幅没人猜出来</div>') +
          '<div class="note">画手 ' + esc(d.drawer_name) + '</div>';
        return;
      }
      return renderBoard(c, s, false);
    }

    if (lastRound !== d.no) {
      lastRound = d.no; strokeSince = 0;
      c.innerHTML =
        '<div class="question-card timed-card">' + ring('rg', true) +
        '<div class="label">第 ' + d.no + ' / ' + d.total + ' 幅</div>' +
        '<div style="font-size:clamp(22px,2.6vw,40px);font-weight:800;margin-top:6px">' +
        '✏️ ' + esc(d.drawer_name) + ' 正在画' +
        '<span style="color:var(--muted);font-size:.6em">　（答案：' +
        esc(d.word || '') + '）</span></div></div>' +
        '<div style="display:flex;gap:22px;align-items:flex-start;width:min(1250px,94vw)">' +
        '<canvas id="hcv" class="hostcv"></canvas>' +
        '<div class="feedbox" id="hfeed"></div></div>';
      var cv = $('hcv');
      cv.width = 1200; cv.height = 864;
      var ctx = cv.getContext('2d');
      ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, cv.width, cv.height);
      ctx.lineCap = 'round'; ctx.lineJoin = 'round';
      ctx.strokeStyle = '#111'; ctx.lineWidth = 7;
      if (strokeTimer) clearInterval(strokeTimer);
      strokeTimer = setInterval(pullStrokes, 120);
    }
    hostFeed(d);
  }

  function pullStrokes() {
    if (!S || S.kind !== 'draw' || S.phase !== 'question') return;
    var cv = $('hcv');
    if (!cv) { clearInterval(strokeTimer); strokeTimer = null; return; }
    fetch('/api/draw?room=' + room + '&since=' + strokeSince)
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var ctx = cv.getContext('2d');
        if (d.n < strokeSince) {        // 画手清空了画布
          ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, cv.width, cv.height);
          strokeSince = 0;
          return;
        }
        (d.strokes || []).forEach(function (st) {
          var p = st.p || [];
          if (p.length < 2) return;
          ctx.beginPath();
          ctx.moveTo(p[0][0] * cv.width, p[0][1] * cv.height);
          for (var i = 1; i < p.length; i++)
            ctx.lineTo(p[i][0] * cv.width, p[i][1] * cv.height);
          ctx.stroke();
        });
        strokeSince = d.n;
      }).catch(function () { });
  }

  function hostFeed(d) {
    var f = $('hfeed');
    if (!f) return;
    f.innerHTML = (d.guesses || []).slice(-10).reverse().map(function (g) {
      return '<div class="gline"><b>' + esc(g.name) + '</b>：' + esc(g.text) +
        ' <button class="gok" data-g="' + g.id + '">判对</button></div>';
    }).join('') || '<div class="note">等大家猜…</div>';
    Array.prototype.forEach.call(f.querySelectorAll('.gok'), function (b) {
      b.onclick = function () {
        act('judge', { guess_id: parseInt(b.getAttribute('data-g'), 10) });
      };
    });
  }

  function renderBoard(c, s, final) {
    var rows = s.board.map(function (p) {
      return '<div class="brow r' + p.rank + (p.online ? '' : ' off') + '">' +
        '<span class="rk">' + (p.rank === 1 ? '👑' : p.rank) + '</span>' +
        '<span class="nm">' + esc(p.name) + '</span>' +
        '<span class="gn">' + (p.gain ? '+' + p.gain : '') + '</span>' +
        '<span class="sc">' + p.score + '</span></div>';
    }).join('') || '<div class="note">还没有人参与</div>';

    if (final) {
      var champ = s.board[0];
      var multi = (s.played && s.played.length) ||
        (s.total_board || []).some(function (b) { return b.total !== b.score; });
      var totalRows = multi ? (s.total_board || []).map(function (p) {
        return '<div class="brow r' + p.rank + '" style="font-size:20px;padding:11px 18px">' +
          '<span class="rk">' + (p.rank === 1 ? '👑' : p.rank) + '</span>' +
          '<span class="nm">' + esc(p.name) + '</span>' +
          '<span class="sc">' + p.total + '</span></div>';
      }).join('') : '';
      c.innerHTML =
        '<div class="brand" style="font-size:56px">本 局 结 束</div>' +
        (champ ? '<div style="font-size:40px;font-weight:900">👑 ' +
          esc(champ.name) + '　<span style="color:var(--gold)">' +
          champ.score + ' 分</span></div>' : '') +
        '<div class="board">' + rows + '</div>' +
        (multi ? '<div class="label" style="margin-top:10px">整晚总分榜（' +
          esc((s.played || []).concat([s.game_name]).join(' + ')) + '）</div>' +
          '<div class="board">' + totalRows + '</div>' : '') +
        nextTag(s) +
        '<div style="display:flex;gap:14px">' +
        '<button class="btn" id="bAgain">' +
        (s.next_ready ? '再来一局（题已备好）' : '换一套题，再来一局') + '</button>' +
        '<button class="btn ghost" id="bBack">回大厅</button></div>';
      $('bAgain').onclick = function () { act('lobby').then(function () { act('generate'); }); };
      $('bBack').onclick = function () { act('lobby'); };
    } else {
      c.innerHTML =
        '<div class="label">第 ' + s.q_done + ' 题结束 · 还剩 ' + s.q_left + ' 题</div>' +
        '<div class="board">' + rows + '</div>' +
        (s.settings.auto ? '<div class="note">马上进入下一题…</div>'
          : '<button class="btn gold" id="bGo">下一题 →</button>');
      if (!s.settings.auto) $('bGo').onclick = function () { act('skip'); };
    }
  }

  /* ---------------- 倒计时动画 ---------------- */

  setInterval(function () {
    if (!S) return;
    var n = $('rgn'), timer = $('rg');
    if (n) {
      var ms = remain();
      if (ms === null) {
        n.textContent = S.paused ? '⏸' : '–';
        if (timer) timer.style.setProperty('--timer-progress', '0%');
      }
      else {
        var sec = Math.ceil(ms / 1000);
        n.textContent = sec;
        if (timer) {
          var frac = Math.min(1, ms / (S.phase_sec * 1000 || 1));
          timer.style.setProperty('--timer-progress', Math.min(99, frac * 100) + '%');
          timer.classList.toggle('urgent', sec <= 5);
          timer.setAttribute('aria-label', '剩余 ' + sec + ' 秒');
        }
      }
    }
    var a = $('ansn');
    if (a && S.q) a.textContent = S.q.answered;

    var g = $('genSec');
    if (g && S.gen && S.gen.since) {
      var el = Math.round((Date.now() + offset - S.gen.since) / 1000);
      g.textContent = '　已等 ' + el + ' 秒' +
        (el > 20 ? '（DeepSeek 要先想一会儿，通常 1~2 分钟）' : '');
    }
    var ps = $('preSec');
    if (ps && S.next_gen && S.next_gen.since) {
      ps.textContent = '　' +
        Math.round((Date.now() + offset - S.next_gen.since) / 1000) + ' 秒';
    }
  }, 100);
})();
