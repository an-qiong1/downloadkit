// ========== 抖音登录（Playwright 持久化 profile 方案） ==========
// 与页面里原有的「抖音 Cookie 助手」的区别：
//   旧助手  把 cookie 字符串存进配置文件，Edge 有 App-Bound 加密经常读不出来
//   本模块  直接用程序自带的 Chromium，扫一次码，登录态存在 profile 里长期有效
//
// 后端接口（server.py）：
//   GET  /api/douyin/login/status   查登录态
//   POST /api/douyin/login/start    弹浏览器窗口扫码，立即返回
//   POST /api/douyin/login/cancel   取消
//   POST /api/douyin/logout         退出登录
(function () {
  'use strict';

  var API = '/api/douyin';
  var POLL_MS = 2000;
  var pollTimer = null;

  // ---- DOM ----
  function elLogin() { return document.getElementById('dy-login-btn'); }
  function elLogout() { return document.getElementById('dy-logout-btn'); }
  function elStatus() { return document.getElementById('dy-login-status'); }
  function elBox() { return document.getElementById('dy-login-box'); }
  function elRefresh() { return document.getElementById('dy-login-refresh'); }

  // ---- 渲染 ----
  function setStatus(text, color) {
    var s = elStatus();
    if (!s) return;
    s.textContent = text;
    s.style.color = color || 'var(--text-secondary)';
  }

  function setBox(text, color) {
    var b = elBox();
    if (!b) return;
    if (!text) { b.style.display = 'none'; b.textContent = ''; return; }
    b.style.display = 'block';
    b.textContent = text;
    b.style.color = color || 'var(--text-secondary)';
  }

  function setButtons(phase) {
    // phase: idle | busy | logged
    var b1 = elLogin(), b2 = elLogout();
    if (b1) {
      b1.disabled = (phase !== 'idle');
      b1.textContent = (phase === 'busy') ? '登录中…' : '扫码登录抖音';
    }
    if (b2) b2.style.display = (phase === 'logged') ? 'inline-block' : 'none';
  }

  // ---- 轮询 ----
  function stopPolling() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  var FINAL = { success: 1, failed: 1, timeout: 1, cancelled: 1 };

  function poll() {
    api(API + '/login/status').then(function (d) {
      if (d.login_running) {
        setButtons('busy');
        setStatus('等待扫码…', 'var(--warning)');
        setBox((d.message || '请在浏览器窗口里扫码登录') +
               '（已用 ' + (d.elapsed || 0) + ' 秒）');
        return;
      }
      // 流程结束
      stopPolling();
      if (d.status === 'success') {
        setButtons('logged');
        setStatus('已登录' + (d.detail ? '：' + d.detail : ''), 'var(--success)');
        setBox('');
        toast('抖音登录成功', 'success');
      } else if (d.status === 'timeout') {
        setButtons('idle');
        setStatus('登录超时', 'var(--error)');
        setBox(d.message || '超时，请重试');
      } else if (d.status === 'cancelled') {
        setButtons('idle');
        setStatus('已取消登录', 'var(--text-secondary)');
        setBox('');
      } else if (d.status === 'failed') {
        setButtons('idle');
        setStatus('登录失败', 'var(--error)');
        setBox(d.message || '登录失败，请重试');
      } else {
        renderIdle(d);
      }
    }).catch(function (e) {
      stopPolling();
      setButtons('idle');
      setStatus('无法连接后端', 'var(--error)');
      setBox(String(e.message || e));
    });
  }

  function renderIdle(d) {
    // 后端拿不到后台浏览器时会用登录流程状态兜底，
    // 这里再兜一层：刚登录成功就别又显示回「未登录」，免得用户以为扫码没生效。
    var logged = d.logged_in || d.status === 'success';
    if (logged) {
      setButtons('logged');
      setStatus('已登录' + (d.detail ? '：' + d.detail : ''), 'var(--success)');
      setBox('');
    } else {
      setButtons('idle');
      setStatus('未登录', 'var(--text-secondary)');
      if (d.detail) setBox(d.detail);
    }
  }

  // ---- 动作 ----
  function startLogin() {
    setButtons('busy');
    setStatus('正在启动浏览器…', 'var(--warning)');
    setBox('马上会弹出一个浏览器窗口，请在窗口里扫码');
    api(API + '/login/start', {
      method: 'POST',
      body: { timeout: 300 }
    }).then(function (d) {
      if (!d.ok) {
        setButtons('idle');
        setStatus('无法开始登录', 'var(--error)');
        setBox(d.error || '未知原因');
        toast(d.error || '无法开始登录', 'error');
        return;
      }
      toast('请在弹出的浏览器窗口里扫码', 'info');
      stopPolling();
      pollTimer = setInterval(poll, POLL_MS);
      poll();
    }).catch(function (e) {
      setButtons('idle');
      setStatus('无法开始登录', 'var(--error)');
      setBox(String(e.message || e));
    });
  }

  function cancelLogin() {
    stopPolling();
    setButtons('busy');
    setStatus('正在取消…', 'var(--text-secondary)');
    api(API + '/login/cancel', { method: 'POST' }).then(function () {
      setButtons('idle');
      setStatus('已取消登录', 'var(--text-secondary)');
      setBox('');
    }).catch(function (e) {
      setStatus('取消失败', 'var(--error)');
      setBox(String(e.message || e));
    });
  }

  function logout() {
    if (!confirm('确定要退出抖音登录吗？退出后订阅功能会不可用。')) return;
    setButtons('busy');
    api(API + '/logout', { method: 'POST' }).then(function (d) {
      if (!d.ok) {
        setButtons('logged');
        setStatus('退出失败', 'var(--error)');
        setBox(d.error || '未知原因');
        return;
      }
      setButtons('idle');
      setStatus('已退出登录', 'var(--text-secondary)');
      setBox('');
      toast('已退出抖音登录', 'success');
    }).catch(function (e) {
      setButtons('logged');
      setStatus('退出失败', 'var(--error)');
      setBox(String(e.message || e));
    });
  }

  function refresh() {
    setStatus('正在检查登录状态…', 'var(--text-secondary)');
    api(API + '/login/status').then(function (d) {
      if (d.login_running) {
        setButtons('busy');
        setStatus('等待扫码…', 'var(--warning)');
        setBox(d.message || '');
        stopPolling();
        pollTimer = setInterval(poll, POLL_MS);
      } else {
        renderIdle(d);
      }
    }).catch(function (e) {
      setButtons('idle');
      setStatus('检查失败', 'var(--error)');
      setBox(String(e.message || e));
    });
  }

  // ---- 绑定 ----
  function init() {
    var b1 = elLogin(), b2 = elLogout(), b3 = elRefresh();
    if (b1) {
      // 登录中时点主按钮 = 取消，省得再点一次
      b1.addEventListener('click', function () {
        if (b1.disabled) { cancelLogin(); return; }
        startLogin();
      });
    }
    if (b2) b2.addEventListener('click', logout);
    if (b3) b3.addEventListener('click', refresh);
    refresh();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // 切到设置页时刷新一次，避免状态过期
  document.addEventListener('click', function (e) {
    var t = e.target;
    if (t && t.dataset && t.dataset.tab === 'settings' && elRefresh()) {
      setTimeout(refresh, 200);
    }
  });
})();
