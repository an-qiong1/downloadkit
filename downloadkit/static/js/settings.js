(function() {
  'use strict';

  // ========== 加载设置 ==========
  window.loadSettings = function() {
    api('/api/settings/get').then(function(data) {
      var s = data.settings || {};
      
      // General
      var gen = s.general || {};
      $('#setting-download-dir').value = gen.download_dir || '~/Downloads';
      $('#setting-max-concurrent').value = gen.max_concurrent || 3;
      $('#setting-log-level').value = gen.log_level || 'INFO';

      // Type-specific download dirs
      $('#setting-download-dir-music').value = gen.download_dir_music || '~/Downloads/music';
      $('#setting-download-dir-video').value = gen.download_dir_video || '~/Downloads/videos';
      $('#setting-download-dir-animated').value = gen.download_dir_animated || '~/Downloads/animated';
      $('#setting-download-dir-images').value = gen.download_dir_images || '~/Downloads/images';
      
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

      // Update download dir display: show actual resolved absolute path + status
      updateDownloadDirDisplay(gen.download_dir || './downloads');
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
          statusEl.innerHTML = '<span style="color:var(--danger)" title="' + tip.replace(/"/g, '&quot;') + '">✗ ' + msg + '</span>';
        }
      })
      .catch(function(err) {
        actualEl.textContent = '(检查失败)';
        var errMsg = (err && err.message) ? err.message : String(err);
        statusEl.innerHTML = '<span style="color:var(--danger)">✗ ' + errMsg + '</span>';
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
      body: JSON.stringify({ initial: initial })
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
      toast('已选择：' + res.path, 'success');
    })
    .catch(function(err) {
      allBrowse.forEach(function(b) { b.disabled = false; });
      toast('请求失败: ' + err.message, 'error');
    });
  }

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
      general: { download_dir: '~/Downloads', download_dir_music: '~/Downloads/music', download_dir_video: '~/Downloads/videos', download_dir_animated: '~/Downloads/animated', download_dir_images: '~/Downloads/images', max_concurrent: 3, log_level: 'INFO', rename_strategy: 'skip', motion_photo_default: true, history_max_records: 1000, close_to_tray: false },
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
    var dirInput = $('#setting-download-dir');
    if (dirInput) {
      // 输入时实时更新"实际路径"显示
      var debounceTimer = null;
      dirInput.addEventListener('input', function() {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(function() {
          updateDownloadDirDisplay(dirInput.value);
        }, 300);
      });
    }

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
                body: JSON.stringify({ path: info.absolute })
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
            body: JSON.stringify({ platform: platform, browser: browser })
          })
          .then(function(res) {
            btn.disabled = false;
            if (!res || !res.ok) {
              if (status) status.innerHTML = '<span style="color:var(--danger)">✗ ' + (res.error || '读取失败') + '</span>';
              toast(res.error || '读取 Cookie 失败', 'error');
              return;
            }
            if (status) {
              status.innerHTML = '<span style="color:var(--success)">✓ 找到 ' + res.count + ' 个 Cookie</span>';
            }
            // 弹窗让用户确认保存
            var ok = window.confirm(
              '从 ' + res.browser + ' 浏览器找到 ' + res.count + ' 个 ' + (platform === 'douyin' ? '抖音' : 'B站') + ' Cookie。\n\n' +
              '点击 [确定] 保存到默认文件：\n' +
              '  ~/.downloadkit/cookies/' + platform + '.txt\n\n' +
              '点击 [取消] 不保存。'
            );
            if (ok && res.cookie_string) {
              api('/api/cookies/save', {
                method: 'POST',
                body: JSON.stringify({
                  platform: platform,
                  cookie_string: res.cookie_string,
                  save_to_config: true
                })
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
                if (status) status.innerHTML = '<span style="color:var(--danger)">✗ 保存失败: ' + err.message + '</span>';
              });
            }
          })
          .catch(function(err) {
            btn.disabled = false;
            if (status) status.innerHTML = '<span style="color:var(--danger)">✗ ' + err.message + '</span>';
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
              body: JSON.stringify({ platform: platform, browser: browser })
            })
            .then(function(loadRes) {
              close();
              if (!loadRes || !loadRes.ok) {
                if (status) status.innerHTML = '<span style="color:var(--danger)">✗ ' + (loadRes.error || '读取失败') + '</span>';
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
                body: JSON.stringify({
                  platform: platform,
                  cookie_string: loadRes.cookie_string,
                  save_to_config: true
                })
              })
              .then(function(saveRes) {
                toast('已保存 ' + loadRes.count + ' 个 ' + platformName + ' Cookie', 'success');
                if (status) status.innerHTML = '<span style="color:var(--success)">✓ 已保存 ' + loadRes.count + ' 个 Cookie</span>';
                var inputId = platform === 'douyin' ? 'setting-cookie-douyin' : 'setting-cookie-bilibili';
                var input = $('#' + inputId);
                if (input) input.value = saveRes.path;
              })
              .catch(function(err) {
                if (status) status.innerHTML = '<span style="color:var(--danger)">✗ 保存失败: ' + err.message + '</span>';
                toast('保存失败: ' + err.message, 'error');
              });
            })
            .catch(function(err) {
              close();
              var status = $('#cookie-status-' + platform);
              if (status) status.innerHTML = '<span style="color:var(--danger)">✗ ' + err.message + '</span>';
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
