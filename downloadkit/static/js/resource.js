// ========== 资源解析模块（智能识别） ==========
  // 检测平台
  function detectPlatform(url) {
    if (url.includes('douyin.com') || url.includes('tiktok.com')) return 'douyin';
    if (url.includes('bilibili.com') || url.includes('b23.tv')) return 'bilibili';
    if (url.includes('youtube.com') || url.includes('youtu.be')) return 'youtube';
    if (url.includes('xiaohongshu.com') || url.includes('xhslink.com')) return 'xiaohongshu';
    // 兜底：任何 http(s) 链接走 generic（直链 m3u8/mp4 或普通网页）
    if (/^https?:\/\//i.test(url)) return 'generic';
    return null;
  }
  
  // 统一输入处理：单行回车直接解析，多行时回车换行继续粘贴（Shift+Enter 恒换行）
  $('#resource-input').addEventListener('keydown', function(e) {
    if (e.key !== 'Enter') return;
    if (e.shiftKey) return;
    var lines = $('#resource-input').value.split('\n').filter(function(l) { return l.trim(); });
    if (lines.length <= 1) {
      e.preventDefault();
      handleResourceInput();
    }
  });
  $('#resource-btn').addEventListener('click', handleResourceInput);
  
  // 资源解析框清空按钮 + 多行自适应高度（1~6 行）
  var resourceInput = $('#resource-input');
  var resourceClear = $('#resource-clear');
  function autoResizeResourceInput() {
    resourceInput.style.height = 'auto';
    resourceInput.style.height = Math.min(resourceInput.scrollHeight, 6 * 21 + 10) + 'px';
  }
  resourceInput.addEventListener('input', function() {
    resourceClear.classList.toggle('show', resourceInput.value.length > 0);
    autoResizeResourceInput();
  });
  resourceClear.addEventListener('click', function() {
    resourceInput.value = '';
    resourceClear.classList.remove('show');
    autoResizeResourceInput();
    resourceInput.focus();
    // 隐藏预览
    $('#resource-preview').style.display = 'none';
    $('#resource-status').style.display = 'none';
  });
  
  function handleResourceInput() {
    var input = $('#resource-input').value.trim();
    if (!input) return;
    
    // 检测多行输入 → 批量解析
    var lines = input.split('\n').filter(function(l) { return l.trim(); });
    if (lines.length > 1) {
      handleBatchInput(lines);
      return;
    }
    
    // 尝试从输入中提取URL（支持抖音口令等混合文本）
    var url = extractUrl(input);
    if (!url) {
      toast('未找到有效链接，请输入URL或抖音口令', 'error');
      return;
    }
    
    
    var platform = detectPlatform(url);
    
    if (!platform) {
      toast('不是有效的 http(s) 链接', 'error');
      return;
    }
    
    // 使用统一解析接口
    parseVideo(url, platform);
  }
  
  // 统一视频解析
  function parseVideo(url, platform) {
    var btn = $('#resource-btn');
    btn.disabled = true;
    
    var st = $('#resource-status');
    st.style.display = 'block';
    st.innerHTML = '<span class="spinner"></span> 正在解析…';
    st.className = 'status-msg';
    $('#resource-preview').style.display = 'none';
    
    api('/api/video/parse', { method: 'POST', body: { url: url }, timeout: 120 }).then(function(data) {
      st.style.display = 'none';
      showResourcePreview(data, platform, url);
    }).catch(function(err) {
      // 解析失败往往正是 L1 对该站无效（WAF 重置连接等）——
      // 失败提示里直接给 L2 深度嗅探入口，不让流程断在这里
      st.className = 'status-msg error';
      st.innerHTML = '解析失败：' + escHtml(err.message) +
        ' <button class="btn btn-secondary" id="status-sniff-btn">' +
        '<i data-lucide="search"></i>深度嗅探</button>' +
        ' <button class="btn btn-secondary" id="status-episodes-btn">' +
        '<i data-lucide="list"></i>展开选集</button>' +
        '<div id="sniff-result" class="sniff-result" style="display:none"></div>';
      lucide.createIcons();
      var sb = $('#status-sniff-btn');
      if (sb) {
        sb.onclick = function() { runDeepSniff(url, { title: '' }, sb); };
      }
      var eb = $('#status-episodes-btn');
      if (eb) {
        eb.onclick = function() { expandEpisodes(url, eb); };
      }
    }).finally(function() { 
      btn.disabled = false; 
    });
  }
  
  // 从单输入框检测多行时的批量处理
  function handleBatchInput(lines) {
    var urls = [];
    lines.forEach(function(line) {
      var url = extractUrl(line.trim());
      if (url) urls.push(url);
    });

    if (urls.length === 0) {
      toast('未找到有效链接', 'error');
      return;
    }

    var btn = $('#resource-btn');
    btn.disabled = true;

    var st = $('#resource-status');
    st.style.display = 'block';
    st.innerHTML = '<span class="spinner"></span> 正在解析 ' + urls.length + ' 个链接…';
    st.className = 'status-msg';
    $('#resource-preview').style.display = 'none';

    // 批量总时长随条数增长：下限 120s，每条再放宽 30s
    api('/api/video/batch-parse', {
      method: 'POST',
      body: { urls: urls },
      timeout: Math.max(120, urls.length * 30)
    }).then(function(data) {
      st.style.display = 'none';
      showInlineBatchResults(data.results || []);
    }).catch(function(err) {
      st.innerHTML = '解析失败：' + err.message;
      st.className = 'status-msg error';
    }).finally(function() {
      btn.disabled = false;
    });
  }

  // 显示批量解析结果（默认单输入框预览区；书签模式传 #bookmark-results）
  function showInlineBatchResults(results, targetSel) {
    var preview = $(targetSel || '#resource-preview');
    preview.style.display = 'block';
    preview.className = 'resource-preview-container';

    var platformColors = {
      'douyin': { bg: '#FF6B6B20', color: '#FF6B6B', label: '抖音' },
      'bilibili': { bg: '#00A1D620', color: '#00A1D6', label: 'B站' },
      'youtube': { bg: '#FF000020', color: '#FF0000', label: 'YouTube' },
      'xiaohongshu': { bg: '#FF244220', color: '#FF2442', label: '小红书' },
      'generic': { bg: '#BF5AF220', color: '#BF5AF2', label: '网页' }
    };

    var successCount = results.filter(function(r) { return r.status === 'success'; }).length;
    var failCount = results.length - successCount;

    var html = '';

    // 汇总栏
    html += '<div class="inline-batch-summary">' +
      '<span>解析完成：<strong class="text-success">' + successCount + ' 成功</strong>' +
      (failCount > 0 ? '，<strong class="text-error">' + failCount + ' 失败</strong>' : '') + '</span>';
    if (successCount > 0) {
      html += '<button class="btn btn-primary inline-batch-dl-all" style="padding:6px 14px;font-size:12px"><i data-lucide="download" style="width:12px;height:12px;margin-right:4px"></i>下载全部</button>';
    }
    html += '</div>';

    // 结果列表
    html += '<div class="batch-results-list" style="margin-top:0">';
    results.forEach(function(item, index) {
      var p = platformColors[item.platform] || { bg: '#86868B20', color: '#86868B', label: '未知' };
      var itemIcon = getContentTypeIcon(item.content_type);

      html += '<div class="batch-item" data-index="' + index + '">';
      html += '<span class="batch-item-idx">' + (index + 1) + '</span>';
      html += '<div class="batch-item-cover" style="background:linear-gradient(135deg,' + p.bg + ',' + p.bg.replace('20', '10') + ')"><i data-lucide="' + itemIcon + '"></i></div>';
      html += '<div class="batch-item-info">';
      html += '<div class="batch-item-title">' + escHtml(item.title || '未知标题') + '</div>';
      html += '<div class="batch-item-meta">' + escHtml(item.author || '未知作者') + ' · <span class="platform-tag" style="background:' + p.bg + ';color:' + p.color + ';margin-top:0">' + p.label + '</span>' +
        (item.suggested_name ? ' · <span style="color:var(--text-tertiary)">保存为 ' + escHtml(item.suggested_name) + '.mp4</span>' : '') + '</div>';
      html += '</div>';

      if (item.status === 'success') {
        html += '<button class="btn btn-primary inline-dl-btn" data-url="' + escAttr(item.url) + '" data-platform="' + escAttr(item.platform) + '"><i data-lucide="download" style="width:12px;height:12px;margin-right:4px"></i>下载</button>';
      } else {
        html += '<span class="batch-item-status failed" title="' + escAttr(item.error || '') + '">' + escHtml(item.error || '失败') + '</span>';
      }
      html += '</div>';
    });
    html += '</div>';

    preview.innerHTML = html;
    lucide.createIcons();

    // 绑定单个下载按钮（状态落在自己身上，见 downloadResource 的 btn 参数）
    preview.querySelectorAll('.inline-dl-btn').forEach(function(btn) {
      btn.addEventListener('click', function() {
        downloadResource(this.dataset.url, this.dataset.platform, this);
      });
    });

    // 绑定全部下载按钮（class 选择器按容器取，支持预览区/书签结果区两处）
    var dlAll = preview.querySelector('.inline-batch-dl-all');
    if (dlAll) {
      dlAll.addEventListener('click', function() {
        var urls = results.filter(function(r) { return r.status === 'success'; }).map(function(r) { return r.url; });
        if (urls.length > 0) {
          startBatchDownload(urls);
        }
      });
    }
  }

  // 根据内容类型获取图标名
  function getContentTypeIcon(contentType) {
    if (contentType === 'video') return 'film';
    if (contentType === 'image') return 'image';
    if (contentType === 'animated') return 'sparkles';
    return 'file';
  }

  // 图片灯箱
  var lightboxState = { images: [], currentIndex: 0 };

  function openLightbox(images, index) {
    lightboxState.images = images;
    lightboxState.currentIndex = index;
    renderLightbox();
  }

  function renderLightbox() {
    var existing = $('#preview-lightbox-el');
    if (existing) existing.remove();

    var overlay = document.createElement('div');
    overlay.className = 'preview-lightbox';
    overlay.id = 'preview-lightbox-el';

    var img = document.createElement('img');
    img.src = lightboxState.images[lightboxState.currentIndex].url || lightboxState.images[lightboxState.currentIndex];
    overlay.appendChild(img);

    if (lightboxState.images.length > 1) {
      var prevBtn = document.createElement('button');
      prevBtn.className = 'preview-lightbox-nav prev';
      prevBtn.innerHTML = '<i data-lucide="chevron-left"></i>';
      prevBtn.onclick = function(e) {
        e.stopPropagation();
        lightboxState.currentIndex = (lightboxState.currentIndex - 1 + lightboxState.images.length) % lightboxState.images.length;
        renderLightbox();
      };
      overlay.appendChild(prevBtn);

      var nextBtn = document.createElement('button');
      nextBtn.className = 'preview-lightbox-nav next';
      nextBtn.innerHTML = '<i data-lucide="chevron-right"></i>';
      nextBtn.onclick = function(e) {
        e.stopPropagation();
        lightboxState.currentIndex = (lightboxState.currentIndex + 1) % lightboxState.images.length;
        renderLightbox();
      };
      overlay.appendChild(nextBtn);
    }

    var closeBtn = document.createElement('button');
    closeBtn.className = 'preview-lightbox-close';
    closeBtn.innerHTML = '<i data-lucide="x"></i>';
    closeBtn.onclick = function() { overlay.remove(); };
    overlay.appendChild(closeBtn);

    overlay.addEventListener('click', function(e) {
      if (e.target === overlay) overlay.remove();
    });

    document.body.appendChild(overlay);
    lucide.createIcons();
  }

  // 显示资源预览
  function showResourcePreview(data, platform, url) {
    var preview = $('#resource-preview');
    preview.style.display = 'block';
    preview.className = 'resource-preview-container';

    var contentType = data.content_type || 'video';
    var iconName = getContentTypeIcon(contentType);

    var platformColors = {
      'douyin': { bg: '#FF6B6B20', color: '#FF6B6B', label: '抖音' },
      'bilibili': { bg: '#00A1D620', color: '#00A1D6', label: 'B站' },
      'youtube': { bg: '#FF000020', color: '#FF0000', label: 'YouTube' },
      'xiaohongshu': { bg: '#FF244220', color: '#FF2442', label: '小红书' },
      'generic': { bg: '#BF5AF220', color: '#BF5AF2', label: '网页' }
    };
    var p = platformColors[platform] || platformColors.douyin;

    var html = '' +
      '<div class="preview-header">' +
        '<div class="preview-header-icon ' + contentType + '"><i data-lucide="' + iconName + '"></i></div>' +
        '<div class="preview-header-info">' +
          '<div class="preview-header-title">' + escHtml(data.title || '无标题') + '</div>' +
          '<div class="preview-header-meta">' + escHtml(data.author || '未知作者') + ' · <span class="platform-tag" style="background:' + p.bg + ';color:' + p.color + ';margin-top:0">' + p.label + '</span></div>' +
        '</div>' +
        '<button class="btn btn-primary" id="resource-download-btn"><i data-lucide="download"></i>下载</button>' +
        (platform === 'generic'
          ? '<button class="btn btn-secondary" id="resource-sniff-btn"><i data-lucide="search"></i>深度嗅探</button>' +
            '<button class="btn btn-secondary" id="resource-episodes-btn"><i data-lucide="list"></i>展开选集</button>'
          : '') +
      '</div>' +
      // L2 嗅探结果容器（点击「深度嗅探」后填充流列表）
      (platform === 'generic'
        ? '<div id="sniff-result" class="sniff-result" style="display:none"></div>'
        : '');

    // 内容预览主体
    if (contentType === 'video' && data.video_url) {
      // 视频预览（通过服务端代理，携带Referer等鉴权头）
      var videoSrc = data.video_url;
      if (platform === 'douyin') {
        // 传原始分享链接和已解析视频URL，代理快速直连（不重解析）
        videoSrc = '/api/media/proxy?url=' + encodeURIComponent(url) + '&video_url=' + encodeURIComponent(data.video_url);
      } else if (platform === 'xiaohongshu') {
        videoSrc = '/api/media/proxy?url=' + encodeURIComponent(data.video_url);
      }
      html += '<div class="preview-body"><div class="preview-player">' +
        '<video controls autoplay muted playsinline preload="metadata">' +
          '<source src="' + escAttr(videoSrc) + '" type="video/mp4">' +
        '</video>' +
      '</div></div>';
    } else if (contentType === 'video' && data.cover) {
      // 无视频URL但有封面 - 显示封面截图
      var unavailableMsg = '该平台暂不支持在线预览';
      if (platform === 'bilibili' && data.duration) {
        unavailableMsg = '时长 ' + data.duration + (data.quality ? ' · ' + data.quality : '');
      } else if (platform === 'generic') {
        unavailableMsg = '网页视频 · 已解析，点击下载';
        if (data.duration) unavailableMsg += ' · 时长 ' + data.duration + ' 秒';
      }
      html += '<div class="preview-unavailable">' +
        '<i data-lucide="film"></i>' +
        '<span class="preview-unavailable-text">' + unavailableMsg + '</span>' +
        (data.cover ? '<img src="' + escAttr(data.cover) + '" style="max-width:360px;border-radius:6px;margin-top:8px;opacity:0.7" alt="封面">' : '') +
      '</div>';
    } else if (contentType === 'image' && data.images && data.images.length > 0) {
      // 图片画廊 - 网格布局，多图自适应
      var galleryDataKey = '_gallery_' + Date.now();
      window[galleryDataKey] = data.images;
      var gridClass = data.images.length >= 2 ? 'preview-gallery grid-layout' : 'preview-gallery';
      html += '<div class="preview-body"><div class="' + gridClass + '">';
      data.images.forEach(function(img, idx) {
        var imgUrl = img.url || img;
        html += '<div class="preview-gallery-item" data-gallery="' + galleryDataKey + '" data-index="' + idx + '">' +
          '<img src="' + escAttr(imgUrl) + '" alt="图片 ' + (idx + 1) + '" loading="lazy">' +
          (data.images.length > 1 ? '<span class="gallery-index">' + (idx + 1) + '/' + data.images.length + '</span>' : '') +
        '</div>';
      });
      html += '</div></div>';
    } else if (contentType === 'image' && data.cover) {
      // 单图
      var singleKey = '_single_' + Date.now();
      window[singleKey] = [{url: data.cover}];
      html += '<div class="preview-body"><div class="preview-gallery">' +
        '<div class="preview-gallery-item" data-gallery="' + singleKey + '" data-index="0">' +
          '<img src="' + escAttr(data.cover) + '" alt="封面" loading="lazy">' +
        '</div>' +
      '</div></div>';
    } else if (contentType === 'animated') {
      // 实况照片：图片网格展示 + 实况标记，不预览视频
      var liveImages = data.images || [];

      html += '<div class="preview-body">';

      // 实况照片横幅
      html += '<div style="display:flex;align-items:center;gap:8px;padding:10px 14px;background:linear-gradient(135deg,#5856D620,#5856D610);border-bottom:1px solid var(--border)">' +
        '<span style="display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:100px;background:#5856D6;color:white;font-size:11px;font-weight:600"><i data-lucide="sparkles" style="width:12px;height:12px"></i> 实况照片</span>' +
        '<span style="font-size:12px;color:var(--text-secondary)">' + liveImages.length + ' 张</span>' +
      '</div>';

      // 图片网格（同普通图文）
      if (liveImages.length > 0) {
        var liveDataKey = '_live_gallery_' + Date.now();
        window[liveDataKey] = liveImages;
        var gridClass = liveImages.length >= 2 ? 'preview-gallery grid-layout' : 'preview-gallery';
        html += '<div class="' + gridClass + '">';
        liveImages.forEach(function(img, idx) {
          var imgUrl = img.url || img;
          html += '<div class="preview-gallery-item" data-gallery="' + liveDataKey + '" data-index="' + idx + '">' +
            '<img src="' + escAttr(imgUrl) + '" alt="实况照片 ' + (idx + 1) + '" loading="lazy">' +
            '<span class="gallery-index">' + (idx + 1) + '/' + liveImages.length + '</span>' +
            '<span class="live-badge"><i data-lucide="sparkles" style="width:11px;height:11px"></i> 实况</span>' +
          '</div>';
        });
        html += '</div>';
      }

      html += '</div>';
    } else {
      // 兜底：无可用预览
      // generic（网页视频）常常拿不到封面且 m3u8 无法内联播放，
      // 但解析已成功、下载按钮可用 —— 不能显示成"不可用"
      var unavailableText = '暂无可用预览';
      if (platform === 'generic') {
        unavailableText = '网页视频 · 已解析，点击下载';
        if (data.duration) unavailableText += ' · 时长 ' + data.duration + ' 秒';
      }
      html += '<div class="preview-unavailable">' +
        '<i data-lucide="eye-off"></i>' +
        '<span class="preview-unavailable-text">' + unavailableText + '</span>' +
      '</div>';
    }

    // 底部操作栏
    html += '<div class="preview-footer">' +
      '<span class="platform-tag" style="background:' + p.bg + ';color:' + p.color + '">' + p.label + '</span>' +
      '<span style="font-size:12px;color:var(--text-tertiary)">' +
        (contentType === 'video' ? '视频' : contentType === 'image' ? '图文' : '实况照片') +
      '</span>' +
    '</div>';

    preview.innerHTML = html;
    lucide.createIcons();

    // === 视频错误处理（不销毁video，显示错误浮层带刷新按钮） ===
    function _showVideoError(video, shareUrl) {
      if (!video || !video.parentNode) return;
      // 避免重复创建错误提示
      if (video.parentNode.querySelector('.preview-video-error')) return;
      
      video.style.display = 'none';
      var errEl = document.createElement('div');
      errEl.className = 'preview-video-error';
      errEl.innerHTML = '<i data-lucide="alert-circle"></i>' +
        '<span class="preview-video-error-text">视频无法播放，可能链接已过期</span>' +
        '<button class="preview-video-refresh-btn" data-share-url="' + escAttr(shareUrl) + '">刷新链接</button>';
      video.parentNode.appendChild(errEl);
      
      // 刷新按钮：重新解析后重试
      errEl.querySelector('.preview-video-refresh-btn').addEventListener('click', function() {
        var sUrl = this.getAttribute('data-share-url');
        // 移除错误浮层
        if (errEl.parentNode) errEl.parentNode.removeChild(errEl);
        // 显示视频，加上loading指示器
        video.style.display = '';
        var player = video.closest('.preview-player');
        if (player) {
          var spinner = document.createElement('div');
          spinner.className = 'preview-video-loading';
          spinner.innerHTML = '<span class="spinner"></span>';
          player.appendChild(spinner);
          // 视频开始播放时自动移除spinner
          video.addEventListener('loadeddata', function() {
            if (spinner.parentNode) spinner.parentNode.removeChild(spinner);
          }, { once: true });
        }
        var refreshSrc = '/api/media/proxy?url=' + encodeURIComponent(sUrl) + '&t=' + Date.now();
        var source = video.querySelector('source');
        if (source) source.src = refreshSrc;
        video.load();
      });
      
      lucide.createIcons();
    }

    preview.querySelectorAll('video').forEach(function(video) {
      video.addEventListener('error', function() {
        _showVideoError(video, url);
      });
    });

    // 预览播放器内的视频增加加载指示器，8秒超时防止黑屏一直转
    preview.querySelectorAll('.preview-player video').forEach(function(video) {
      var loading = document.createElement('div');
      loading.className = 'preview-video-loading';
      loading.innerHTML = '<span class="spinner"></span>';
      var player = video.closest('.preview-player');
      if (player) {
        player.appendChild(loading);
      }
      var loadTimeout = setTimeout(function() {
        // 移除 spinner（超时后不再转圈）
        if (loading.parentNode) loading.parentNode.removeChild(loading);
        if (video.readyState < 2) { // HAVE_CURRENT_DATA = 2 — 还没数据，说明文件大/CDN慢
          // 不是错误，显示"仍在加载"提示，之后继续等待数据到达
          var slowEl = document.createElement('div');
          slowEl.className = 'preview-video-slow';
          slowEl.textContent = '视频较大，加载中（可能需要 10~20 秒）…';
          player.appendChild(slowEl);
        }
        lucide.createIcons();
      }, 8000);
      function _removeSlowHint() {
        var s = player.querySelector('.preview-video-slow');
        if (s) s.remove();
      }
      video.addEventListener('loadeddata', function() {
        clearTimeout(loadTimeout);
        if (loading.parentNode) loading.parentNode.removeChild(loading);
        _removeSlowHint();
      });
      video.addEventListener('error', function() {
        clearTimeout(loadTimeout);
        if (loading.parentNode) loading.parentNode.removeChild(loading);
        _removeSlowHint();
      });
    });

    // 绑定下载按钮
    var dlBtn = $('#resource-download-btn');
    if (dlBtn) {
      dlBtn.onclick = function() {
        downloadResource(url, platform);
      };
    }

    // 绑定深度嗅探按钮（L2：L0/L1 拿不到流时的浏览器嗅探）
    var sniffBtn = $('#resource-sniff-btn');
    if (sniffBtn) {
      sniffBtn.onclick = function() {
        runDeepSniff(url, data, sniffBtn);
      };
    }

    // 绑定展开选集按钮（P4：播放页 → 集数列表 → 勾选探测批量下载）
    var epBtn = $('#resource-episodes-btn');
    if (epBtn) {
      epBtn.onclick = function() { expandEpisodes(url, epBtn); };
    }

    // 绑定画廊点击事件（灯箱）
    preview.querySelectorAll('.preview-gallery-item').forEach(function(item) {
      item.addEventListener('click', function() {
        var key = item.dataset.gallery;
        var idx = parseInt(item.dataset.index);
        var images = window[key];
        if (images && images.length > 0) {
          openLightbox(images, idx);
        }
      });
    });

  }

  // ========== 深度嗅探（L2：DrissionPage 浏览器嗅探） ==========
  // L0 直链 / L1 静态解析拿不到流时，真实浏览器过 WAF + 监听网络 +
  // 跨域 iframe 播放器提升，抓 m3u8/mp4 并带 Referer 入下载队列。
  function runDeepSniff(pageUrl, data, btn) {
    var box = $('#sniff-result');
    if (!box) return;
    var iconHtml = '<i data-lucide="search"></i>';
    btn.disabled = true;
    btn.innerHTML = iconHtml + '嗅探中…';
    box.style.display = 'block';
    box.innerHTML = '<div class="sniff-loading"><span class="spinner"></span>' +
      '<span>正在嗅探…（过 WAF 挑战 + 定位播放器，预计 30~60 秒，请稍候）</span></div>';
    lucide.createIcons();

    api('/api/sniff', { method: 'POST', body: { url: pageUrl, timeout: 40 }, timeout: 120 }).then(function(res) {
      btn.disabled = false;
      btn.innerHTML = iconHtml + '重新嗅探';
      lucide.createIcons();
      if (!res.ok || !res.streams || !res.streams.length) {
        box.innerHTML = '<div class="sniff-empty"><i data-lucide="alert-circle"></i>' +
          '<span>嗅探未命中：' + escHtml(res.error || '页面未发现流地址') + '</span></div>';
        lucide.createIcons();
        return;
      }
      var methodLabels = { main: '主页面监听', player: '播放器提升', js: 'JS Hook' };
      // hint 优先级：书签提示 > 解析标题 > 嗅探拿到的页面标题
      // （解析失败场景 data.title 为空，没有 res.title 兜底文件名会退化成 URL 末段）
      var hint = (downloadHints[pageUrl] && downloadHints[pageUrl].title) || data.title || res.title || '';
      var html = '<div class="sniff-meta">命中 ' + res.streams.length + ' 条流 · ' +
        escHtml(methodLabels[res.method] || res.method || '-') + ' · ' + res.elapsed + 's' +
        (res.player_url ? ' · 播放器: ' + escHtml(shortenUrl(res.player_url, 50)) : '') + '</div>';
      res.streams.forEach(function(s, i) {
        html += '<div class="sniff-stream-row">' +
          '<span class="sniff-kind">' + escHtml(s.kind) + '</span>' +
          '<span class="sniff-url" title="' + escAttr(s.url) + '">' + escHtml(shortenUrl(s.url, 90)) + '</span>' +
          '<button class="btn btn-primary sniff-dl" data-i="' + i + '">下载</button>' +
        '</div>';
      });
      box.innerHTML = html;
      box._sniff = { streams: res.streams, hint: hint };
      box.querySelectorAll('.sniff-dl').forEach(function(b) {
        b.onclick = function() {
          var st = box._sniff;
          var s = st.streams[parseInt(this.dataset.i, 10)];
          if (!s) return;
          this.disabled = true;
          this.textContent = '入队…';
          api('/api/video/download', { method: 'POST', body: {
            url: s.url, platform: 'generic',
            referer: s.referer || '',
            filename_hint: st.hint,
          } }).then(function(r) {
            pollResourceDownload(r.task_id, b, '<i data-lucide="download"></i>');
          }).catch(function(err) {
            b.disabled = false;
            b.textContent = '失败';
            lucide.createIcons();
            toast('入队失败：' + err.message, 'error');
          });
        };
      });
      lucide.createIcons();
    }).catch(function(err) {
      btn.disabled = false;
      btn.innerHTML = iconHtml + '深度嗅探';
      box.innerHTML = '<div class="sniff-empty"><i data-lucide="alert-circle"></i>' +
        '<span>嗅探失败：' + escHtml(err.message) + '</span></div>';
      lucide.createIcons();
    });
  }

  function shortenUrl(u, n) {
    if (!u || u.length <= n) return u;
    return u.slice(0, n - 12) + '…' + u.slice(-10);
  }

  // 下载资源
  // btn = 状态落点：内联列表按钮传自己，详情主按钮不传走默认。
  // 之前内联按钮点完全程写在主按钮上 —— 批量列表视图里主按钮压根
  // 不在 DOM，btn.disabled 直接 null 崩，状态还跑到看不见的地方去。
  // 三态与音乐页对齐：下载中（禁用）/ 已下载 / 下载失败，后两者
  // 都留在按钮上当反馈，不再 2 秒后抹回「下载」。
  function downloadResource(url, platform, btn) {
    btn = btn || $('#resource-download-btn');
    if (!btn) return;
    var iconHtml = '<i data-lucide="download"></i>';
    btn.disabled = true;
    btn.innerHTML = iconHtml + '下载中…';
    lucide.createIcons();
    
    // 使用统一下载接口（书签场景带命名提示；探测命中项带 Referer 防盗链）
    var h = downloadHints[url] || {};
    var hint = h.title || '';
    api('/api/video/download', { method: 'POST', body: { url: url, platform: platform, filename_hint: hint, referer: h.referer || '', folder: h.folder || '' } }).then(function(result) {
      pollResourceDownload(result.task_id, btn, iconHtml);
    }).catch(function(err) {
      btn.disabled = false;
      btn.innerHTML = iconHtml + '下载失败';
      lucide.createIcons();
      toast('下载失败：' + err.message, 'error');
    });
  }
  
  // 轮询下载状态
  function pollResourceDownload(taskId, btn, iconHtml) {
    api('/api/video/' + taskId).then(function(info) {
      if (info.status === 'done') {
        // 完成态保持（对齐音乐页 dl-ok）。抹回「下载」等于把
        // 「下过了」的反馈擦掉，用户还得自己去下载目录确认一遍
        btn.disabled = false;
        btn.innerHTML = iconHtml + '已下载';
        lucide.createIcons();
        toast('下载完成' + (info.files ? '：' + info.files.join(', ') : ''), 'success');
        if (state.activeTab === 'downloads' && state.downloadView === 'files') refreshFiles();
      } else if (info.status === 'failed') {
        // 失败态同样保持，按钮留着当反馈、可点重试
        btn.disabled = false;
        btn.innerHTML = iconHtml + '下载失败';
        lucide.createIcons();
        toast('下载失败：' + (info.error || '未知错误'), 'error');
      } else {
        setTimeout(function() { pollResourceDownload(taskId, btn, iconHtml); }, 1500);
      }
    }).catch(function() {
      setTimeout(function() { pollResourceDownload(taskId, btn, iconHtml); }, 1500);
    });
  }
  
  // ========== 批量下载模块 ==========
  // 命名提示：url → {title, folder}（书签模式填充；下载时作为文件名依据）
  var downloadHints = {};
  
  // 开始批量下载（存在书签命名提示时随 items 下发）
  function startBatchDownload(urls) {
    toast('开始批量下载 ' + urls.length + ' 个视频...', 'info');

    var body = { urls: urls };
    if (urls.some(function(u) { return downloadHints[u]; })) {
      // items 必须全量覆盖 urls（后端以 items 为权威工作列表）
      body.items = urls.map(function(u) {
        var h = downloadHints[u] || {};
        return { url: u, title: h.title || '', folder: h.folder || '' };
      });
    }
    api('/api/video/batch-download', { method: 'POST', body: body }).then(function(result) {
      pollBatchDownload(result.task_id);
    }).catch(function(err) {
      toast('批量下载失败：' + err.message, 'error');
    });
  }
  
  // 轮询批量下载状态
  function pollBatchDownload(taskId) {
    api('/api/video/batch/' + taskId).then(function(info) {
      if (info.status === 'done') {
        var msg = '批量下载完成！成功: ' + info.completed + ', 失败: ' + info.failed;
        toast(msg, info.failed > 0 ? 'warning' : 'success');
        if (state.activeTab === 'downloads' && state.downloadView === 'files') refreshFiles();
      } else if (info.status === 'failed') {
        toast('批量下载失败', 'error');
      } else {
        // 更新进度
        var progress = info.completed + '/' + info.total;
        toast('下载进度: ' + progress, 'info');
        setTimeout(function() { pollBatchDownload(taskId); }, 2000);
      }
    }).catch(function() {
      setTimeout(function() { pollBatchDownload(taskId); }, 2000);
    });
  }

  // ========== 书签导入模式（P1） ==========
  var bookmarkTree = [];

  // 选文件（点击输入框区域或上传按钮都触发）
  $('#bookmark-pick').addEventListener('click', function(e) {
    if (e.target.closest('#bookmark-import-btn')) return; // 按钮自行触发，避免双弹
    $('#bookmark-file').click();
  });
  $('#bookmark-import-btn').addEventListener('click', function(e) {
    e.stopPropagation();
    $('#bookmark-file').click();
  });
  $('#bookmark-file').addEventListener('change', function() {
    var f = this.files && this.files[0];
    if (f) importBookmarks(f);
    this.value = '';  // 允许重复选择同一文件
  });

  function setBookmarkStatus(msg, kind) {
    var st = $('#bookmark-status');
    if (!msg) { st.style.display = 'none'; return; }
    st.style.display = 'block';
    st.className = 'status-msg' + (kind ? ' ' + kind : '');
    st.innerHTML = msg;
  }

  function importBookmarks(file) {
    $('#bookmark-file-label').value = file.name;
    setBookmarkStatus('<span class="spinner"></span> 正在读取 ' + escHtml(file.name) + '…');
    $('#bookmark-tree-wrap').style.display = 'none';
    $('#bookmark-results').style.display = 'none';
    // 新导入作废进行中的探测
    if (probeState.running) {
      clearInterval(probeState.timer);
      probeState.running = false;
      setProbeButtons(false);
      if (probeState.id) {
        api('/api/bookmarks/probe/' + probeState.id + '/stop', { method: 'POST' }).catch(function() {});
      }
    }
    showProbeBar(false);

    var reader = new FileReader();
    reader.onerror = function() { setBookmarkStatus('读取文件失败', 'error'); };
    reader.onload = function() {
      api('/api/bookmarks/import', { method: 'POST', body: { html: String(reader.result || '') } })
        .then(function(data) {
          setBookmarkStatus('');
          bookmarkTree = data.tree || [];
          downloadHints = {};  // 新导入覆盖旧提示
          if (!data.links) {
            $('#bookmark-tree-wrap').style.display = 'none';
            toast('书签里没有可用链接', 'warning');
            return;
          }
          renderBookmarkTree();
          $('#bookmark-tree-wrap').style.display = 'block';
          toast('书签导入成功：' + data.links + ' 条链接 / ' + data.folders + ' 个文件夹', 'success');
        })
        .catch(function(err) {
          setBookmarkStatus('导入失败：' + escHtml(err.message), 'error');
        });
    };
    reader.readAsText(file);  // UTF-8（规范默认），BOM 自动剥离
  }

  function renderBookmarkNodes(nodes) {
    var html = '';
    (nodes || []).forEach(function(n) {
      if (n.type === 'folder') {
        html += '<div class="bookmark-folder">' +
          '<label class="bookmark-folder-label"><input type="checkbox" class="bm-folder-cb" checked>' +
          '<i data-lucide="folder" style="width:14px;height:14px"></i><span>' + escHtml(n.name || '未命名文件夹') + '</span></label>' +
          '<div class="bookmark-children">' + renderBookmarkNodes(n.children) + '</div></div>';
      } else if (n.type === 'link' && n.url) {
        var host = '';
        try { host = new URL(n.url).hostname; } catch (_) {}
        html += '<label class="bookmark-link">' +
          '<input type="checkbox" class="bm-link-cb" checked data-url="' + escAttr(n.url) + '" data-title="' + escAttr(n.title || '') + '">' +
          '<span class="bm-title">' + escHtml(n.title || n.url) + '</span>' +
          '<span class="bm-host">' + escHtml(host) + '</span></label>';
      }
    });
    return html;
  }

  function renderBookmarkTree() {
    var el = $('#bookmark-tree');
    el.innerHTML = renderBookmarkNodes(bookmarkTree);
    lucide.createIcons();

    // 文件夹勾选 → 级联全部子链接
    el.querySelectorAll('.bm-folder-cb').forEach(function(cb) {
      cb.addEventListener('change', function() {
        var folder = cb.closest('.bookmark-folder');
        folder.querySelectorAll('.bm-link-cb').forEach(function(l) { l.checked = cb.checked; });
        cb.indeterminate = false;
        updateBookmarkCount();
      });
    });
    // 链接勾选 → 反向刷新祖先文件夹的选中/半选状态
    el.querySelectorAll('.bm-link-cb').forEach(function(cb) {
      cb.addEventListener('change', function() {
        refreshFolderState(cb.closest('.bookmark-folder'));
        updateBookmarkCount();
      });
    });
    updateBookmarkCount();
  }

  function refreshFolderState(folder) {
    while (folder) {
      var links = folder.querySelectorAll('.bm-link-cb');
      var checked = folder.querySelectorAll('.bm-link-cb:checked').length;
      var cb = folder.querySelector(':scope > .bookmark-folder-label .bm-folder-cb');
      if (cb) {
        cb.checked = links.length > 0 && checked === links.length;
        cb.indeterminate = checked > 0 && checked < links.length;
      }
      folder = folder.parentElement && folder.parentElement.closest('.bookmark-folder');
    }
  }

  function updateBookmarkCount() {
    var all = $$('#bookmark-tree .bm-link-cb');
    var sel = $$('#bookmark-tree .bm-link-cb:checked');
    $('#bookmark-total').textContent = all.length;
    $('#bookmark-selected').textContent = sel.length;
  }

  function collectSelectedBookmarks() {
    var seen = {}, items = [];
    $$('#bookmark-tree .bm-link-cb:checked').forEach(function(cb) {
      var url = cb.dataset.url;
      if (!url || seen[url]) return;
      seen[url] = true;
      // 文件夹路径：向上收集层级名（追剧/国漫）
      var path = [], p = cb.closest('.bookmark-folder');
      while (p) {
        var lb = p.querySelector(':scope > .bookmark-folder-label span');
        if (lb) path.unshift(lb.textContent);
        p = p.parentElement && p.parentElement.closest('.bookmark-folder');
      }
      items.push({ url: url, title: cb.dataset.title || '', folder: path.join('/') });
    });
    return items;
  }

  $('#bookmark-select-all').addEventListener('click', function() {
    $$('#bookmark-tree .bm-link-cb').forEach(function(cb) { cb.checked = true; });
    $$('#bookmark-tree .bm-folder-cb').forEach(function(cb) { cb.checked = true; cb.indeterminate = false; });
    updateBookmarkCount();
  });
  $('#bookmark-clear').addEventListener('click', function() {
    $$('#bookmark-tree .bm-link-cb').forEach(function(cb) { cb.checked = false; });
    $$('#bookmark-tree .bm-folder-cb').forEach(function(cb) { cb.checked = false; cb.indeterminate = false; });
    updateBookmarkCount();
  });

  // 解析选中书签（带书签标题作命名提示）
  $('#bookmark-parse-btn').addEventListener('click', function() {
    var items = collectSelectedBookmarks();
    if (items.length === 0) {
      toast('请先勾选要解析的书签', 'error');
      return;
    }

    var btn = this;
    btn.disabled = true;
    setBookmarkStatus('<span class="spinner"></span> 正在解析 ' + items.length + ' 条书签…');

    api('/api/video/batch-parse', {
      method: 'POST',
      body: { urls: items.map(function(i) { return i.url; }), items: items },
      timeout: Math.max(120, items.length * 30)
    }).then(function(data) {
      setBookmarkStatus('');
      var results = data.results || [];
      // 登记命名提示：书签标题用于下载时的文件命名
      items.forEach(function(i) { downloadHints[i.url] = { title: i.title, folder: i.folder }; });
      showInlineBatchResults(results, '#bookmark-results');
    }).catch(function(err) {
      setBookmarkStatus('解析失败：' + escHtml(err.message), 'error');
    }).finally(function() {
      btn.disabled = false;
    });
  });

  // ================= 批量探测（P3：三层降级 L0 直链 → L1 静态 → L2 浏览器嗅探） =================
  // 轮询式进度：POST 启动拿 probe_id → 每秒 GET 全量结果 → 前端整列重渲染。
  // 结果按完成顺序追加（并发完成先后不定），data-idx 用当前数组下标，每轮重绑。

  var probeState = { id: '', timer: 0, running: false, bar: null, results: null, launchBtns: [] };

  function showProbeBar(visible, total, done, hit) {
    var bar = probeState.bar;
    if (!bar) return;
    bar.style.display = visible ? 'flex' : 'none';
    if (!visible) return;
    bar.querySelector('.probe-text').textContent = '已探测 ' + done + '/' + total + ' · 命中 ' + hit;
    bar.querySelector('.probe-fill').style.width = (total ? Math.round(done / total * 100) : 0) + '%';
    var stop = bar.querySelector('.probe-stop-btn');
    if (stop) stop.disabled = false;
  }

  function setProbeButtons(disabled) {
    (probeState.launchBtns || []).forEach(function(b) { if (b) b.disabled = disabled; });
  }

  // 启动探测（书签 / 选集弹窗共用；P4 把落点参数化）。
  // ui = {bar, results} 当前进度与结果的 DOM 落点；launchBtns 探测中禁用。
  function startProbe(items, ui, launchBtns) {
    if (probeState.running) {
      toast('已有探测任务进行中，请先停止', 'warning');
      return Promise.resolve(false);
    }
    probeState.bar = ui.bar;
    probeState.results = ui.results;
    probeState.launchBtns = launchBtns || [];
    setProbeButtons(true);
    ui.results.style.display = 'none';

    return api('/api/bookmarks/probe', {
      method: 'POST',
      body: { items: items, urls: items.map(function(i) { return i.url; }), l2: true }
    }).then(function(data) {
      probeState.id = data.probe_id;
      probeState.running = true;
      showProbeBar(true, data.total, 0, 0);
      probeState.timer = setInterval(pollProbe, 1000);
      return true;
    }).catch(function(err) {
      setProbeButtons(false);
      toast('探测启动失败：' + err.message, 'error');
      return false;
    });
  }

  function probeSelectedBookmarks() {
    var items = collectSelectedBookmarks();
    if (items.length === 0) {
      toast('请先勾选要探测的书签', 'error');
      return;
    }
    startProbe(items,
      { bar: $('#bookmark-probe-bar'), results: $('#bookmark-results') },
      [$('#bookmark-probe-btn'), $('#bookmark-parse-btn')]);
  }

  function pollProbe() {
    if (!probeState.id) return;
    api('/api/bookmarks/probe/' + probeState.id).then(function(st) {
      showProbeBar(st.status === 'running', st.total, st.done, st.hit);
      renderProbeResults(st.results || [], st.status);
      if (st.status !== 'running') {
        clearInterval(probeState.timer);
        probeState.running = false;
        setProbeButtons(false);
        if (st.status === 'done') {
          toast('探测完成：命中 ' + st.hit + '/' + st.total, st.hit > 0 ? 'success' : 'warning');
        } else if (st.status === 'stopped') {
          toast('探测已停止（已完成 ' + st.done + ' 条，命中 ' + st.hit + '）', 'info');
        } else if (st.status === 'failed') {
          toast('探测失败：' + escHtml(st.error || '未知错误'), 'error');
        }
      }
    }).catch(function() { /* 单次轮询失败容忍，下一轮重试 */ });
  }

  function stopProbe() {
    if (!probeState.id) return;
    var btn = probeState.bar && probeState.bar.querySelector('.probe-stop-btn');
    if (btn) btn.disabled = true;
    api('/api/bookmarks/probe/' + probeState.id + '/stop', { method: 'POST' }).catch(function() {});
  }

  // 探测结果列表：层徽章 + 标题 + 耗时 +（命中）下载入口
  function renderProbeResults(results, status) {
    var box = probeState.results;
    if (!box) return;
    box.style.display = 'block';
    box.className = 'resource-preview-container';

    var hits = results.filter(function(r) { return r.status === 'hit' && r.streams && r.streams.length; });
    var missCount = results.length - hits.length;
    var label = status === 'running' ? '探测中…'
      : status === 'stopped' ? '已停止'
      : status === 'failed' ? '探测失败' : '探测完成';

    var html = '<div class="inline-batch-summary">' +
      '<span>' + label + '：<strong class="text-success">' + hits.length + ' 命中</strong>' +
      '，' + missCount + ' 未命中 / 共 ' + results.length + ' 条</span>';
    if (hits.length > 0 && status !== 'running') {
      html += '<button class="btn btn-primary inline-probe-dl-all" style="padding:6px 14px;font-size:12px">' +
        '<i data-lucide="download" style="width:12px;height:12px;margin-right:4px"></i>下载勾选（<span class="probe-checked-n">' + hits.length + '</span>）</button>' +
        '<button class="btn btn-secondary probe-cb-all" style="padding:6px 10px;font-size:11px">全选</button>' +
        '<button class="btn btn-secondary probe-cb-none" style="padding:6px 10px;font-size:11px">清空</button>';
    }
    html += '</div><div class="probe-list">';

    results.forEach(function(r, idx) {
      var layer = r.layer && r.layer !== '-' ? r.layer : '';
      html += '<div class="probe-row' + (r.status === 'hit' ? ' probe-hit' : '') + '">' +
        (layer
          ? '<span class="probe-layer probe-layer-' + layer.toLowerCase() + '">' + layer + '</span>'
          : '<span class="probe-layer probe-layer-miss">—</span>') +
        '<span class="probe-title" title="' + escHtml(r.url) + '">' + escHtml(r.title || shortenUrl(r.url)) + '</span>';
      if (r.status === 'hit') {
        // 结果勾选（§4.3「拿不准展示供勾选，默认全选」）+ 多流选流下拉
        html += '<label class="probe-cb-wrap" title="参与批量下载"><input type="checkbox" class="probe-cb" data-idx="' + idx + '" checked></label>' +
          '<span class="probe-count">' + (r.streams || []).length + ' 流</span>';
        if ((r.streams || []).length > 1) {
          html += '<select class="probe-stream-sel" data-idx="' + idx + '" title="选择下载哪条流">';
          r.streams.forEach(function(su) {
            html += '<option value="' + escHtml(su) + '">' + escHtml(streamShortLabel(su)) + '</option>';
          });
          html += '</select>';
        }
        html += '<span class="probe-meta">' + escHtml(String(r.elapsed != null ? r.elapsed + 's' : '')) + '</span>' +
          '<button class="btn btn-secondary probe-dl-btn" data-idx="' + idx + '" style="padding:3px 10px;font-size:11px">下载</button>';
      } else {
        html += '<span class="probe-miss-txt">' + escHtml(r.error || '无视频') + '</span>' +
          '<span class="probe-meta">' + escHtml(String(r.elapsed != null ? r.elapsed + 's' : '')) + '</span>';
      }
      html += '</div>';
    });
    html += '</div>';
    box.innerHTML = html;
    if (typeof lucide !== 'undefined') lucide.createIcons();

    function updateCheckedN() {
      var n = box.querySelectorAll('.probe-cb:checked').length;
      var el = box.querySelector('.probe-checked-n');
      if (el) el.textContent = n;
    }
    box.querySelectorAll('.probe-cb').forEach(function(cb) {
      cb.addEventListener('change', updateCheckedN);
    });
    var cbAll = box.querySelector('.probe-cb-all');
    if (cbAll) cbAll.addEventListener('click', function() {
      box.querySelectorAll('.probe-cb').forEach(function(cb) { cb.checked = true; });
      updateCheckedN();
    });
    var cbNone = box.querySelector('.probe-cb-none');
    if (cbNone) cbNone.addEventListener('click', function() {
      box.querySelectorAll('.probe-cb').forEach(function(cb) { cb.checked = false; });
      updateCheckedN();
    });

    var dlAll = box.querySelector('.inline-probe-dl-all');
    if (dlAll) dlAll.addEventListener('click', function() { downloadProbeHits(results); });
    box.querySelectorAll('.probe-dl-btn').forEach(function(b) {
      b.addEventListener('click', function() {
        var r = results[+b.dataset.idx];
        if (!r || !r.streams || !r.streams.length) return;
        var sel = box.querySelector('.probe-stream-sel[data-idx="' + b.dataset.idx + '"]');
        var su = (sel && sel.value) || r.streams[0];
        downloadHints[su] = { title: r.title || '', folder: r.folder || '', referer: r.referer || '' };
        downloadResource(su, 'generic', b);
      });
    });
  }

  // 选流下拉的显示标签：类型 + 路径尾两段（完整 URL 悬浮 title）
  function streamShortLabel(u) {
    var kind = /\.m3u8(\?|$)/i.test(u) ? 'HLS' : /\.mpd(\?|$)/i.test(u) ? 'DASH' : 'MP4';
    var p = String(u).split('#')[0].split('?')[0];
    var seg = p.split('/').slice(-2).join('/');
    return kind + ' · ' + seg;
  }

  // 一键入队勾选命中项（勾选行 + 行内选流；title/folder/referer 随 items 下发）
  function downloadProbeHits(results) {
    var box = probeState.results;
    var work = [];
    results.forEach(function(r, idx) {
      if (!r || r.status !== 'hit' || !r.streams || !r.streams.length) return;
      var cb = box && box.querySelector('.probe-cb[data-idx="' + idx + '"]');
      if (cb && !cb.checked) return;  // 未勾选 → 不入队
      var sel = box && box.querySelector('.probe-stream-sel[data-idx="' + idx + '"]');
      var su = (sel && sel.value) || r.streams[0];
      work.push({ url: su, title: r.title || '', folder: r.folder || '', referer: r.referer || '' });
    });
    if (!work.length) { toast('没有勾选的命中项', 'warning'); return; }
    toast('开始批量下载 ' + work.length + ' 个命中资源...', 'info');
    api('/api/video/batch-download', {
      method: 'POST',
      body: { urls: work.map(function(w) { return w.url; }), items: work }
    }).then(function(result) {
      pollBatchDownload(result.task_id);
    }).catch(function(err) {
      toast('批量下载失败：' + err.message, 'error');
    });
  }

  $('#bookmark-probe-btn').addEventListener('click', probeSelectedBookmarks);
  // 停止按钮按 class 绑定（书签 bar 与选集弹窗 bar 各一个）
  $$('.probe-stop-btn').forEach(function(b) { b.addEventListener('click', stopProbe); });

  // ================= 选集展开（P4：播放页 → 集数列表 → 勾选探测批量下载） =================
  // 三级回退在后端（episodes.py）；本模块只做弹窗、勾选与探测复用（startProbe）。

  var epState = { items: [], series: '' };

  function expandEpisodes(url, btn) {
    if (btn.disabled) return;
    var iconHtml = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span>展开中…';
    api('/api/video/episodes', { method: 'POST', body: { url: url, timeout: 60 }, timeout: 150 })
      .then(function(res) {
        if (!res.count || res.count < 3) {
          toast(res.error || '未识别到选集（已回退为单集下载）', 'warning');
          return;
        }
        openEpisodeModal(res);
      })
      .catch(function(err) {
        toast('展开选集失败：' + err.message, 'error');
      })
      .finally(function() {
        btn.disabled = false;
        btn.innerHTML = iconHtml;
        if (typeof lucide !== 'undefined') lucide.createIcons();
      });
  }

  // 页面 title 常带「第05集在线播放」等当前集后缀 → 去掉，作剧名前缀
  function cleanSeriesName(title) {
    return String(title || '')
      .replace(/\s*第\s*\d+\s*[集话期].*$/, '')
      .replace(/\s+$/, '')
      .trim();
  }

  function openEpisodeModal(res) {
    var g = (res.groups && res.groups[0]) || { items: [] };
    epState.series = cleanSeriesName(res.title);
    epState.items = g.items || [];

    $('#episode-title').textContent = epState.series || '选集展开';
    var methodLabel = { ytdlp: 'yt-dlp 原生', static: '静态提取', browser: '浏览器提取' }[res.method] || res.method;
    $('#episode-method').textContent =
      g.count + ' 集 · ' + methodLabel +
      ((res.groups || []).length > 1 ? ' · 另 ' + (res.groups.length - 1) + ' 组链接' : '') +
      (res.elapsed != null ? ' · ' + res.elapsed + 's' : '');

    renderEpisodeList();
    $('#episode-probe-bar').style.display = 'none';
    $('#episode-results').style.display = 'none';
    $('#episode-overlay').style.display = 'flex';
    if (typeof lucide !== 'undefined') lucide.createIcons();
  }

  function renderEpisodeList() {
    var box = $('#episode-list');
    box.innerHTML = epState.items.map(function(it, i) {
      return '<label class="episode-item" title="' + escAttr(it.url) + '">' +
        '<input type="checkbox" class="episode-cb" data-idx="' + i + '">' +
        '<span class="episode-label">' + escHtml(it.label || ('第' + (i + 1) + '集')) + '</span>' +
        '</label>';
    }).join('');
    $('#episode-total').textContent = epState.items.length;
    $('#episode-selected').textContent = '0';
    box.querySelectorAll('.episode-cb').forEach(function(cb) {
      cb.addEventListener('change', updateEpisodeCount);
    });
  }

  function updateEpisodeCount() {
    var n = document.querySelectorAll('#episode-list .episode-cb:checked').length;
    $('#episode-selected').textContent = n;
  }

  function probeSelectedEpisodes() {
    var checked = $$('#episode-list .episode-cb:checked');
    if (!checked.length) {
      toast('请先勾选要下载的集数', 'error');
      return;
    }
    var series = epState.series;
    var items = checked.map(function(cb) {
      var it = epState.items[+cb.dataset.idx];
      // title = 剧名 + 集数 → P1 build_file_stem 解析命名；folder = 剧名目录
      return {
        url: it.url,
        title: (series ? series + ' ' : '') + it.label,
        folder: series || ''
      };
    });
    startProbe(items,
      { bar: $('#episode-probe-bar'), results: $('#episode-results') },
      [$('#episode-probe-btn'), $('#episode-all-btn'), $('#episode-none-btn')]);
  }

  function closeEpisodeModal() {
    // 关闭弹窗时若探测正在进行且落点是本弹窗 → 停止（书签探测不受影响）
    if (probeState.running && probeState.bar === $('#episode-probe-bar')) {
      stopProbe();
    }
    $('#episode-overlay').style.display = 'none';
  }

  $('#episode-all-btn').addEventListener('click', function() {
    $$('#episode-list .episode-cb').forEach(function(cb) { cb.checked = true; });
    updateEpisodeCount();
  });
  $('#episode-none-btn').addEventListener('click', function() {
    $$('#episode-list .episode-cb').forEach(function(cb) { cb.checked = false; });
    updateEpisodeCount();
  });
  $('#episode-probe-btn').addEventListener('click', probeSelectedEpisodes);
  $('#episode-close-btn').addEventListener('click', closeEpisodeModal);
  $('#episode-overlay').addEventListener('click', function(e) {
    if (e.target === this) closeEpisodeModal();
  });