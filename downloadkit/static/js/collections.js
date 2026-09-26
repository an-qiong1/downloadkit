// ========== 歌单收藏模块 ==========

(function() {
  'use strict';

  var container, listEl, loadingEl, emptyEl;

  // 初始化
  function init() {
    container = $('#collections-app');
    if (!container) return;
    render();
  }

  function render() {
    container.innerHTML =
      '<div style="margin-bottom:16px;display:flex;justify-content:space-between;align-items:center">' +
        '<h3 style="margin:0;font-size:16px;font-weight:600">收藏歌单</h3>' +
        '<button class="btn btn-primary" id="coll-add-btn"><i data-lucide="plus" style="width:14px;height:14px;margin-right:6px"></i>添加收藏</button>' +
      '</div>' +
      '<div id="coll-loading" class="status-msg" style="display:none"><span class="spinner"></span> 加载中...</div>' +
      '<div id="coll-empty" class="status-msg" style="display:none">还没有收藏的歌单，点击右上角添加</div>' +
      '<div id="coll-list"></div>' +
      // 添加弹窗
      '<div class="modal-overlay" id="coll-add-modal" style="display:none">' +
        '<div class="modal-box" style="background:var(--card-bg);border:1px solid var(--border);border-radius:12px;padding:24px;max-width:520px;width:90%;margin:10vh auto;box-shadow:0 8px 32px rgba(0,0,0,0.3)">' +
          '<h3 style="margin:0 0 16px;font-size:16px;font-weight:600">添加收藏歌单</h3>' +
          '<p style="margin:0 0 12px;font-size:13px;color:var(--text-secondary)">粘贴歌单链接，系统将自动解析并获取名称</p>' +
          '<input id="coll-add-url" class="search-input" type="text" placeholder="例如: https://music.163.com/playlist?id=..." style="width:100%;margin-bottom:12px;padding:10px 14px;border:1px solid var(--border);border-radius:8px;background:var(--input-bg);color:var(--text);font-size:14px">' +
          '<div style="display:flex;gap:8px;justify-content:flex-end">' +
            '<button class="btn btn-secondary" id="coll-add-cancel">取消</button>' +
            '<button class="btn btn-primary" id="coll-add-confirm">添加</button>' +
          '</div>' +
        '</div>' +
      '</div>' +
      // 详情弹窗
      '<div class="modal-overlay" id="coll-detail-modal" style="display:none">' +
        '<div class="modal-box" style="background:var(--card-bg);border:1px solid var(--border);border-radius:12px;padding:24px;max-width:600px;width:90%;margin:5vh auto;box-shadow:0 8px 32px rgba(0,0,0,0.3);max-height:80vh;overflow-y:auto">' +
          '<h3 style="margin:0 0 16px;font-size:16px;font-weight:600" id="coll-detail-title"></h3>' +
          '<div id="coll-detail-info" style="margin-bottom:16px;font-size:13px;color:var(--text-secondary)"></div>' +
          '<div id="coll-detail-tracks" style="margin-bottom:16px"></div>' +
          '<div style="display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap">' +
            '<button class="btn btn-secondary" id="coll-detail-refresh"><i data-lucide="refresh-cw" style="width:14px;height:14px;margin-right:6px"></i>刷新</button>' +
            '<button class="btn btn-primary" id="coll-detail-download"><i data-lucide="download" style="width:14px;height:14px;margin-right:6px"></i>下载全部</button>' +
            '<button class="btn btn-secondary" id="coll-detail-close">关闭</button>' +
          '</div>' +
        '</div>' +
      '</div>';

    lucide.createIcons();
    bindEvents();
    loadList();
  }

  function bindEvents() {
    $('#coll-add-btn').addEventListener('click', function() {
      $('#coll-add-url').value = '';
      $('#coll-add-modal').style.display = 'block';
    });
    $('#coll-add-cancel').addEventListener('click', function() {
      $('#coll-add-modal').style.display = 'none';
    });
    $('#coll-add-confirm').addEventListener('click', addCollection);
    $('#coll-add-url').addEventListener('keydown', function(e) {
      if (e.key === 'Enter') addCollection();
    });
    $('#coll-detail-close').addEventListener('click', function() {
      $('#coll-detail-modal').style.display = 'none';
    });
    $('#coll-detail-refresh').addEventListener('click', function() {
      var id = parseInt(this.dataset.id);
      if (id) refreshOne(id, function() { loadList(); showDetail(id); });
    });
    $('#coll-detail-download').addEventListener('click', function() {
      var id = parseInt(this.dataset.id);
      if (id) downloadCollection(id);
    });
    // 点击遮罩关闭弹窗
    $$('.modal-overlay').forEach(function(el) {
      el.addEventListener('click', function(e) {
        if (e.target === this) this.style.display = 'none';
      });
    });
  }

  // ========== 加载列表 ==========
  function loadList() {
    var loading = $('#coll-loading');
    var empty = $('#coll-empty');
    var list = $('#coll-list');
    loading.style.display = 'block';
    empty.style.display = 'none';
    list.innerHTML = '';

    api('/api/collections').then(function(data) {
      loading.style.display = 'none';
      if (!data || data.length === 0) {
        empty.style.display = 'block';
        return;
      }
      renderList(data);
    }).catch(function(err) {
      loading.style.display = 'none';
      list.innerHTML = '<div class="status-msg error">加载失败: ' + escHtml(err.message) + '</div>';
    });
  }

  function renderList(collections) {
    var list = $('#coll-list');
    var platformLabels = { netease: '网易云', qqmusic: 'QQ音乐', spotify: 'Spotify' };
    var platformColors = { netease: '#e74c3c', qqmusic: '#3498db', spotify: '#2ecc71' };

    list.innerHTML = collections.map(function(c) {
      var pl = c.platform || 'unknown';
      var label = platformLabels[pl] || pl;
      var color = platformColors[pl] || '#888';
      var refreshed = c.refreshed_at ? c.refreshed_at : '<span style="color:var(--text-secondary)">未刷新</span>';
      return '<div class="song-card" style="display:flex;align-items:center;padding:12px 16px;margin-bottom:8px;border-radius:10px;background:var(--card-bg);border:1px solid var(--border);cursor:pointer">' +
        '<div style="flex-shrink:0;width:40px;height:40px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:20px;margin-right:12px">🎵</div>' +
        '<div style="flex:1;min-width:0">' +
          '<div style="font-weight:500;margin-bottom:4px">' + escHtml(c.name) + '</div>' +
          '<div style="font-size:12px;color:var(--text-secondary)">' +
            '<span style="display:inline-block;padding:1px 8px;border-radius:4px;font-size:11px;color:#fff;background:' + color + ';margin-right:8px">' + label + '</span>' +
            '<span>' + c.song_count + ' 首</span>' +
            '<span style="margin-left:12px">上次: ' + refreshed + '</span>' +
          '</div>' +
        '</div>' +
        '<div style="display:flex;gap:4px;flex-shrink:0;margin-left:8px">' +
          '<button class="btn btn-sm coll-refresh" data-id="' + c.id + '" title="刷新" style="padding:6px 10px;font-size:12px"><i data-lucide="refresh-cw" style="width:12px;height:12px"></i></button>' +
          '<button class="btn btn-sm coll-download" data-id="' + c.id + '" title="下载全部" style="padding:6px 10px;font-size:12px"><i data-lucide="download" style="width:12px;height:12px"></i></button>' +
          '<button class="btn btn-sm coll-delete" data-id="' + c.id + '" title="删除" style="padding:6px 10px;font-size:12px;color:#e74c3c"><i data-lucide="trash-2" style="width:12px;height:12px"></i></button>' +
        '</div>' +
      '</div>';
    }).join('');

    lucide.createIcons();

    // 点击卡片 → 查看详情
    list.querySelectorAll('.song-card').forEach(function(card, idx) {
      card.addEventListener('click', function(e) {
        if (e.target.closest('button')) return;
        var id = collections[idx].id;
        showDetail(id);
      });
    });

    // 刷新按钮
    list.querySelectorAll('.coll-refresh').forEach(function(btn) {
      btn.addEventListener('click', function(e) {
        e.stopPropagation();
        var id = parseInt(this.dataset.id);
        if (id) refreshOne(id, loadList);
      });
    });

    // 下载按钮
    list.querySelectorAll('.coll-download').forEach(function(btn) {
      btn.addEventListener('click', function(e) {
        e.stopPropagation();
        var id = parseInt(this.dataset.id);
        if (id) downloadCollection(id);
      });
    });

    // 删除按钮
    list.querySelectorAll('.coll-delete').forEach(function(btn) {
      btn.addEventListener('click', function(e) {
        e.stopPropagation();
        var id = parseInt(this.dataset.id);
        if (id && confirm('确定删除这个收藏歌单？')) {
          api('/api/collections/' + id, { method: 'DELETE' }).then(function() {
            toast('已删除', 'success');
            loadList();
          }).catch(function(err) {
            toast('删除失败: ' + err.message, 'error');
          });
        }
      });
    });
  }

  // ========== 添加收藏 ==========
  function addCollection() {
    var url = $('#coll-add-url').value.trim();
    if (!url) { toast('请输入歌单链接', 'error'); return; }

    var btn = $('#coll-add-confirm');
    btn.disabled = true;
    btn.textContent = '解析中...';

    api('/api/collections', { method: 'POST', body: { url: url } }).then(function() {
      toast('收藏成功', 'success');
      $('#coll-add-modal').style.display = 'none';
      loadList();
    }).catch(function(err) {
      toast('收藏失败: ' + err.message, 'error');
    }).finally(function() {
      btn.disabled = false;
      btn.textContent = '添加';
    });
  }

  // ========== 刷新歌单 ==========
  function refreshOne(id, callback) {
    api('/api/collections/' + id + '/refresh', { method: 'POST' }).then(function(resp) {
      toast(resp.message || '刷新成功', 'success');
      if (callback) callback();
    }).catch(function(err) {
      toast('刷新失败: ' + err.message, 'error');
    });
  }

  // ========== 查看详情 ==========
  function showDetail(id) {
    api('/api/collections/' + id).then(function(data) {
      if (!data) { toast('歌单不存在', 'error'); return; }

      $('#coll-detail-title').textContent = data.name;
      $('#coll-detail-refresh').dataset.id = id;
      $('#coll-detail-download').dataset.id = id;

      var info = $('#coll-detail-info');
      var plLabels = { netease: '网易云', qqmusic: 'QQ音乐' };
      info.innerHTML =
        '<span style="display:inline-block;padding:1px 8px;border-radius:4px;font-size:11px;color:#fff;background:#888;margin-right:8px">' + (plLabels[data.platform] || data.platform) + '</span>' +
        '<span>' + data.song_count + ' 首</span>' +
        '<span style="margin-left:12px">创建: ' + data.created_at + '</span>' +
        '<span style="margin-left:12px">刷新: ' + (data.refreshed_at || '未刷新') + '</span>';

      var tracks = $('#coll-detail-tracks');
      if (!data.tracks || data.tracks.length === 0) {
        tracks.innerHTML = '<div class="status-msg" style="padding:20px 0">暂无歌曲，请点击刷新</div>';
      } else {
        tracks.innerHTML = '<div style="font-weight:500;margin-bottom:8px">歌曲列表 (' + data.tracks.length + ' 首)</div>' +
          '<div style="max-height:350px;overflow-y:auto;border:1px solid var(--border);border-radius:8px">' +
          data.tracks.map(function(t, i) {
            return '<div style="display:flex;align-items:center;padding:8px 12px;border-bottom:1px solid var(--border);font-size:13px">' +
              '<span style="width:28px;flex-shrink:0;color:var(--text-secondary)">' + (i + 1) + '</span>' +
              '<span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + escHtml(t.title) + '</span>' +
              '<span style="flex-shrink:0;color:var(--text-secondary);margin-left:8px">' + (t.artist ? escHtml(t.artist) : '') + '</span>' +
            '</div>';
          }).join('') + '</div>';
      }

      $('#coll-detail-modal').style.display = 'block';
    }).catch(function(err) {
      toast('加载失败: ' + err.message, 'error');
    });
  }

  // ========== 下载全部 ==========
  function downloadCollection(id) {
    api('/api/collections/' + id).then(function(data) {
      if (!data.tracks || data.tracks.length === 0) {
        toast('歌单中没有歌曲，请先刷新', 'warning');
        return;
      }

      // 用现有 music 模块的批量下载功能
      // 先把状态设为歌单歌曲
      var songs = data.tracks.map(function(t) {
        return {
          title: t.title,
          artist: t.artist,
          platform: t.platform,
          song_id: t.song_id,
          album: t.album || ''
        };
      });

      state.playlistSongs = null;
      state.songs = songs;

      // 切换到音乐下载面板渲染歌曲列表
      var musicNav = $('.nav-item[data-tab="music"]');
      if (musicNav) musicNav.click();

      // 渲染歌曲
      if (typeof renderResults === 'function') {
        renderResults();
      }

      // 开始逐一下载
      toast('开始下载 ' + songs.length + ' 首歌曲...', 'info');
      songs.forEach(function(s, i) {
        setTimeout(function() {
          var btn = document.querySelector('.dl-btn[data-id="' + s.song_id + '"]');
          if (btn && typeof handleDownload === 'function') {
            handleDownload(btn);
          }
        }, i * 500);
      });

      $('#coll-detail-modal').style.display = 'none';
    }).catch(function(err) {
      toast('下载失败: ' + err.message, 'error');
    });
  }

  // ========== tab 切换时初始化 ==========
  // 监听 nav 点击，切换到此 tab 时渲染
  document.addEventListener('DOMContentLoaded', function() {
    // 观察侧边栏点击
    $$('.nav-item[data-tab="collections"]').forEach(function(item) {
      item.addEventListener('click', function() {
        setTimeout(init, 50);
      });
    });
  });

  // 外部也可直接调
  window.initCollections = init;

  // 模块加载时自动尝试初始化（如果已经是活跃 tab）
  setTimeout(function() {
    if ($('#panel-collections') && $('#panel-collections').classList.contains('active')) {
      init();
    }
  }, 100);

})();
