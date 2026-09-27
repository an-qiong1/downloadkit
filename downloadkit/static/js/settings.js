(function() {
  'use strict';

  // 系统代理探测值（settings/get 附带），「跟随系统」态回显与测试都用它
  var systemProxyValue = '';

  // ========== 加载设置 ==========
  window.loadSettings = function() {
    api('/api/settings/get').then(function(data) {
      var s = data.settings || {};
      
      // General
      var gen = s.general || {};
      $('#setting-download-dir').value = gen.download_dir || '~/Downloads/DownloadKit';
      $('#setting-max-concurrent').value = gen.max_concurrent || 3;
      $('#setting-log-level').value = gen.log_level || 'INFO';

      // Type-specific download dirs
      $('#setting-download-dir-music').value = gen.download_dir_music || '~/Downloads/DownloadKit/music';
      $('#setting-download-dir-video').value = gen.download_dir_video || '~/Downloads/DownloadKit/videos';
      $('#setting-download-dir-animated').value = gen.download_dir_animated || '~/Downloads/DownloadKit/animated';
      $('#setting-download-dir-images').value = gen.download_dir_images || '~/Downloads/DownloadKit/images';
      
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

      // 关闭窗口是否最小化到托盘（存 config.toml，跟着「保存」一起提交）
      if ($('#setting-close-to-tray')) {
        $('#setting-close-to-tray').checked = gen.close_to_tray === true;
      }

      // 开机自启动写的是注册表、不在 config.toml 里，得单独查一次
      loadAutostartStatus();

      // Proxy（三态 P3-1：off / system / manual）
      var proxy = s.proxy || {};
      var proxyMode = proxy.mode;
      if (proxyMode !== 'off' && proxyMode !== 'system' && proxyMode !== 'manual') {
        // 旧配置没有 mode 字段：与服务端 proxy.resolve_mode 同一套推导，
        // 两边不一致会出现「界面显示手动、实际走系统代理」的分裂
        proxyMode = proxy.enabled === false ? 'off'
          : (proxy.global || proxy.youtube || proxy.douyin ||
             proxy.bilibili || proxy.xiaohongshu) ? 'manual'
          : 'system';
      }
      var modeRadio = $('#setting-proxy-mode-' + proxyMode);
      if (modeRadio) modeRadio.checked = true;
      systemProxyValue = data.proxy_system || '';
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

      // Update download dir display: show actual resolved absolute path + status
      updateDownloadDirDisplay(gen.download_dir || './downloads');

      // 分类路径只读预览跟着填一次
      renderDirPreview();

      // 异步填完根目录后同步「已知根目录」，否则首次改目录时分类不会跟着走
      lastDirRoot = String($('#setting-download-dir').value || '').trim();
    }).catch(function(err) {
      toast('加载设置失败: ' + err.message, 'error');
    });
  };

  // ========== 显示下载目录的实际路径和状态 ==========
  function updateDownloadDirDisplay(rawPath) {
    var actualEl = $('#setting-download-dir-actual');
    var statusEl = $('#setting-download-dir-status');
    if (!actualEl) return;

    api('/api/settings/download-dir-info?path=' + encodeURIComponent(rawPath || ''))
      .then(function(info) {
        actualEl.textContent = info.absolute || '(未解析)';
        actualEl.title = info.absolute || '';
        if (info.ok) {
          statusEl.innerHTML = '<span style="color:var(--success)">✓ 可用</span>';
        } else {
          var msg = (typeof info.message === 'string') ? info.message : (info.message && (info.message.error || info.message.detail)) || '不可用';
          var tip = (typeof info.message === 'string') ? info.message : JSON.stringify(info.message || '');
          statusEl.innerHTML = '<span style="color:var(--error)" title="' + tip.replace(/"/g, '&quot;') + '">✗ ' + msg + '</span>';
        }
      })
      .catch(function(err) {
        actualEl.textContent = '(检查失败)';
        var errMsg = (err && err.message) ? err.message : String(err);
        statusEl.innerHTML = '<span style="color:var(--error)">✗ ' + errMsg + '</span>';
      });
  }

  // ========== 分类路径只读预览（P1-3：主界面只留总目录）==========
  // input 后缀 → 实际文件夹名（video 那一栏的文件夹叫 videos）
  var DIR_PREVIEW_CATS = { music: 'music', video: 'videos', animated: 'animated', images: 'images' };

  // 根目录的「上一次已知值」。放模块级：loadSettings 异步填值时也要刷新，
  // 否则 change 事件里闭包捕获的还是初始化时的空串，syncCategoryDirs 会提前 return，
  // 分类目录就不同步了（2026-09-27 走查时发现）。
  var lastDirRoot = '';

  function renderDirPreview() {
    var rootEl = $('#setting-download-dir');
    var root = String(rootEl ? rootEl.value : '').replace(/[\\/]+$/, '');
    if (!root) return;
    Object.keys(DIR_PREVIEW_CATS).forEach(function(key) {
      var code = $('#dir-preview-' + key);
      if (!code) return;
      var catEl = $('#setting-download-dir-' + key);
      var v = String(catEl && catEl.value || '').trim();
      // 分类没被单独改过（空值 / 等于根目录派生值）就展示派生路径
      code.textContent = v ? v : (root + '/' + DIR_PREVIEW_CATS[key]);
      code.title = code.textContent;
    });
  }

  // ========== Windows 原生目录选择 ==========
  function pickDirectory(inputId) {
    var input = $('#' + inputId);
    if (!input) return;
    var initial = input.value || '';

    // 按钮置灰
    var btn = document.querySelector('[id^="setting-browse-dir"][id$="' + inputId.replace('setting-download-dir-', '').replace('setting-download-dir', '') + '"]');
    // 简单方案：直接 disable 所有 browse 按钮中跟当前 inputId 匹配的
    var allBrowse = document.querySelectorAll('[id^="setting-browse-"]');
    allBrowse.forEach(function(b) { b.disabled = true; });

    api('/api/utils/pick-directory', {
      method: 'POST',
      body: { initial: initial }
    })
    .then(function(res) {
      allBrowse.forEach(function(b) { b.disabled = false; });
      if (!res || !res.ok) {
        if (res && res.cancelled) {
          // 用户取消，静默
          return;
        }
        toast('选择目录失败: ' + (res && res.error || '未知错误'), 'error');
        return;
      }
      input.value = res.path;
      // 触发 input 事件让"实际路径"和"状态"实时刷新
      input.dispatchEvent(new Event('input', { bubbles: true }));
      // 程序赋值不会自己发 change，手动补一个 —— 根目录的 change 监听靠它
      // 把分类目录一起带过去（见 syncCategoryDirs）
      input.dispatchEvent(new Event('change', { bubbles: true }));
      toast('已选择：' + res.path, 'success');
    })
    .catch(function(err) {
      allBrowse.forEach(function(b) { b.disabled = false; });
      toast('请求失败: ' + err.message, 'error');
    });
  }

  // ========== Update proxy field state ==========
  function currentProxyMode() {
    var el = document.querySelector('input[name="setting-proxy-mode"]:checked');
    return el ? el.value : 'system';
  }

  function updateProxyFields() {
    var mode = currentProxyMode();
    var fields = [
      'setting-proxy-global', 'setting-proxy-youtube',
      'setting-proxy-douyin', 'setting-proxy-bilibili', 'setting-proxy-xiaohongshu'
    ];
    fields.forEach(function(id) {
      // 只有手动模式才让编辑：关闭/跟随系统下填的地址不生效，
      // 留着可编辑会让人以为改了就有效
      $('#' + id).disabled = (mode !== 'manual');
    });
    updateProxySystemHint();
  }

  // 「跟随系统」态回显系统代理探测值，否则这一态就是个黑盒
  function updateProxySystemHint() {
    var hint = $('#proxy-system-hint');
    if (!hint) return;
    if (currentProxyMode() === 'system') {
      hint.style.display = '';
      hint.textContent = systemProxyValue
        ? '当前系统代理：' + systemProxyValue
        : '未检测到系统代理设置（当前等于直连）';
    } else {
      hint.style.display = 'none';
    }
  }

  // ========== 代理测试（P3-1）==========
  // 测「当前模式实际会用的出口」：关闭→直连、跟随系统→系统代理、
  // 手动→全局地址。端点永远 200，可用性看 body.ok。
  function testProxy() {
    var mode = currentProxyMode();
    var out = $('#proxy-test-result');
    var proxy = '';
    if (mode === 'system') {
      proxy = systemProxyValue;
      if (!proxy) {
        out.textContent = '未检测到系统代理设置';
        out.style.color = 'var(--error)';
        return;
      }
    } else if (mode === 'manual') {
      proxy = ($('#setting-proxy-global').value || '').trim();
      if (!proxy) {
        out.textContent = '请先填写全局代理地址';
        out.style.color = 'var(--error)';
        return;
      }
    }
    // off / 空值 = 测直连，验证网络本身通不通

    var btn = $('#proxy-test-btn');
    btn.disabled = true;
    btn.textContent = '测试中…';
    out.textContent = '';
    api('/api/proxy/test', { method: 'POST', body: { proxy: proxy } })
      .then(function(r) {
        out.textContent = r.message || (r.ok ? '连接成功' : '连接失败');
        out.style.color = r.ok ? 'var(--success)' : 'var(--error)';
      })
      .catch(function(err) {
        out.textContent = '测试失败: ' + err.message;
        out.style.color = 'var(--error)';
      })
      .finally(function() {
        btn.disabled = false;
        btn.textContent = '测试连接';
      });
  }

  // ========== 开机自启动 ==========
  // 与其它设置分开处理的两个原因：
  //   1. 它写的是注册表（系统状态），不是 config.toml；
  //   2. 勾完必须立即生效 —— 攒到「保存」再提交，用户会以为开关坏了。
  function loadAutostartStatus() {
    var box = $('#setting-autostart');
    var hint = $('#setting-autostart-hint');
    if (!box) return;
    api('/api/settings/autostart').then(function(st) {
      box.disabled = !st.available;
      box.checked = !!st.enabled;
      if (hint) {
        // 不可用时把原因亮出来（例如「源码运行没有可自启的程序」），
        // 否则用户点不动只会觉得程序有 bug
        hint.textContent = st.available ? '' : (st.reason || '当前环境不支持');
        hint.style.color = st.available ? 'var(--text-secondary)' : 'var(--warning)';
      }
    }).catch(function(err) {
      if (hint) { hint.textContent = '查询失败: ' + err.message; hint.style.color = 'var(--error)'; }
    });
  }

  function toggleAutostart(enabled) {
    var box = $('#setting-autostart');
    var hint = $('#setting-autostart-hint');
    if (box) box.disabled = true;
    if (hint) { hint.textContent = '处理中…'; hint.style.color = 'var(--text-secondary)'; }

    api('/api/settings/autostart', { method: 'POST', body: { enabled: enabled } })
      .then(function(st) {
        if (box) { box.checked = !!st.enabled; box.disabled = !st.available; }
        if (hint) { hint.textContent = st.message || ''; hint.style.color = 'var(--success)'; }
        toast(st.message || '已更新', 'success');
      })
      .catch(function(err) {
        // 失败要把勾还原，不能停在「看起来已开启」的假状态上
        if (box) { box.checked = !enabled; box.disabled = false; }
        if (hint) { hint.textContent = err.message; hint.style.color = 'var(--error)'; }
        toast('设置失败: ' + err.message, 'error');
      });
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
      history_max_records: parseInt($('#setting-history-max-records').value) || 1000,
      close_to_tray: $('#setting-close-to-tray') ? $('#setting-close-to-tray').checked : false
    };
    
    // Proxy（三态：mode 是唯一真值；旧 enabled 字段不再写入，
    // 服务端 resolve_mode 先读 mode，残留的旧值不会被读到）
    data.proxy = {
      mode: currentProxyMode(),
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
      $('#settings-save').innerHTML = '<i data-lucide="save"></i>保存';
      lucide.createIcons();
    });
  }

  // ========== 恢复默认 ==========
  async function resetDefaults() {
    if (!(await uiConfirm('确定恢复默认设置？'))) return;
    
    var defaults = {
      general: { download_dir: '~/Downloads/DownloadKit', download_dir_music: '~/Downloads/DownloadKit/music', download_dir_video: '~/Downloads/DownloadKit/videos', download_dir_animated: '~/Downloads/DownloadKit/animated', download_dir_images: '~/Downloads/DownloadKit/images', max_concurrent: 3, log_level: 'INFO', rename_strategy: 'skip', motion_photo_default: true, history_max_records: 1000, close_to_tray: false },
      proxy: { mode: 'system', global: '', youtube: '', douyin: '', bilibili: '', xiaohongshu: '' },
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

  // ========== 设置导出 / 导入（P3-3）==========
  // 导出：现拉一次 /api/settings/get（不拿页面里可能过期的值），
  // 落成带时间戳的 JSON 文件。只含 general/proxy/cookie/subscription
  // 四段 —— cookie 段是文件路径不是 Cookie 内容，导出文件不携带
  // 登录态；subscription 是轮询偏好（开关/周期），换机时也该跟着走。
  function exportSettings() {
    api('/api/settings/get').then(function(data) {
      var s = data.settings || {};
      var payload = {
        app: 'downloadkit',
        exported_at: new Date().toISOString(),
        settings: {
          general: s.general || {},
          proxy: s.proxy || {},
          cookie: s.cookie || {},
          subscription: s.subscription || {}
        }
      };
      var blob = new Blob([JSON.stringify(payload, null, 2)],
                          { type: 'application/json' });
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      var d = new Date();
      function pad(n) { return (n < 10 ? '0' : '') + n; }
      a.href = url;
      a.download = 'downloadkit-settings-' +
        d.getFullYear() + pad(d.getMonth() + 1) + pad(d.getDate()) + '.json';
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast('设置已导出为 JSON 文件', 'success');
    }).catch(function(err) {
      toast('导出失败: ' + err.message, 'error');
    });
  }

  // 导入：段级白名单（general/proxy/cookie/subscription 且必须是
  // 对象），其它键一律丢掉 —— config.toml 只该有应用认识的段，
  // 脏数据进去了没有地方报错，只会安静地留着。每段都允许缺失，
  // 文件里有哪段就更哪段（settings/update 本来就按段更新）。
  function handleImportFile(e) {
    var file = e.target.files && e.target.files[0];
    e.target.value = '';   // 先清掉，同一个文件改完再导一次才选得动
    if (!file) return;

    var reader = new FileReader();
    reader.onload = async function() {
      var data;
      try {
        data = JSON.parse(reader.result);
      } catch (err) {
        toast('导入失败：不是有效的 JSON 文件', 'error');
        return;
      }
      if (!data || typeof data !== 'object' || Array.isArray(data)) {
        toast('导入失败：文件内容不是设置对象', 'error');
        return;
      }
      // 兼容带壳（{settings:{...}}）与裸（直接三段）两种写法
      var s = (data.settings && typeof data.settings === 'object')
        ? data.settings : data;
      var payload = {};
      ['general', 'proxy', 'cookie', 'subscription'].forEach(function(k) {
        if (s[k] && typeof s[k] === 'object' && !Array.isArray(s[k])) {
          payload[k] = s[k];
        }
      });
      var keys = Object.keys(payload);
      if (keys.length === 0) {
        toast('导入失败：没有可识别的设置段（general / proxy / cookie / subscription）', 'error');
        return;
      }
      if (!(await uiConfirm('导入将覆盖当前的【' + keys.join('、') + '】设置，确定？'))) {
        return;
      }
      api('/api/settings/update', { method: 'POST', body: payload }).then(function() {
        toast('设置已导入：' + keys.join('、'), 'success');
        loadSettings();
      }).catch(function(err) {
        toast('导入失败: ' + err.message, 'error');
      });
    };
    reader.onerror = function() {
      toast('导入失败：文件读取不出来', 'error');
    };
    reader.readAsText(file, 'utf-8');
  }

  // ========== 事件绑定 ==========
  document.addEventListener('DOMContentLoaded', function() {
    $('#settings-save').addEventListener('click', saveSettings);
    $('#settings-reset').addEventListener('click', resetDefaults);
    $('#settings-export').addEventListener('click', exportSettings);
    $('#settings-import').addEventListener('click', function() {
      $('#settings-import-file').click();
    });
    $('#settings-import-file').addEventListener('change', handleImportFile);
    // 三态 radio 各绑一次（change 不冒泡到 document 的委托里，直接绑最稳）
    ['off', 'system', 'manual'].forEach(function(m) {
      var el = $('#setting-proxy-mode-' + m);
      if (el) el.addEventListener('change', updateProxyFields);
    });
    $('#proxy-test-btn').addEventListener('click', testProxy);

    // 开机自启动勾完立即写注册表，不等「保存」
    var autostartBox = $('#setting-autostart');
    if (autostartBox) {
      autostartBox.addEventListener('change', function() {
        toggleAutostart(this.checked);
      });
    }

    // 目录浏览按钮 - 调 Windows 原生 FolderBrowserDialog
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
          pickDirectory(inputId);
        });
      }
    });

    // ===== 新增：下载目录相关事件 =====
    // 根目录换了，分类目录跟着走 —— 只改「由根目录派生出来的」，
    // 用户单独自定义过某个分类路径的不动（否则会把人家的手动设置冲掉）。
    function joinDir(root, cat) {
      return String(root || '').replace(/[\\/]+$/, '') + '/' + cat;
    }
    function syncCategoryDirs(oldRoot, newRoot) {
      if (!oldRoot || !newRoot || oldRoot === newRoot) return;
      // input 后缀 → 实际文件夹名（video 那一栏的文件夹叫 videos）
      var cats = { music: 'music', video: 'videos', animated: 'animated', images: 'images' };
      var changed = [];
      Object.keys(cats).forEach(function(key) {
        var el = $('#setting-download-dir-' + key);
        if (!el) return;
        var v = (el.value || '').trim();
        // 空值 / 正好等于「旧根目录/分类名」= 派生值 → 跟着改
        if (!v || v === joinDir(oldRoot, cats[key])) {
          el.value = joinDir(newRoot, cats[key]);
          changed.push(el.value);
        }
      });
      if (changed.length) {
        toast('分类目录已跟随更新：' + changed.length + ' 项', 'success');
      }
      renderDirPreview();
    }

    var dirInput = $('#setting-download-dir');
    if (dirInput) {
      // 根目录失焦 / 被目录对话框改掉时，把分类目录一起带过去
      dirInput.addEventListener('change', function() {
        syncCategoryDirs(lastDirRoot, dirInput.value);
        lastDirRoot = String(dirInput.value || '').trim();
        renderDirPreview();
      });

      // 输入时实时更新"实际路径"显示
      var debounceTimer = null;
      dirInput.addEventListener('input', function() {
        clearTimeout(debounceTimer);
        renderDirPreview();
        debounceTimer = setTimeout(function() {
          updateDownloadDirDisplay(dirInput.value);
        }, 300);
      });
    }

    // 高级折叠里单独改了某个分类 → 预览区跟着变
    Object.keys(DIR_PREVIEW_CATS).forEach(function(key) {
      var el = $('#setting-download-dir-' + key);
      if (el) el.addEventListener('input', renderDirPreview);
    });

    // "打开"按钮 - 在文件管理器中打开当前下载目录
    var openDirBtn = $('#setting-open-dir');
    if (openDirBtn) {
      openDirBtn.addEventListener('click', function() {
        var rawPath = dirInput ? dirInput.value : '';
        api('/api/settings/download-dir-info?path=' + encodeURIComponent(rawPath || ''))
          .then(function(info) {
            if (info.absolute && info.exists) {
              // 调用后端在系统文件管理器中打开目录
              api('/api/open-dir', {
                method: 'POST',
                body: { path: info.absolute }
              })
                .then(function() { toast('已打开：' + info.absolute, 'success'); })
                .catch(function(err) { toast('打开失败: ' + err.message, 'error'); });
            } else {
              toast('目录不存在：' + (info.message || info.absolute), 'error');
            }
          })
          .catch(function(err) { toast('获取路径失败: ' + err.message, 'error'); });
      });
    }

    // ===== 新增：Cookie 浏览器读取按钮 =====
    ['douyin', 'bilibili'].forEach(function(platform) {
      var btn = $('#cookie-load-' + platform);
      var sel = $('#cookie-browser-' + platform);
      var status = $('#cookie-status-' + platform);
      if (btn) {
        btn.addEventListener('click', function() {
          var browser = sel ? sel.value : 'edge';
          btn.disabled = true;
          if (status) status.textContent = '正在读取...';
          api('/api/cookies/load-from-browser', {
            method: 'POST',
            body: { platform: platform, browser: browser }
          })
          .then(async function(res) {
            btn.disabled = false;
            if (!res || !res.ok) {
              if (status) status.innerHTML = '<span style="color:var(--error)">✗ ' + (res.error || '读取失败') + '</span>';
              toast(res.error || '读取 Cookie 失败', 'error');
              return;
            }
            if (status) {
              status.innerHTML = '<span style="color:var(--success)">✓ 找到 ' + res.count + ' 个 Cookie</span>';
            }
            // 弹窗让用户确认保存
            var ok = await uiConfirm(
              '从 ' + res.browser + ' 浏览器找到 ' + res.count + ' 个 ' + (platform === 'douyin' ? '抖音' : 'B站') + ' Cookie。\n\n' +
              '点击 [确定] 保存到默认文件：\n' +
              '  ~/.downloadkit/cookies/' + platform + '.txt\n\n' +
              '点击 [取消] 不保存。'
            );
            if (ok && res.cookie_string) {
              api('/api/cookies/save', {
                method: 'POST',
                body: {
                  platform: platform,
                  cookie_string: res.cookie_string,
                  save_to_config: true
                }
              })
              .then(function(saveRes) {
                toast('已保存到：' + saveRes.path, 'success');
                if (status) status.innerHTML = '<span style="color:var(--success)">✓ 已保存 ' + res.count + ' 个 Cookie 到 ' + saveRes.path + '</span>';
                // 刷新对应输入框
                var inputId = platform === 'douyin' ? 'setting-cookie-douyin' : 'setting-cookie-bilibili';
                var input = $('#' + inputId);
                if (input) input.value = saveRes.path;
              })
              .catch(function(err) {
                toast('保存失败: ' + err.message, 'error');
                if (status) status.innerHTML = '<span style="color:var(--error)">✗ 保存失败: ' + err.message + '</span>';
              });
            }
          })
          .catch(function(err) {
            btn.disabled = false;
            if (status) status.innerHTML = '<span style="color:var(--error)">✗ ' + err.message + '</span>';
            toast('请求失败: ' + err.message, 'error');
          });
        });
      }

      // ===== 新增："🌐 登录并获取"按钮（新流程）=====
      var loginBtn = $('#cookie-login-' + platform);
      if (loginBtn) {
        loginBtn.addEventListener('click', function() {
          var sel2 = $('#cookie-browser-' + platform);
          var browser = sel2 ? sel2.value : 'edge';
          var platformName = platform === 'douyin' ? '抖音' : 'B站';
          openCookieLoginFlow(platform, platformName, browser);
        });
      }
    });

    // ========== "登录并获取"流程 ==========
    function openCookieLoginFlow(platform, platformName, browser) {
      // 1. 调后端在默认浏览器打开登录页
      api('/api/cookies/open-login?platform=' + encodeURIComponent(platform))
        .then(function(res) {
          if (!res || !res.url) {
            toast('无法打开登录页', 'error');
            return;
          }

          // 2. 弹"等待登录"卡片
          var overlay = document.createElement('div');
          overlay.className = 'dir-browser-overlay';
          var modal = document.createElement('div');
          modal.className = 'dir-browser-modal';
          modal.innerHTML =
            '<h4 class="dir-browser-title">🌐 正在打开 ' + platformName + ' 登录页</h4>' +
            '<div style="padding:12px 0;font-size:13px;line-height:1.7">' +
              '<p>已在你的 <b>' + (browser === 'chrome' ? 'Chrome' : 'Edge') + '</b> 浏览器中打开登录页。</p>' +
              '<p style="margin-top:8px">请在浏览器中完成以下步骤：</p>' +
              '<ol style="margin:8px 0 8px 20px;padding:0;color:var(--text-secondary)">' +
                '<li>登录你的 ' + platformName + ' 账号</li>' +
                '<li>登录成功后<b>保持浏览器开着</b>，<b>不要退出登录</b></li>' +
                '<li>回到本窗口，点击下方"已完成登录"按钮</li>' +
              '</ol>' +
              (res.opened
                ? ''
                : '<p style="margin-top:8px;color:var(--warning);font-size:12px">⚠ 自动打开失败，请手动复制此链接到浏览器打开：<br>' +
                  '<code style="display:inline-block;margin-top:4px;background:var(--bg-secondary);padding:4px 8px;border-radius:3px;word-break:break-all;user-select:all">' + res.url + '</code></p>'
              ) +
            '</div>' +
            '<div class="dir-browser-footer" style="display:flex;gap:8px;justify-content:flex-end">' +
              '<button class="btn btn-secondary" id="cookie-login-cancel">取消</button>' +
              '<button class="btn btn-primary" id="cookie-login-done">✅ 已完成登录</button>' +
            '</div>';

          overlay.appendChild(modal);
          document.body.appendChild(overlay);

          // 关闭
          function close() { document.body.removeChild(overlay); }

          // 取消
          $('#cookie-login-cancel').addEventListener('click', close);

          // 点击遮罩关闭
          overlay.addEventListener('click', function(e) {
            if (e.target === overlay) close();
          });

          // 3. 用户点"已完成登录" → 读取 Cookie
          $('#cookie-login-done').addEventListener('click', function() {
            var doneBtn = $('#cookie-login-done');
            doneBtn.disabled = true;
            doneBtn.textContent = '正在读取...';
            var status = $('#cookie-status-' + platform);
            if (status) status.textContent = '正在从浏览器读取...';

            api('/api/cookies/load-from-browser', {
              method: 'POST',
              body: { platform: platform, browser: browser }
            })
            .then(function(loadRes) {
              close();
              if (!loadRes || !loadRes.ok) {
                if (status) status.innerHTML = '<span style="color:var(--error)">✗ ' + (loadRes.error || '读取失败') + '</span>';
                toast(loadRes.error || '读取 Cookie 失败', 'error');
                return;
              }
              if (loadRes.count === 0) {
                if (status) status.innerHTML = '<span style="color:var(--warning)">⚠ 未找到 ' + platformName + ' Cookie，请确认浏览器中已登录</span>';
                toast('未找到 ' + platformName + ' Cookie', 'error');
                return;
              }
              // 4. 直接保存（无需 confirm，已经过"已完成登录"确认）
              api('/api/cookies/save', {
                method: 'POST',
                body: {
                  platform: platform,
                  cookie_string: loadRes.cookie_string,
                  save_to_config: true
                }
              })
              .then(function(saveRes) {
                toast('已保存 ' + loadRes.count + ' 个 ' + platformName + ' Cookie', 'success');
                if (status) status.innerHTML = '<span style="color:var(--success)">✓ 已保存 ' + loadRes.count + ' 个 Cookie</span>';
                var inputId = platform === 'douyin' ? 'setting-cookie-douyin' : 'setting-cookie-bilibili';
                var input = $('#' + inputId);
                if (input) input.value = saveRes.path;
              })
              .catch(function(err) {
                if (status) status.innerHTML = '<span style="color:var(--error)">✗ 保存失败: ' + err.message + '</span>';
                toast('保存失败: ' + err.message, 'error');
              });
            })
            .catch(function(err) {
              close();
              var status = $('#cookie-status-' + platform);
              if (status) status.innerHTML = '<span style="color:var(--error)">✗ ' + err.message + '</span>';
              toast('请求失败: ' + err.message, 'error');
            });
          });
        })
        .catch(function(err) {
          toast('无法打开登录页: ' + err.message, 'error');
        });
    }
  });
})();
