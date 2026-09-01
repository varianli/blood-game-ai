/* 手机端 */
(function () {
  var $ = function (id) { return document.getElementById(id); };
  var room = null, pid = null, offset = 0, S = null, lastV = -1;
  var localChoice = null, localQ = -1, localSetRev = -1;

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
  function buzz(ms) { try { navigator.vibrate && navigator.vibrate(ms); } catch (e) { } }

  /* ---------------- 加入 ---------------- */

  var qs = new URLSearchParams(location.search);
  if (qs.get('room')) $('jRoom').value = qs.get('room');
  try {
    var saved = JSON.parse(localStorage.getItem('xzyx_player') || 'null');
    if (saved) {
      if (!$('jRoom').value) $('jRoom').value = saved.room || '';
      $('jName').value = saved.name || '';
    }
  } catch (e) { }

  function loadPicks() {
    var code = $('jRoom').value.trim();
    if (code.length < 4) return;
    fetch('/api/state?room=' + encodeURIComponent(code) + '&since=-1')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (s) {
        if (!s || s.error) { $('jMsg').textContent = '找不到这个房间'; return; }
        $('jMsg').textContent = '房间在线 · 已有 ' + s.count + ' 人';
        var names = (s.settings && s.settings.names) || [];
        $('jPick').innerHTML = names.map(function (n) {
          return '<span class="chip" data-n="' + esc(n) + '">' + esc(n) + '</span>';
        }).join('');
        Array.prototype.forEach.call($('jPick').children, function (el) {
          el.onclick = function () { $('jName').value = el.getAttribute('data-n'); };
        });
      }).catch(function () { });
  }
  $('jRoom').addEventListener('input', loadPicks);
  loadPicks();

  function enter(code, name, reuse) {
    return post('/api/join', { room: code, name: name, pid: reuse })
      .then(function (r) {
        if (r.error) throw new Error('no_room');
        room = r.room; pid = r.pid;
        try {
          localStorage.setItem('xzyx_player',
            JSON.stringify({ room: room, pid: pid, name: r.name }));
        } catch (e) { }
        $('join').classList.add('hide');
        $('app').classList.remove('hide');
        $('pName').textContent = r.name;
        poll();
        return r;
      });
  }

  $('jGo').onclick = function () {
    var code = $('jRoom').value.trim(), name = $('jName').value.trim();
    if (code.length < 4) { $('jMsg').textContent = '房间号是 4 位数字'; return; }
    if (!name) { $('jMsg').textContent = '写个名字吧'; return; }
    var old = null;
    try { old = JSON.parse(localStorage.getItem('xzyx_player') || 'null'); } catch (e) { }
    enter(code, name, (old && old.room === code) ? old.pid : null)
      .catch(function (e) {
        $('jMsg').textContent = e.message === 'no_room'
          ? '加入失败：房间不存在' : '连不上，检查 Wi-Fi';
      });
  };

  // 之前进过就直接回去，不用再点一次「进入房间」。
  // 手机锁屏、切后台、被系统杀掉重开，回来都能接着玩，分数不丢。
  (function autoRejoin() {
    var old = null;
    try { old = JSON.parse(localStorage.getItem('xzyx_player') || 'null'); } catch (e) { }
    if (!old || !old.room || !old.pid) return;
    var want = qs.get('room');
    if (want && want !== old.room) return;      // 扫了另一个房间的码就别自动回去
    $('jMsg').textContent = '正在回到房间 ' + old.room + '…';
    enter(old.room, old.name || '', old.pid).catch(function () {
      $('jMsg').textContent = '之前的房间已经关了，重新进一个吧';
    });
  })();

  // 万一真的想换个人玩
  $('pSwitch').onclick = function () {
    if (!confirm('换个名字重新进？当前这个名字的分数会留在原地。')) return;
    try { localStorage.removeItem('xzyx_player'); } catch (e) { }
    location.href = '/p?room=' + room;
  };

  /* ---------------- 轮询 ---------------- */

  function poll() {
    fetch('/api/state?room=' + room + '&pid=' + pid + '&since=' + lastV)
      .then(function (r) { return r.json(); })
      .then(function (s) {
        if (s.error) { setTimeout(poll, 2000); return; }
        offset = s.now - Date.now();
        var prev = S; S = s;
        if (s.v !== lastV) { lastV = s.v; render(prev); }
        setTimeout(poll, 30);
      })
      .catch(function () { setTimeout(poll, 1200); });
  }

  function remain() {
    if (!S || !S.deadline) return null;
    return Math.max(0, S.deadline - (Date.now() + offset));
  }

  function cornerTimer(id) {
    return '<div class="ring ring-corner phone-ring" id="' + id +
      '" role="timer" aria-label="本阶段倒计时">' +
      '<div class="num" id="' + id + 'n">–</div></div>';
  }

  /* ---------------- 作答 ---------------- */

  function choose(i) {
    if (!S || S.phase !== 'question') return;
    if (S.you && S.you.choice !== null && S.you.choice !== undefined) return;
    if (localQ === S.q.no && localChoice !== null) return;
    localQ = S.q.no; localChoice = i;
    buzz(30);
    render();
    post('/api/answer', { room: room, pid: pid, q: S.q.no - 1, choice: i });
  }

  /* ---------------- 渲染 ---------------- */

  function render(prev) {
    var s = S, m = $('pMain');
    if (localSetRev !== s.set_rev) {
      localSetRev = s.set_rev;
      localChoice = null;
      localQ = -1;
      pad = null;
    }
    if (s.you) {
      $('pName').textContent = s.you.name;
      $('pScore').textContent = s.you.score;
      $('pRank').textContent = s.count ? ('第 ' + s.you.rank + ' / ' + s.count) : '—';
    }
    if (s.q && localQ !== s.q.no) { localChoice = null; localQ = -1; }

    if (s.phase === 'lobby') {
      m.innerHTML = '<div class="pinfo">已进入房间 <b>' + esc(s.room) + '</b><br>' +
        '<span style="font-size:.6em;color:var(--muted)">等主持人开始…' +
        '（现在 ' + s.count + ' 人）</span></div>' +
        '<div class="note" style="text-align:center">' +
        '等下大屏会一条一条放信息，记住它们。</div>';
      return;
    }

    if (s.phase === 'briefing') {
      var i = s.info || { i: 0, total: 1, text: '' };
      m.innerHTML = '<div class="label" style="text-align:center">信息 ' +
        i.i + ' / ' + i.total + '</div>' +
        '<div class="pinfo timed-card">' + cornerTimer('prg') +
        esc(i.text) + '</div>' +
        '<div class="note" style="text-align:center">记住 —— 等下要用它算题</div>';
      return;
    }

    // ---- 谁最可能 / 卧底找茬：投票选人 ----
    if (s.kind === 'vote' || s.kind === 'undercover') {
      if (renderVote(m, s, prev)) return;
    }
    // ---- 你画我猜 ----
    if (s.kind === 'draw') {
      if (renderDraw(m, s, prev)) return;
    }

    if (s.phase === 'question' || s.phase === 'reveal') {
      var q = s.q, rv = s.reveal;
      var mine = (s.you && s.you.choice !== null && s.you.choice !== undefined)
        ? s.you.choice : localChoice;
      var revealed = (s.phase === 'reveal');

      if (revealed && prev && prev.phase === 'question') {
        buzz(s.you && s.you.correct ? [40, 60, 40] : 200);
      }

      var head = '<div class="phone-question-card timed-card">' + cornerTimer('prg') +
        '<div class="label">第 ' + q.no + ' / ' + q.total + ' 题</div>' +
        '<div class="pq">' + esc(q.text) + '</div></div>';

      var opts = q.options.map(function (o, k) {
        var cls = 'popt k' + k;
        if (revealed) cls += (k === rv.answer ? ' right' : ' dim');
        else if (mine !== null && mine !== undefined) cls += (k === mine ? ' mine' : ' dim');
        return '<button class="' + cls + '" data-k="' + k + '">' +
          '<span class="k">' + 'ABCD'[k] + '</span><span>' + esc(o) + '</span></button>';
      }).join('');

      var foot = '';
      if (revealed) {
        var got = s.you && s.you.correct;
        var answered = s.you && s.you.choice !== null && s.you.choice !== undefined;
        foot = '<div class="bigres ' + (got ? 'win' : 'lose') + '">' +
          '<div class="icon">' + (got ? '✓' : (answered ? '✗' : '⏱')) + '</div>' +
          '<div class="t">' + (got ? '答对了！' : (answered ? '答错了' : '没来得及')) + '</div>' +
          (got ? '<div class="p">+' + s.you.gain + ' 分' +
            (s.you.streak > 1 ? '　🔥 连对 ' + s.you.streak : '') + '</div>' : '') +
          '<div class="note" style="margin-top:8px">正确答案 ' + 'ABCD'[rv.answer] +
          '：' + esc(q.options[rv.answer]) + '</div></div>';
      } else if (mine !== null && mine !== undefined) {
        foot = '<div class="note" style="text-align:center">' +
          '已锁定 <b style="color:var(--gold)">' + 'ABCD'[mine] + '</b>　等其他人…</div>';
      } else {
        foot = '<div class="note" style="text-align:center">选一个答案</div>';
      }

      m.innerHTML = head + '<div class="popts">' + opts + '</div>' + foot;
      if (!revealed && (mine === null || mine === undefined)) {
        Array.prototype.forEach.call(m.querySelectorAll('.popt'), function (b) {
          b.onclick = function () { choose(parseInt(b.getAttribute('data-k'), 10)); };
        });
      }
      return;
    }

    if (s.phase === 'scoreboard' || s.phase === 'final') {
      var top = s.board.slice(0, 8).map(function (p) {
        var me = s.you && p.pid === s.you.pid;
        return '<div class="brow r' + p.rank + '" style="font-size:17px;padding:10px 14px' +
          (me ? ';border-color:var(--gold)' : '') + '">' +
          '<span class="rk">' + (p.rank === 1 ? '👑' : p.rank) + '</span>' +
          '<span class="nm">' + esc(p.name) + (me ? ' （你）' : '') + '</span>' +
          '<span class="sc">' + p.score + '</span></div>';
      }).join('');
      m.innerHTML =
        (s.phase === 'final'
          ? '<div class="brand" style="font-size:30px;text-align:center">本 局 结 束</div>'
          : '<div class="label" style="text-align:center">第 ' + s.q_done +
          ' 题结束 · 还剩 ' + s.q_left + ' 题</div>') +
        (s.you ? '<div class="bigres ' + (s.you.rank === 1 ? 'win' : 'lose') +
          '" style="padding:18px"><div class="t">第 ' + s.you.rank + ' 名</div>' +
          '<div class="p">' + s.you.score + ' 分</div></div>' : '') +
        '<div class="board" style="width:100%">' + top + '</div>';
      return;
    }

    m.innerHTML = '<div class="note" style="text-align:center">等待中…</div>';
  }

  /* ---------------- 谁最可能 / 卧底找茬 ---------------- */

  function vote(target) {
    if (!S || S.phase !== 'question') return;
    if (S.you && S.you.target) return;
    buzz(30);
    post('/api/submit', { room: room, pid: pid, payload: { target: target } });
  }

  function renderVote(m, s, prev) {
    var you = s.you || {};

    // 卧底：发词阶段，只有自己能看到自己的词
    if (s.phase === 'assign') {
      m.innerHTML = '<div class="label" style="text-align:center">第 ' +
        (s.round ? s.round.no + ' / ' + s.round.total : '1') + ' 轮</div>' +
        '<div class="pinfo timed-card">' + cornerTimer('prg') +
        '你拿到的词是<br><b style="font-size:1.5em;color:var(--gold)">' +
        esc(you.word || '…') + '</b></div>' +
        '<div class="note" style="text-align:center">' +
        '别给别人看。等下轮流描述它，但不能直接说出来。<br>' +
        '有一个人拿到的词跟你不一样。</div>';
      return true;
    }
    if (s.phase === 'describe') {
      m.innerHTML = '<div class="pinfo timed-card" style="font-size:1.1em">' +
        cornerTimer('prg') + '你的词：<b style="color:var(--gold)">' +
        esc(you.word || '') + '</b></div>' +
        '<div class="note" style="text-align:center">' +
        '按座位顺序，每人用一句话描述自己的词。<br>说得太准会被卧底抄，说得太含糊会被当成卧底。</div>';
      return true;
    }

    if (s.phase === 'question' && s.candidates) {
      var mine = you.target;
      m.innerHTML = '<div class="phone-question-card timed-card">' +
        cornerTimer('prg') + '<div class="pq">' +
        esc(s.q ? s.q.text : '投票') + '</div></div>' +
        '<div class="votegrid">' + s.candidates.map(function (c) {
          var me = (you.pid === c.pid);
          return '<button class="vopt' + (mine === c.pid ? ' mine' : '') +
            (mine && mine !== c.pid ? ' dim' : '') + '" data-p="' + c.pid + '"' +
            (me && s.kind === 'undercover' ? ' disabled' : '') + '>' +
            esc(c.name) + (me ? '<span class="mesmall">（你）</span>' : '') + '</button>';
        }).join('') + '</div>' +
        (mine ? '<div class="note" style="text-align:center">已投给 <b style="color:var(--gold)">' +
          esc((s.candidates.filter(function (c) { return c.pid === mine; })[0] || {}).name || '') +
          '</b>　等其他人…</div>'
          : '<div class="note" style="text-align:center">选一个人</div>');
      if (!mine) {
        Array.prototype.forEach.call(m.querySelectorAll('.vopt'), function (b) {
          if (!b.disabled) b.onclick = function () { vote(b.getAttribute('data-p')); };
        });
      }
      return true;
    }

    if (s.phase === 'reveal') {
      if (s.kind === 'undercover' && s.uc_reveal) {
        var r = s.uc_reveal, wasSpy = you.was_spy;
        m.innerHTML = '<div class="bigres ' + (s.you && s.you.gain ? 'win' : 'lose') + '">' +
          '<div class="t">' + (wasSpy ? '你是卧底' : '你是平民') + '</div>' +
          '<div class="note" style="margin-top:8px">卧底是 <b style="color:var(--gold)">' +
          esc(r.spy_name) + '</b>（' + esc(r.spy_word) + '）<br>' +
          '大家的词是 ' + esc(r.civ_word) + '</div>' +
          '<div class="note" style="margin-top:6px">' +
          (r.voted_out_name ? '票出了 ' + esc(r.voted_out_name) : '票数打平，没人出局') +
          ' —— ' + (r.caught ? '卧底被抓到了' : '卧底藏住了') + '</div>' +
          (you.gain ? '<div class="p">+' + you.gain + ' 分</div>' : '') + '</div>';
        return true;
      }
      if (s.kind === 'vote' && s.vote_result) {
        var rows = s.vote_result.rows.map(function (x) {
          return '<div class="brow' + (x.win ? ' r1' : '') + '" style="font-size:16px;padding:9px 13px">' +
            '<span class="nm">' + esc(x.name) + '</span>' +
            '<span class="sc">' + x.votes + ' 票</span></div>';
        }).join('');
        m.innerHTML = '<div class="pq">' + esc(s.q ? s.q.text : '') + '</div>' +
          '<div class="board" style="width:100%">' + rows + '</div>' +
          (you.gain ? '<div class="bigres win" style="padding:16px">' +
            '<div class="p">+' + you.gain + ' 分</div></div>' : '');
        return true;
      }
    }
    return false;
  }

  /* ---------------- 你画我猜 ---------------- */

  var pad = null;

  function renderDraw(m, s, prev) {
    var d = s.draw, you = s.you || {};
    if (!d) return false;
    var drawKey = s.set_rev + ':' + d.no;

    if (s.phase === 'question' && you.is_drawer) {
      if (!pad || pad.key !== drawKey) {
        m.innerHTML = '<div class="phone-question-card timed-card">' +
          cornerTimer('prg') + '<div class="label">该你画了 · 第 ' +
          d.no + ' / ' + d.total + ' 幅</div>' +
          '<div class="drawword">' + esc(d.word || '') + '</div></div>' +
          '<canvas id="cv" class="cv"></canvas>' +
          '<div style="display:flex;gap:10px">' +
          '<button class="btn ghost" id="undo" style="flex:1">撤一笔</button>' +
          '<button class="btn ghost" id="clr" style="flex:1">全清</button></div>' +
          '<div id="gfeed" class="gfeed"></div>';
        setupPad(drawKey);
      }
      renderFeed(d);
      return true;
    }

    if (s.phase === 'question') {
      m.innerHTML = '<div class="phone-question-card timed-card">' +
        cornerTimer('prg') + '<div class="label">' + esc(d.drawer_name) +
        ' 正在画 · 第 ' + d.no + ' / ' + d.total + ' 幅</div>' +
        '<div class="note" style="margin-top:7px">看大屏，想到什么直接打上去</div></div>' +
        '<div id="gfeed" class="gfeed"></div>' +
        '<div style="display:flex;gap:8px">' +
        '<input class="field" id="gin" maxlength="20" placeholder="猜什么？" autocomplete="off">' +
        '<button class="btn" id="gsend">发</button></div>';
      var gin = $('gin');
      var send = function () {
        var t = gin.value.trim();
        if (!t) return;
        gin.value = '';
        post('/api/submit', { room: room, pid: pid, payload: { kind: 'guess', text: t } });
      };
      $('gsend').onclick = send;
      gin.onkeydown = function (e) { if (e.key === 'Enter') send(); };
      renderFeed(d);
      return true;
    }

    if (s.phase === 'reveal') {
      pad = null;
      m.innerHTML = '<div class="bigres ' + (you.gain ? 'win' : 'lose') + '">' +
        '<div class="t">答案：' + esc(d.answer || '') + '</div>' +
        (d.winner_name
          ? '<div class="note" style="margin-top:8px"><b style="color:var(--gold)">' +
            esc(d.winner_name) + '</b> 猜中了（' + esc(d.winner_text || '') + '）</div>'
          : '<div class="note" style="margin-top:8px">这幅没人猜出来</div>') +
        (you.gain ? '<div class="p">+' + you.gain + ' 分</div>' : '') + '</div>';
      return true;
    }
    return false;
  }

  function renderFeed(d) {
    var f = $('gfeed');
    if (!f) return;
    f.innerHTML = (d.guesses || []).slice(-8).map(function (g) {
      var mine = S.you && g.pid === S.you.pid;
      return '<div class="gline' + (mine ? ' mine' : '') + '"><b>' + esc(g.name) +
        '</b>：' + esc(g.text) +
        (S.you && S.you.is_drawer
          ? ' <button class="gok" data-g="' + g.id + '">判对</button>' : '') +
        '</div>';
    }).join('') || '<div class="note">还没人猜…</div>';
    Array.prototype.forEach.call(f.querySelectorAll('.gok'), function (b) {
      b.onclick = function () {
        post('/api/submit', {
          room: room, pid: pid,
          payload: { kind: 'judge', guess_id: parseInt(b.getAttribute('data-g'), 10) }
        });
      };
    });
  }

  function setupPad(drawKey) {
    var cv = $('cv');
    if (!cv) return;
    var rect = cv.getBoundingClientRect();
    cv.width = Math.round(rect.width * 2);
    cv.height = Math.round(rect.width * 1.35 * 2);
    cv.style.height = Math.round(rect.width * 1.35) + 'px';
    var ctx = cv.getContext('2d');
    ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, cv.width, cv.height);
    ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    ctx.strokeStyle = '#111'; ctx.lineWidth = 6;
    pad = { key: drawKey, ctx: ctx, cv: cv, pts: [], all: [] };

    function xy(e) {
      var r = cv.getBoundingClientRect();
      var t = e.touches ? e.touches[0] : e;
      return [(t.clientX - r.left) / r.width, (t.clientY - r.top) / r.height];
    }
    function down(e) { e.preventDefault(); pad.pts = [xy(e)]; }
    function move(e) {
      if (!pad.pts.length) return;
      e.preventDefault();
      var p = xy(e), q = pad.pts[pad.pts.length - 1];
      ctx.beginPath();
      ctx.moveTo(q[0] * cv.width, q[1] * cv.height);
      ctx.lineTo(p[0] * cv.width, p[1] * cv.height);
      ctx.stroke();
      pad.pts.push(p);
    }
    function up() {
      if (pad.pts.length > 1) {
        var st = { p: pad.pts.map(function (a) { return [Math.round(a[0] * 1000) / 1000, Math.round(a[1] * 1000) / 1000]; }) };
        pad.all.push(st);
        post('/api/submit', { room: room, pid: pid, payload: { kind: 'stroke', stroke: st } });
      }
      pad.pts = [];
    }
    cv.addEventListener('touchstart', down, { passive: false });
    cv.addEventListener('touchmove', move, { passive: false });
    cv.addEventListener('touchend', up);
    cv.addEventListener('mousedown', down);
    cv.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);

    $('clr').onclick = function () {
      ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, cv.width, cv.height);
      pad.all = [];
      post('/api/submit', { room: room, pid: pid, payload: { kind: 'clear' } });
    };
    $('undo').onclick = function () {
      pad.all.pop();
      ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, cv.width, cv.height);
      pad.all.forEach(function (st) { drawStroke(ctx, cv, st); });
      post('/api/submit', { room: room, pid: pid, payload: { kind: 'clear' } });
      pad.all.forEach(function (st) {
        post('/api/submit', { room: room, pid: pid, payload: { kind: 'stroke', stroke: st } });
      });
    };
  }

  function drawStroke(ctx, cv, st) {
    var p = st.p || [];
    if (p.length < 2) return;
    ctx.beginPath();
    ctx.moveTo(p[0][0] * cv.width, p[0][1] * cv.height);
    for (var i = 1; i < p.length; i++) ctx.lineTo(p[i][0] * cv.width, p[i][1] * cv.height);
    ctx.stroke();
  }

  /* ---------------- 进度条 ---------------- */

  setInterval(function () {
    if (!S) return;
    var ms = remain(), bar = $('pBar'), timer = $('prg'), timerNum = $('prgn');
    if (ms === null || !S.phase_sec) {
      bar.style.width = '0%';
      if (timer) timer.style.setProperty('--timer-progress', '0%');
      if (timerNum) timerNum.textContent = S.paused ? '⏸' : '–';
      return;
    }
    var frac = Math.max(0, Math.min(1, ms / (S.phase_sec * 1000)));
    var sec = Math.ceil(ms / 1000);
    bar.style.width = (frac * 100) + '%';
    bar.style.background = (S.phase === 'question' && ms < 5000) ? '#e01e37' : '#f2c14e';
    if (timer) {
      timer.style.setProperty('--timer-progress', Math.min(99, frac * 100) + '%');
      timer.classList.toggle('urgent', sec <= 5);
      timer.setAttribute('aria-label', '剩余 ' + sec + ' 秒');
    }
    if (timerNum) timerNum.textContent = sec;
  }, 100);
})();
