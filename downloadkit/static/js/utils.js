// ========== 工具函数 ==========
var $ = function(sel, ctx) { return (ctx || document).querySelector(sel); };
var $$ = function(sel, ctx) { return [].slice.call((ctx || document).querySelectorAll(sel)); };

function _extractErr(e) {
  // 递归从对象里提取可读的错误字符串（避免显示 [object Object]）
  if (!e) return '';
  if (typeof e === 'string') return e;
  if (typeof e === 'number') return String(e);
  if (e instanceof Error) return _extractErr(e.message);
  if (Array.isArray(e)) return e.map(_extractErr).filter(Boolean).join('; ');
  if (typeof e === 'object') {
    for (var k of ['message', 'detail', 'error', 'msg']) {
      if (e[k]) return _extractErr(e[k]);
    }
    try { return JSON.stringify(e); } catch (_) { return String(e); }
  }
  return String(e);
}

function api(path, opts) {
  opts = opts || {};
  opts.headers = opts.headers || {};
  if (opts.body && typeof opts.body === 'object') {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(opts.body);
  } else if (opts.body && typeof opts.body === 'string' && !opts.headers['Content-Type']) {
    // 防御：string body 默认也按 JSON 发。fetch 对字符串 body 兜底是
    // text/plain，FastAPI 0.141+ 见非 application/json 不解析 body，
    // Pydantic 收到裸字符串直接 422「Input should be a valid dictionary」。
    // 本项目的 string body 只会是 JSON.stringify 的产物。
    opts.headers['Content-Type'] = 'application/json';
  }
  // 整体超时（秒）：AbortController 主动失败，避免请求挂起时前端无限转圈。
  // 超时统一转成可读错误走调用方的 catch（兑底按钮等照常出现）。
  var timer = null;
  if (opts.timeout && opts.timeout > 0) {
    var ctl = new AbortController();
    opts.signal = ctl.signal;
    timer = setTimeout(function() { ctl.abort(); }, opts.timeout * 1000);
  }
  var p = fetch(window.location.origin + path, opts).then(function(r) {
    if (!r.ok) return r.json().then(function(e) {
      throw new Error(_extractErr(e) || r.statusText || '请求失败');
    }, function() {
      throw new Error(r.statusText || '请求失败');
    });
    return r.json();
  });
  if (timer) {
    p = p.then(function(v) {
      clearTimeout(timer);
      return v;
    }, function(e) {
      clearTimeout(timer);
      if (e && e.name === 'AbortError') {
        throw new Error('请求超时（超过 ' + opts.timeout + ' 秒），请重试，或用深度嗅探/展开选集换个方式');
      }
      throw e;
    });
  }
  return p;
}

function toast(msg, type) {
  type = type || 'info';
  var el = document.createElement('div');
  el.className = 'toast ' + type;
  el.textContent = msg;
  $('#toast-container').appendChild(el);
  setTimeout(function() { el.remove(); }, 3000);
}

function fmtSize(bytes) {
  if (!bytes) return '';
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1048576).toFixed(1) + ' MB';
}

function escHtml(s) {
  var div = document.createElement('div');
  div.textContent = s || '';
  return div.innerHTML;
}

function escAttr(s) {
  return (s || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ========== 状态管理 ==========
var state = {
  activeTab: 'music',
  // 「下载」页的子视图：queue=进行中（原下载队列），files=已完成（原已下载）
  downloadView: 'queue',
  songs: [],
  selectedSongs: {},
  playlistSongs: null,
  downloading: {},
  files: [],
  batchTask: null,
};

// ========== 页面标题映射 ==========
var tabTitles = {
  'music': '音乐下载',
  'resource': '资源解析',
  'movie': '影视解析',
  'subscriptions': '创作者订阅',
  'downloads': '下载',
  'collections': '我的歌单',
  'settings': '设置',
  'help': '解答',

};

// ========== 确认弹窗（P4-4，替原生 confirm）==========
// 原生 confirm 卡死页面且样式和应用完全不搭；换成返回 Promise 的
// 同款弹窗：Enter=确认、Esc=取消、点遮罩=取消，\n 直接换行。
// 不用 id（静态引用检查只认 index.html 里存在的元素），全部局部引用；
// 用 textContent 塞正文，消息里的尖括号不会被当 HTML 解析。
function uiConfirm(message, options) {
  options = options || {};
  return new Promise(function (resolve) {
    var mask = document.createElement('div');
    mask.className = 'ui-modal-mask';

    var box = document.createElement('div');
    box.className = 'ui-modal';
    box.setAttribute('role', 'alertdialog');
    box.setAttribute('aria-modal', 'true');

    var title = document.createElement('div');
    title.className = 'ui-modal-title';
    title.textContent = options.title || '请确认';

    var body = document.createElement('div');
    body.className = 'ui-modal-body';
    body.textContent = message || '';

    var actions = document.createElement('div');
    actions.className = 'ui-modal-actions';

    var cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.className = 'btn btn-secondary ui-modal-btn';
    cancelBtn.textContent = options.cancelText || '取消';

    var okBtn = document.createElement('button');
    okBtn.type = 'button';
    okBtn.className = 'btn ui-modal-btn ui-modal-ok' + (options.danger ? ' danger' : '');
    okBtn.textContent = options.okText || '确认';

    actions.appendChild(cancelBtn);
    actions.appendChild(okBtn);
    box.appendChild(title);
    box.appendChild(body);
    box.appendChild(actions);
    mask.appendChild(box);

    var done = false;
    function close(v) {
      if (done) return;
      done = true;
      document.removeEventListener('keydown', onKey, true);
      if (mask.parentNode) mask.parentNode.removeChild(mask);
      resolve(v);
    }
    function onKey(e) {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(false); }
      else if (e.key === 'Enter') { e.preventDefault(); close(true); }
      else if (e.key === 'Tab') {
        // 焦点关在弹窗里：只有两个按钮，Tab 来回切
        e.preventDefault();
        (document.activeElement === okBtn ? cancelBtn : okBtn).focus();
      }
    }
    mask.addEventListener('click', function (e) { if (e.target === mask) close(false); });
    cancelBtn.addEventListener('click', function () { close(false); });
    okBtn.addEventListener('click', function () { close(true); });
    document.addEventListener('keydown', onKey, true);

    document.body.appendChild(mask);
    okBtn.focus();
  });
}
