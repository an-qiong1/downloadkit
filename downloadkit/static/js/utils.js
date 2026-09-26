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
  }
  return fetch(window.location.origin + path, opts).then(function(r) {
    if (!r.ok) return r.json().then(function(e) {
      throw new Error(_extractErr(e) || r.statusText || '请求失败');
    }, function() {
      throw new Error(r.statusText || '请求失败');
    });
    return r.json();
  });
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
  songs: [],
  selectedSongs: {},
  playlistSongs: null,
  downloading: {},
  files: []
};

// ========== 页面标题映射 ==========
var tabTitles = {
  'music': '音乐下载',
  'resource': '资源解析',
  'subscriptions': '创作者订阅',
  'files': '已下载',
  'queue': '下载队列',
  'collections': '我的歌单',
  'settings': '设置',

};
