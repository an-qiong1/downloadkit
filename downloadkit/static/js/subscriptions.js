// ========== 创作者订阅 ==========
// 产品核心能力：订阅抖音创作者，自动发现并下载他的新作品。
//
// 后端接口（server.py）：
//   GET    /api/subscriptions              列表 + 总览
//   POST   /api/subscriptions              添加（传主页链接）
//   POST   /api/subscriptions/preview      预览（不入库）
//   POST   /api/subscriptions/{sec}/toggle 暂停/恢复
//   POST   /api/subscriptions/{sec}/scope  下载范围（P2-1：仅新作品/往回补N/全部）
//   DELETE /api/subscriptions/{sec}        取消订阅
//   GET    /api/subscriptions/{sec}        详情 + 已发现作品
(function () {
  'use strict';

  var API = '/api/subscriptions';

  function el(id) { return document.getElementById(id); }

  function showMsg(text, kind) {
    var m = el('sub-msg');
    if (!m) return;
    if (!text) { m.style.display = 'none'; m.textContent = ''; return; }
    m.style.display = 'block';
    m.textContent = text;
    var bg = 'var(--bg-tertiary)', fg = 'var(--text-secondary)';
    if (kind === 'error') { bg = 'rgba(220,38,38,0.10)'; fg = 'var(--error)'; }
    else if (kind === 'ok') { bg = 'rgba(22,163,74,0.10)'; fg = 'var(--success)'; }
    else if (kind === 'busy') { fg = 'var(--warning)'; }
    m.style.background = bg;
    m.style.color = fg;
  }

  function setBusy(on) {
    var b1 = el('sub-add-btn'), b2 = el('sub-preview-btn');
    if (b1) { b1.disabled = on; b1.style.opacity = on ? '0.6' : '1'; }
    if (b2) { b2.disabled = on; b2.style.opacity = on ? '0.6' : '1'; }
  }

  // ---------- 渲染 ----------

  function fmtWhen(s) {
    if (!s) return '还没检查过';
    // 后端给的是 'YYYY-MM-DD HH:MM:SS'
    var d = new Date(s.replace(/-/g, '/'));
    if (isNaN(d.getTime())) return s;
    var diff = (Date.now() - d.getTime()) / 1000;   // 正 = 过去，负 = 未来

    // 未来时间（「下次检查」）必须单独处理。
    // 早期没分支，diff 为负直接落到 `diff < 60` 那档，
    // 下次检查时间被显示成「刚刚」，读起来像已经跑过了。
    if (diff < 0) {
      var left = -diff;
      if (left < 60) return '不到 1 分钟后';
      if (left < 3600) return Math.ceil(left / 60) + ' 分钟后';
      if (left < 86400) return Math.ceil(left / 3600) + ' 小时后';
      return Math.ceil(left / 86400) + ' 天后';
    }

    if (diff < 60) return '刚刚';
    if (diff < 3600) return Math.floor(diff / 60) + ' 分钟前';
    if (diff < 86400) return Math.floor(diff / 3600) + ' 小时前';
    if (diff < 86400 * 30) return Math.floor(diff / 86400) + ' 天前';
    return s.slice(0, 10);
  }

  function renderStats(s) {
    var box = el('sub-stats');
    if (!box || !s) return;
    var enabled = s.enabled || 0;
    box.innerHTML =
      '<span>已订阅 <b>' + (s.creators || 0) + '</b> 位</span>' +
      '<span>轮询中 <b>' + enabled + '</b> 位</span>' +
      '<span>已发现作品 <b>' + (s.works_seen || 0) + '</b> 个</span>' +
      (enabled
        ? '<button class="btn btn-primary" id="sub-check-all" style="padding:4px 12px;font-size:12px;margin-left:auto">' +
          '<i data-lucide="refresh-cw"></i> 检查全部更新</button>'
        : '<span style="color:var(--text-tertiary);margin-left:auto">没有可检查的订阅</span>');
  }

  // ---------- 下载范围（P2-1） ----------
  // 一个下拉 + 一个条件出现的数字框，都放在卡片的元信息行里。
  // data-scope 记着「服务端当前的值」，改失败时靠它回滚显示。
  function scopeSelect(c) {
    var scope = c.download_scope || 'only_new';
    var n = parseInt(c.scope_param, 10);
    if (!(n >= 1)) n = 3;
    var opts = [
      ['only_new', '仅新作品'],
      ['backfill_n', '往回补 N 个'],
      ['all', '全部补下']
    ].map(function (o) {
      return '<option value="' + o[0] + '"' + (scope === o[0] ? ' selected' : '') + '>' +
        o[1] + '</option>';
    }).join('');
    return '<select class="sub-scope" data-sec="' + escAttr(c.sec_uid) +
      '" data-scope="' + escAttr(scope) + '" title="下载范围（下次检查生效）">' +
      opts + '</select>' +
      '<input class="sub-scope-n" type="number" min="1" max="9999" step="1" value="' +
      n + '" data-sec="' + escAttr(c.sec_uid) + '" title="往回补几个"' +
      (scope === 'backfill_n' ? '' : ' style="display:none"') + '>';
  }

  function creatorCard(c) {
    var paused = !c.enabled;
    var avatar = c.avatar
      ? '<img src="' + escAttr(c.avatar) + '" referrerpolicy="no-referrer" ' +
        'style="width:44px;height:44px;border-radius:50%;object-fit:cover;background:var(--bg-tertiary);flex-shrink:0">'
      : '<div style="width:44px;height:44px;border-radius:50%;background:var(--bg-tertiary);' +
        'display:flex;align-items:center;justify-content:center;flex-shrink:0;font-size:18px">👤</div>';

    var link = c.home_url
      ? '<a href="' + escAttr(c.home_url) + '" target="_blank" rel="noopener" ' +
        'style="color:inherit;text-decoration:none;display:flex;gap:12px;align-items:center">' + avatar +
        '<div style="min-width:0"><div style="font-size:14px;font-weight:500">' +
        escHtml(c.nickname || '(未获取昵称)') + '</div>' +
        '<div style="font-size:11px;color:var(--text-tertiary);overflow:hidden;' +
        'text-overflow:ellipsis;white-space:nowrap;max-width:320px">' +
        escHtml(c.sec_uid) + '</div></div></a>'
      : '<div style="display:flex;gap:12px;align-items:center">' + avatar +
        '<div><div style="font-size:14px;font-weight:500">' +
        escHtml(c.nickname || '(未获取昵称)') + '</div></div></div>';

    return '<div data-sec="' + escAttr(c.sec_uid) + '" style="display:flex;gap:12px;' +
      'align-items:center;padding:12px 14px;border:1px solid var(--border);' +
      'border-radius:8px;margin-bottom:8px;background:var(--bg-secondary);' +
      (paused ? 'opacity:0.6;' : '') + '">' +
      '<div style="flex:1;min-width:0">' + link +
      '<div style="margin-top:6px;font-size:11px;color:var(--text-secondary);display:flex;' +
      'gap:12px;flex-wrap:wrap">' +
      '<span>作品 ' + (c.works_count || 0) + ' 个</span>' +
      '<span>上次检查 ' + fmtWhen(c.last_checked) + '</span>' +
      '<span class="sub-scope-cell">范围 ' + scopeSelect(c) + '</span>' +
      (paused ? '<span style="color:var(--warning)">已暂停</span>' : '') +
      '</div></div>' +
      '<div style="display:flex;gap:6px;flex-shrink:0">' +
      (paused ? '' :
        '<button class="btn btn-primary" data-act="check" data-sec="' + escAttr(c.sec_uid) + '"' +
        ' style="padding:5px 10px;font-size:12px">检查更新</button>') +
      '<button class="btn btn-secondary" data-act="toggle" data-sec="' + escAttr(c.sec_uid) + '"' +
      ' data-enabled="' + (c.enabled ? 1 : 0) + '" style="padding:5px 10px;font-size:12px">' +
      (paused ? '恢复' : '暂停') + '</button>' +
      '<button class="btn btn-secondary" data-act="detail" data-sec="' + escAttr(c.sec_uid) + '"' +
      ' style="padding:5px 10px;font-size:12px">已发现</button>' +
      '<button class="btn btn-secondary" data-act="remove" data-sec="' + escAttr(c.sec_uid) + '"' +
      ' style="padding:5px 10px;font-size:12px;color:var(--error)">删除</button>' +
      '</div></div>';
  }

  function renderList(creators) {
    var box = el('sub-list');
    if (!box) return;
    if (!creators || !creators.length) {
      box.innerHTML = '<div style="text-align:center;padding:40px 20px;color:var(--text-secondary);' +
        'font-size:13px;border:1px dashed var(--border);border-radius:8px">' +
        '还没有订阅任何创作者<br><span style="font-size:12px;color:var(--text-tertiary)">' +
        '在上面粘贴创作者主页链接就能订阅</span></div>';
      return;
    }
    box.innerHTML = creators.map(creatorCard).join('');
  }

  // ---------- 自动检查（A5） ----------

  var POLLER_API = API + '/poller';

  function fmtInterval(min) {
    if (min >= 120 && min % 60 === 0) return (min / 60) + ' 小时';
    return min + ' 分钟';
  }

  function renderPoller(p) {
    var tog = el('sub-poller-toggle');
    var opts = el('sub-poller-options');
    var box = el('sub-poller-status');
    if (!tog || !p) return;

    // 回写前确认没聚焦：否则用户正点着下拉框时列表刷新会把选择弹掉
    if (document.activeElement !== tog) tog.checked = !!p.enabled;
    if (opts) opts.style.display = p.enabled ? 'block' : 'none';

    var iv = el('sub-poller-interval');
    if (iv && document.activeElement !== iv) iv.value = String(p.interval_minutes);
    var mx = el('sub-poller-maxnew');
    if (mx && document.activeElement !== mx) mx.value = String(p.max_new_per_check);

    // 双模式（P2-2）：方式决定显示「检查间隔」还是「每天时刻」
    var isDaily = p.mode === 'daily_at';
    var md = el('sub-poller-mode');
    if (md && document.activeElement !== md) md.value = isDaily ? 'daily_at' : 'interval';
    var dv = el('sub-poller-daily');
    if (dv && document.activeElement !== dv) dv.value = p.daily_at || '09:00';
    var ivLabel = el('sub-poller-interval-label');
    if (ivLabel) ivLabel.style.display = isDaily ? 'none' : '';
    var dlLabel = el('sub-poller-daily-label');
    if (dlLabel) dlLabel.style.display = isDaily ? '' : 'none';

    if (!box) return;
    if (!p.enabled) {
      box.style.display = 'none';
      box.innerHTML = '';
      return;
    }

    var bo = p.backoff_until ? new Date(p.backoff_until.replace(/-/g, '/')) : null;
    var inBackoff = !!(bo && bo.getTime() > Date.now());

    var tone = 'var(--bg-tertiary)', fg = 'var(--text-secondary)';
    if (inBackoff || p.needs_login) { tone = 'rgba(220,38,38,0.10)'; fg = 'var(--error)'; }

    var lines = [];
    if (isDaily) {
      lines.push('每天 <b>' + escHtml(p.daily_at || '09:00') + '</b> 检查一次' +
                 '（±3 分钟随机浮动）');
    } else {
      lines.push('每 <b>' + fmtInterval(p.interval_minutes) + '</b> 检查一次' +
                 '（±' + p.jitter_percent + '% 随机浮动）');
    }

    if (p.running) {
      lines.push('<span style="color:var(--warning)">正在检查中…</span>');
    } else if (p.next_run_at) {
      lines.push('下次检查：<b>' + escHtml(p.next_run_at) + '</b>（' +
                 escHtml(fmtWhen(p.next_run_at)) + '）');
    }

    if (p.needs_login) {
      lines.push('登录已失效，请到「设置 → 抖音账号登录」重新扫码，' +
                 '否则不会再自动检查');
    }

    if (inBackoff) {
      lines.push('已触发抖音风控，自动暂停到 <b>' + escHtml(p.backoff_until) + '</b>' +
                 '（连续失败 ' + p.consecutive_failures + ' 次，退避是为了避开验证码）');
    }

    if (p.last_run_at) {
      var lr = p.last_result || {};
      var parts = [];
      if (lr.message) parts.push(escHtml(lr.message));
      if (lr.queued) parts.push('入队 ' + lr.queued);
      lines.push('上次检查（' + escHtml(fmtWhen(p.last_run_at)) + '）：' +
                 (parts.join('，') || '—'));
    } else {
      lines.push('还没检查过');
    }

    if (p.creators_enabled === 0) {
      lines.push('当前没有启用中的订阅，检查了也不会有结果');
    }

    box.style.display = 'block';
    box.style.background = tone;
    box.style.color = fg;
    box.innerHTML = lines.join('<br>');
  }

  function loadPoller() {
    return api(POLLER_API).then(renderPoller).catch(function () {
      // 状态读不到不该打断订阅列表本身，静默即可
    });
  }

  function savePoller(patch) {
    return api(POLLER_API, { method: 'POST', body: patch }).then(function (r) {
      renderPoller(r.poller);
      return r;
    });
  }

  function bindPollerField(id, key, labelOf, transform) {
    var sel = el(id);
    if (!sel) return;
    sel.addEventListener('change', function () {
      var patch = {};
      // 默认按数字解析（间隔、上限、抖动都是数）；
      // mode / daily_at 这类字符串字段传恒等 transform 进来
      patch[key] = (transform || function (v) { return parseInt(v, 10); })(sel.value);
      sel.disabled = true;
      savePoller(patch).then(function () {
        showMsg(labelOf(sel), 'ok');
      }).catch(function (e) {
        showMsg('设置失败：' + (e.message || e), 'error');
        return loadPoller();      // 失败回读，把界面恢复成服务端真实值
      }).finally(function () { sel.disabled = false; });
    });
  }

  // ---------- 数据 ----------

  function refresh() {
    return api(API).then(function (d) {
      renderStats(d.stats);
      renderList(d.creators);
      loadPoller();          // 顺带把自动检查状态也刷新了
    }).catch(function (e) {
      renderList([]);
      showMsg('读取订阅列表失败：' + (e.message || e), 'error');
    });
  }

  // ---------- 动作 ----------

  function addSubscription() {
    var input = el('sub-url');
    var url = (input.value || '').trim();
    if (!url) { showMsg('请先粘贴创作者主页链接', 'error'); return; }

    setBusy(true);
    showMsg('正在解析并抓取主页资料，约需 10~20 秒…', 'busy');
    api(API, { method: 'POST', body: { url: url, fetch_profile: true } })
      .then(function (d) {
        var name = (d.creator && d.creator.nickname) || '该创作者';
        showMsg('已订阅：' + name, 'ok');
        input.value = '';
        toast('订阅成功：' + name, 'success');
        return refresh();
      })
      .catch(function (e) {
        showMsg(e.message || String(e), 'error');
      })
      .finally(function () { setBusy(false); });
  }

  function previewCreator() {
    var input = el('sub-url');
    var url = (input.value || '').trim();
    if (!url) { showMsg('请先粘贴创作者主页链接', 'error'); return; }

    setBusy(true);
    showMsg('正在抓取主页，约需 10~20 秒…', 'busy');
    api(API + '/preview', { method: 'POST', body: { url: url, max_scrolls: 3 } })
      .then(function (d) {
        var lines = ['<b>' + escHtml(d.nickname || '(未取到昵称)') + '</b>',
          '共抓到 <b>' + d.video_count + '</b> 个作品'];
        if (d.subscribed) lines.push('<span style="color:var(--warning)">已经订阅过了</span>');
        if (d.video_count === 0) {
          lines.push('<span style="color:var(--error)">一个作品都没抓到。' +
            '可能是需要登录、主页被限制，或者滚动次数不够。</span>');
        }
        showMsg(lines.join('　'), d.video_count > 0 ? 'ok' : 'error');
      })
      .catch(function (e) {
        showMsg(e.message || String(e), 'error');
      })
      .finally(function () { setBusy(false); });
  }

  // 每次检查最多下载几个新作品。
  // 保守取值：抖音风控敏感，一次只下一个最稳妥。
  // 设成 0 表示不限制（不建议）。
  var MAX_NEW_PER_CHECK = 1;

  function checkOne(btn) {
    var sec = btn.dataset.sec;
    btn.disabled = true;
    var old = btn.innerHTML;
    btn.innerHTML = '检查中…';
    showMsg('正在抓取主页，约需 10~20 秒…', 'busy');

    api(API + '/' + encodeURIComponent(sec) + '/check', {
      method: 'POST',
      body: { download: true, max_new: MAX_NEW_PER_CHECK, max_scrolls: 3 }
    }).then(function (r) {
      if (r.baselined) {
        showMsg('<b>' + escHtml(r.nickname || '') + '</b>：' + escHtml(r.message), 'ok');
        toast('已建立基线，不下载存量作品', 'success');
      } else if (r.new_count === 0) {
        showMsg('<b>' + escHtml(r.nickname || '') + '</b>：没有新作品', 'ok');
      } else {
        showMsg('<b>' + escHtml(r.nickname || '') + '</b>：' + escHtml(r.message), 'ok');
        if (r.queued) toast('已加入下载队列 ' + r.queued + ' 个', 'success');
      }
      return refresh();
    }).catch(function (err) {
      var msg = err.message || String(err);
      // 后端对风控返回 429，错误文案里带「风控」，给出针对性提示
      if (msg.indexOf('风控') >= 0 || msg.indexOf('验证码') >= 0) {
        showMsg('抖音触发了风控验证，本轮未完成：' + escHtml(msg) +
                '<br>稍等几分钟再试，自动检查会自行退避。', 'error');
      } else {
        showMsg('检查失败：' + escHtml(msg), 'error');
      }
    }).finally(function () {
      btn.innerHTML = old;
      btn.disabled = false;
    });
  }

  // ---- 本次检查策略（P2-3）----
  // 控件是静态 HTML，默认值就是原有行为（下载、单轮 1 个、跟随各创作者），
  // 不落库；每次点「检查全部更新」现读现用。
  function readStrategy() {
    var dl = el('strat-download');
    var mx = el('strat-maxnew');
    var sc = el('strat-scope');
    var n = el('strat-n');
    var nVal = 3;
    if (n) {
      nVal = parseInt(n.value, 10);
      if (!(nVal >= 1 && nVal <= 9999)) nVal = 3;
    }
    return {
      download: dl ? !!dl.checked : true,
      max_new: mx ? parseInt(mx.value, 10) : MAX_NEW_PER_CHECK,
      // '' = 跟随各创作者自己设的范围（后端不覆盖）
      scope: sc ? sc.value : '',
      scope_param: String(nVal)
    };
  }

  function checkAll() {
    var strat = readStrategy();
    if (strat.scope === 'all') {
      // 与卡片上选「全部补下」同一个防呆：可能一次排队几十上百个
      var ok = confirm(
        '本次检查把所有创作者的历史作品全部补下？\n\n' +
        '水位线之下没下过的作品会按单轮上限分批入队，' +
        '已下载过的不会重复。'
      );
      if (!ok) return;
    }

    var btn = el('sub-check-all');
    if (btn) { btn.disabled = true; btn.innerHTML = '检查中…'; }
    showMsg('正在逐个检查（串行，避免触发抖音限流），创作者多时耗时较长…', 'busy');

    api(API + '/check-all', {
      method: 'POST',
      body: {
        download: strat.download,
        max_new: strat.max_new,
        scope: strat.scope || undefined,   // undefined 会被 JSON 丢掉 = 跟随
        scope_param: strat.scope === 'backfill_n' ? strat.scope_param : ''
      }
    }).then(function (r) {
      if (r.skipped) {
        // 没真正跑：退避中 / 登录窗口开着 / 另一轮还在跑
        showMsg('本轮没执行<br>' + escHtml(r.message || r.reason || ''), 'busy');
        return refresh();
      }
      var lines = (r.results || []).map(function (x) {
        if (x.error) return '· ' + escHtml(x.nickname || x.sec_uid) + '：' + escHtml(x.error);
        if (x.baselined) {
          var bl = '· ' + escHtml(x.nickname || x.sec_uid) + '：建立基线，' + x.marked_as_seen + ' 个存量作品不下载';
          // 首查建基线时若策略选了补下，基线当轮就开始补（P2-1），说清楚
          if (x.backfilled) {
            bl += '，同时补下 ' + x.backfilled + ' 个历史作品';
            if (x.backfill_left) bl += '（还剩 ' + x.backfill_left + ' 个）';
          }
          return bl;
        }
        if (x.skipped) return '· ' + escHtml(x.nickname || x.sec_uid) + '：已暂停';
        var line = '· ' + escHtml(x.nickname || x.sec_uid) + '：新作品 ' + x.new_count + ' 个，入队 ' + x.queued + ' 个';
        // 按策略补下的历史作品单独说清楚：queued 里混着增量和补下，
        // 只报一个数用户分不清「新发的」还是「翻旧账的」
        if (x.backfilled) {
          line += '，补下历史 ' + x.backfilled + ' 个';
          if (x.backfill_left) line += '（还剩 ' + x.backfill_left + ' 个待补）';
        }
        return line;
      });
      var head = '检查完成';
      if (r.rate_limited) head = '<b style="color:var(--error)">触发抖音风控，已自动退避</b>';
      else if (r.needs_login) head = '<b style="color:var(--error)">登录已失效，请重新扫码</b>';
      showMsg(head + '<br>' + (lines.join('<br>') || '没有可检查的订阅'),
               (r.rate_limited || r.needs_login) ? 'error' : 'ok');
      toast('检查完成：发现 ' + r.new_found + ' 个，入队 ' + r.queued + ' 个',
            (r.rate_limited || r.needs_login) ? 'error' : 'success');
      return refresh();
    }).catch(function (err) {
      showMsg('检查失败：' + escHtml(err.message || err), 'error');
    }).finally(function () { refresh(); });
  }

  function onListClick(e) {
    var btn = e.target.closest ? e.target.closest('button[data-act]') : null;
    if (btn && btn.dataset.act === 'check') { checkOne(btn); return; }

    if (btn && btn.id === 'sub-check-all') { checkAll(); return; }
    if (!btn) return;
    var act = btn.dataset.act;
    var sec = btn.dataset.sec;

    if (act === 'toggle') {
      var enabled = btn.dataset.enabled !== '1';
      btn.disabled = true;
      api(API + '/' + encodeURIComponent(sec) + '/toggle', {
        method: 'POST', body: { enabled: enabled }
      }).then(function () {
        toast(enabled ? '已恢复轮询' : '已暂停轮询', 'success');
        return refresh();
      }).catch(function (err) {
        showMsg(err.message || String(err), 'error');
        btn.disabled = false;
      });
      return;
    }

    if (act === 'remove') {
      if (!confirm('取消订阅？\n\n已下载的文件不会被删除。\n已发现的作品记录会保留，重新订阅时不会重复下载。')) return;
      btn.disabled = true;
      api(API + '/' + encodeURIComponent(sec), { method: 'DELETE' })
        .then(function () { toast('已取消订阅', 'success'); return refresh(); })
        .catch(function (err) {
          showMsg(err.message || String(err), 'error');
          btn.disabled = false;
        });
      return;
    }

    if (act === 'detail') {
      btn.disabled = true;
      api(API + '/' + encodeURIComponent(sec) + '?limit=20')
        .then(function (d) {
          var works = d.works || [];
          if (!works.length) {
            showMsg('这位创作者还没有发现过新作品。' +
              '（自动检查新作品的功能还在开发中）', 'busy');
            return;
          }
          var lines = works.map(function (w) {
            return '· ' + escHtml(w.title || w.aweme_id);
          });
          showMsg('<b>已发现 ' + works.length + ' 个作品</b><br>' + lines.join('<br>'), 'ok');
        })
        .catch(function (err) {
          showMsg(err.message || String(err), 'error');
        })
        .finally(function () { btn.disabled = false; });
    }
  }

  // ---------- 下载范围：保存与回滚（P2-1） ----------

  function saveScope(sec, scope, param) {
    var sel = document.querySelector('.sub-scope[data-sec="' + sec + '"]');
    if (sel) sel.disabled = true;
    api(API + '/' + encodeURIComponent(sec) + '/scope', {
      method: 'POST', body: { scope: scope, param: param || '' }
    }).then(function () {
      if (sel) {
        sel.dataset.scope = scope;      // 服务端认可了，回滚基准跟着走
        sel.value = scope;
        sel.disabled = false;
      }
      toast('下载范围已更新，下次检查生效', 'success');
    }).catch(function (err) {
      showMsg(err.message || String(err), 'error');
      refresh();                         // 失败就按服务端真值重画，别自己拼回滚
    });
  }

  function onScopeChange(e) {
    var sel = e.target;
    if (!sel || !sel.classList || !sel.classList.contains('sub-scope')) return;
    var scope = sel.value;
    var prev = sel.dataset.scope || 'only_new';
    if (scope === prev) return;

    if (scope === 'all') {
      // 「全部」可能一次排队几十上百个，值得拦一下
      var ok = confirm(
        '把这个创作者的下载范围设为「全部补下」？\n\n' +
        '水位线之下的历史作品会在此后的检查中分批下载' +
        '（受单轮下载上限约束），已下载过的不会重复。'
      );
      if (!ok) { sel.value = prev; return; }
    }

    var card = sel.closest('div[data-sec]');
    var nInput = card ? card.querySelector('.sub-scope-n') : null;
    if (scope === 'backfill_n') {
      if (nInput) nInput.style.display = '';
    } else if (nInput) {
      nInput.style.display = 'none';
    }

    var param = '';
    if (scope === 'backfill_n') param = (nInput && nInput.value) || '3';
    saveScope(sel.dataset.sec, scope, param);
  }

  function onScopeNChange(e) {
    var inp = e.target;
    if (!inp || !inp.classList || !inp.classList.contains('sub-scope-n')) return;
    var n = parseInt(inp.value, 10);
    if (!(n >= 1)) n = 1;
    if (n > 9999) n = 9999;
    inp.value = n;
    saveScope(inp.dataset.sec, 'backfill_n', String(n));
  }

  // 策略区的控件是静态 HTML，init 时绑一次即可。
  // data-prev 记「上次确认过的值」，选 all 被取消时靠它回滚。
  function bindStrategy() {
    var sc = el('strat-scope');
    if (sc) {
      sc.dataset.prev = sc.value;
      sc.addEventListener('change', function () {
        if (sc.value === 'all') {
          var ok = confirm(
            '本次检查把所有创作者的历史作品全部补下？\n\n' +
            '水位线之下没下过的作品会按单轮上限分批入队，' +
            '已下载过的不会重复。'
          );
          if (!ok) { sc.value = sc.dataset.prev || ''; return; }
        }
        sc.dataset.prev = sc.value;
        var lab = el('strat-n-label');
        if (lab) lab.style.display = sc.value === 'backfill_n' ? '' : 'none';
      });
    }
    var n = el('strat-n');
    if (n) {
      // 失焦时把越界值掰回 1-9999（服务端也校验，这里只是别把明显
      // 手滑的值发出去），服务端用的是 validate_scope 同一套规则
      n.addEventListener('change', function () {
        var v = parseInt(n.value, 10);
        if (!(v >= 1)) v = 1;
        if (v > 9999) v = 9999;
        n.value = v;
      });
    }
  }

  // ---------- 绑定 ----------

  function isActive() {
    var p = el('panel-subscriptions');
    return p && p.classList.contains('active');
  }

  function init() {
    var b1 = el('sub-add-btn'), b2 = el('sub-preview-btn');
    var list = el('sub-list'), stats = el('sub-stats');
    if (b1) b1.addEventListener('click', addSubscription);
    if (b2) b2.addEventListener('click', previewCreator);
    if (list) list.addEventListener('click', onListClick);
    // 下载范围的下拉与 N 输入框都是动态渲染的卡片内容，
    // 靠 sub-list 冒泡接住 change（数字框要等失焦/回车才触发 change）
    if (list) list.addEventListener('change', function (e) {
      onScopeChange(e);
      onScopeNChange(e);
    });
    // 「检查全部更新」按钮是 renderStats 动态生成的，
    // 挂在 stats 容器上靠事件冒泡接住，不能在 init 里直接绑
    if (stats) stats.addEventListener('click', function (e) {
      var t = e.target;
      if (t && t.closest && t.closest('#sub-check-all')) checkAll();
    });
    // 检查策略（P2-3）：静态控件，直接绑
    bindStrategy();

    var input = el('sub-url');
    if (input) {
      input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') addSubscription();
      });
    }

    // 自动检查开关
    var pt = el('sub-poller-toggle');
    if (pt) pt.addEventListener('change', function () {
      var on = pt.checked;
      pt.disabled = true;
      savePoller({ enabled: on }).then(function () {
        showMsg(on ? '自动检查已开启，稍后会自动跑第一轮' : '自动检查已关闭', 'ok');
        toast(on ? '自动检查已开启' : '自动检查已关闭', on ? 'success' : 'info');
      }).catch(function (e) {
        pt.checked = !on;              // 失败回滚，别让界面显示成没生效的样子
        showMsg('设置失败：' + (e.message || e), 'error');
      }).finally(function () {
        pt.disabled = false;
        loadPoller();
      });
    });

    bindPollerField('sub-poller-mode', 'mode', function (sel) {
      return sel.value === 'daily_at' ? '已改为每天定时检查' : '已改为按间隔检查';
    }, function (v) { return v; });
    bindPollerField('sub-poller-daily', 'daily_at', function (sel) {
      return '每天 ' + sel.value + ' 自动检查';
    }, function (v) { return v; });
    bindPollerField('sub-poller-interval', 'interval_minutes', function (sel) {
      return '检查间隔已改为 ' + fmtInterval(parseInt(sel.value, 10));
    });
    bindPollerField('sub-poller-maxnew', 'max_new_per_check', function (sel) {
      var v = parseInt(sel.value, 10);
      return v === 0 ? '单轮下载数量已改为不限' : '单轮最多下载 ' + v + ' 个';
    });

    // 如果这一页正好是当前激活页，直接加载。
    // 早先只在点击导航项时加载，导致把订阅页设成默认页启动时
    // 列表一片空白，得手动点一下侧边栏才有数据。
    if (isActive()) refresh();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // 切到本页时刷新
  document.addEventListener('click', function (e) {
    var t = e.target;
    if (t && t.dataset && t.dataset.tab === 'subscriptions' && el('sub-list')) {
      refresh();
    }
  });
})();
