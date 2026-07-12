(function() {
  'use strict';

  // ========== 加载设置 ==========
  window.loadSettings = function() {
    api('/api/settings/get').then(function(data) {
      var s = data.settings || {};
      
      // General
      var gen = s.general || {};
      $('#setting-download-dir').value = gen.download_dir || './downloads';
      $('#setting-max-concurrent').value = gen.max_concurrent || 3;
      $('#setting-log-level').value = gen.log_level || 'INFO';
      
      // Type-specific download dirs
      $('#setting-download-dir-music').value = gen.download_dir_music || './downloads/music';
      $('#setting-download-dir-video').value = gen.download_dir_video || './downloads/videos';
      $('#setting-download-dir-animated').value = gen.download_dir_animated || './downloads/animated';
      $('#setting-download-dir-images').value = gen.download_dir_images || './downloads/images';
      
      // Rename strategy
      if ($('#setting-rename-strategy')) {
        $('#setting-rename-strategy').value = gen.rename_strategy || 'skip';
      }
      
      // Motion photo default
      if ($('#setting-motion-photo-default')) {
        $('#setting-motion-photo-default').checked = gen.motion_photo_default !== false;
      }
      
      // History max records
      if ($('#setting-history-max-records')) {
        $('#setting-history-max-records').value = gen.history_max_records || 1000;
      }
      
      // Proxy
      var proxy = s.proxy || {};
      $('#setting-proxy-enabled').checked = proxy.enabled !== false;
      $('#setting-proxy-global').value = proxy.global || '';
      $('#setting-proxy-youtube').value = proxy.youtube || '';
      $('#setting-proxy-douyin').value = proxy.douyin || '';
      $('#setting-proxy-bilibili').value = proxy.bilibili || '';
      $('#setting-proxy-xiaohongshu').value = proxy.xiaohongshu || '';
      
      // Cookie
      var cookie = s.cookie || {};
      $('#setting-cookie-douyin').value = cookie.douyin_path || '';
      
      // Bilibili cookie
      if ($('#setting-cookie-bilibili')) {
        $('#setting-cookie-bilibili').value = cookie.bilibili_path || '';
      }
      
      // Update proxy field disabled state
      updateProxyFields();
    }).catch(function(err) {
      toast('加载设置失败: ' + err.message, 'error');
    });
  };

  // ========== Update proxy field state ==========
  function updateProxyFields() {
    var enabled = $('#setting-proxy-enabled').checked;
    var fields = [
      'setting-proxy-global', 'setting-proxy-youtube',
      'setting-proxy-douyin', 'setting-proxy-bilibili', 'setting-proxy-xiaohongshu'
    ];
    fields.forEach(function(id) {
      $('#' + id).disabled = !enabled;
    });
  }

  // ========== 目录浏览弹窗 ==========
  function openDirBrowser(inputId, currentPath) {
    // 创建遮罩层和弹窗
    var overlay = document.createElement('div');
    overlay.className = 'dir-browser-overlay';
    
    var modal = document.createElement('div');
    modal.className = 'dir-browser-modal';
    
    modal.innerHTML =
      '<h4 class="dir-browser-title">选择目录</h4>' +
      '<div class="dir-browser-path-row">' +
        '<input class="search-input" id="dir-browse-path" type="text" placeholder="输入路径后按回车..." value="' + (currentPath || '') + '">' +
        '<button class="btn btn-secondary" id="dir-browse-go">打开</button>' +
      '</div>' +
      '<div id="dir-browse-list" class="dir-browser-list">' +
        '<div class="dir-browser-status">加载中...</div>' +
      '</div>' +
      '<div class="dir-browser-footer">' +
        '<button class="btn btn-secondary" id="dir-browse-cancel">取消</button>' +
      '</div>';
    
    overlay.appendChild(modal);
    document.body.appendChild(overlay);
    
    // 加载目录列表
    function loadDirs(path) {
      var listEl = $('#dir-browse-list');
      listEl.innerHTML = '<div class="dir-browser-status">加载中...</div>';
      
      api('/api/utils/list-directories', {
        method: 'POST',
        body: { path: path || '' }
      }).then(function(data) {
        var dirs = data.directories || [];
        listEl.innerHTML = '';
        
        if (!path && dirs.length === 0) {
          listEl.innerHTML = '<div class="dir-browser-status">无法获取目录列表</div>';
          return;
        }
        
        // 返回上级
        if (path) {
          var parentItem = document.createElement('div');
          parentItem.className = 'dir-browser-item';
          parentItem.innerHTML = '<span class="dir-browser-parent-item">.. (返回上级)</span>';
          parentItem.addEventListener('click', function() {
            var normalized = path.replace(/[\\\/]+$/, '');
            var idx = Math.max(normalized.lastIndexOf('/'), normalized.lastIndexOf('\\'));
            if (idx <= 0) { loadDirs(''); return; }
            loadDirs(normalized.substring(0, idx));
          });
          listEl.appendChild(parentItem);
        }
        
        // 目录列表
        dirs.forEach(function(dir) {
          var item = document.createElement('div');
          item.className = 'dir-browser-item';
          
          var nameSpan = document.createElement('span');
          nameSpan.className = 'dir-browser-item-name';
          nameSpan.innerHTML = '<i data-lucide="folder"></i> ' + (dir.name || dir.path);
          nameSpan.addEventListener('click', function() { loadDirs(dir.path); });
          item.appendChild(nameSpan);
          
          var selectBtn = document.createElement('button');
          selectBtn.className = 'btn btn-secondary dir-browser-select-btn';
          selectBtn.textContent = '选择';
          selectBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            $('#' + inputId).value = dir.path;
            document.body.removeChild(overlay);
          });
          item.appendChild(selectBtn);
          
          listEl.appendChild(item);
        });
        
        // 刷新 lucide 图标
        if (typeof lucide !== 'undefined' && lucide.createIcons) {
          try { lucide.createIcons(); } catch(e) {}
        }
      }).catch(function(err) {
        listEl.innerHTML = '<div class="dir-browser-error">加载失败: ' + err.message + '</div>';
      });
    }
    
    // 绑定事件
    $('#dir-browse-go').addEventListener('click', function() {
      loadDirs($('#dir-browse-path').value.trim());
    });
    
    $('#dir-browse-cancel').addEventListener('click', function() {
      document.body.removeChild(overlay);
    });
    
    $('#dir-browse-path').addEventListener('keydown', function(e) {
      if (e.key === 'Enter') {
        loadDirs($('#dir-browse-path').value.trim());
      }
    });
    
    // 点击遮罩关闭
    overlay.addEventListener('click', function(e) {
      if (e.target === overlay) {
        document.body.removeChild(overlay);
      }
    });
    
    // 初始加载
    loadDirs(currentPath || '');
  }

  // ========== 保存设置 ==========
  function saveSettings() {
    var data = {};
    
    // General
    data.general = {
      download_dir: $('#setting-download-dir').value || './downloads',
      download_dir_music: $('#setting-download-dir-music').value || '',
      download_dir_video: $('#setting-download-dir-video').value || '',
      download_dir_animated: $('#setting-download-dir-animated').value || '',
      download_dir_images: $('#setting-download-dir-images').value || '',
      max_concurrent: parseInt($('#setting-max-concurrent').value) || 3,
      log_level: $('#setting-log-level').value,
      rename_strategy: $('#setting-rename-strategy').value || 'skip',
      motion_photo_default: $('#setting-motion-photo-default').checked,
      history_max_records: parseInt($('#setting-history-max-records').value) || 1000
    };
    
    // Proxy
    data.proxy = {
      enabled: $('#setting-proxy-enabled').checked,
      global: $('#setting-proxy-global').value || '',
      youtube: $('#setting-proxy-youtube').value || '',
      douyin: $('#setting-proxy-douyin').value || '',
      bilibili: $('#setting-proxy-bilibili').value || '',
      xiaohongshu: $('#setting-proxy-xiaohongshu').value || ''
    };
    
    // Cookie
    data.cookie = {
      douyin_path: $('#setting-cookie-douyin').value || '',
      bilibili_path: $('#setting-cookie-bilibili').value || ''
    };
    
    $('#settings-save').disabled = true;
    $('#settings-save').textContent = '保存中...';
    
    api('/api/settings/update', {
      method: 'POST',
      body: data
    }).then(function() {
      toast('设置已保存', 'success');
      loadSettings();
    }).catch(function(err) {
      toast('保存失败: ' + err.message, 'error');
    }).finally(function() {
      $('#settings-save').disabled = false;
      $('#settings-save').innerHTML = '<i data-lucide="save" style="width:14px;height:14px;margin-right:6px"></i>保存';
      lucide.createIcons();
    });
  }

  // ========== 恢复默认 ==========
  function resetDefaults() {
    if (!confirm('确定恢复默认设置？')) return;
    
    var defaults = {
      general: { download_dir: './downloads', download_dir_music: './downloads/music', download_dir_video: './downloads/videos', download_dir_animated: './downloads/animated', download_dir_images: './downloads/images', max_concurrent: 3, log_level: 'INFO', rename_strategy: 'skip', motion_photo_default: true, history_max_records: 1000 },
      proxy: { enabled: true, global: '', youtube: '', douyin: '', bilibili: '', xiaohongshu: '' },
      cookie: { douyin_path: '', bilibili_path: '' }
    };
    
    $('#settings-reset').disabled = true;
    
    api('/api/settings/update', {
      method: 'POST',
      body: defaults
    }).then(function() {
      toast('已恢复默认设置', 'success');
      loadSettings();
    }).catch(function(err) {
      toast('恢复失败: ' + err.message, 'error');
    }).finally(function() {
      $('#settings-reset').disabled = false;
    });
  }

  // ========== 事件绑定 ==========
  document.addEventListener('DOMContentLoaded', function() {
    $('#settings-save').addEventListener('click', saveSettings);
    $('#settings-reset').addEventListener('click', resetDefaults);
    $('#setting-proxy-enabled').addEventListener('change', updateProxyFields);
    
    // 目录浏览按钮
    var browseMap = {
      'setting-browse-dir': 'setting-download-dir',
      'setting-browse-dir-music': 'setting-download-dir-music',
      'setting-browse-dir-video': 'setting-download-dir-video',
      'setting-browse-dir-animated': 'setting-download-dir-animated',
      'setting-browse-dir-images': 'setting-download-dir-images'
    };
    Object.keys(browseMap).forEach(function(btnId) {
      var btn = document.getElementById(btnId);
      if (btn) {
        btn.addEventListener('click', function() {
          var inputId = browseMap[btnId];
          var input = document.getElementById(inputId);
          openDirBrowser(inputId, input ? input.value : '');
        });
      }
    });
  });
})();
