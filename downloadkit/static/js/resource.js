// ========== 资源解析模块（智能识别） ==========
  // 检测平台
  function detectPlatform(url) {
    if (url.includes('douyin.com') || url.includes('tiktok.com')) return 'douyin';
    if (url.includes('bilibili.com') || url.includes('b23.tv')) return 'bilibili';
    if (url.includes('youtube.com') || url.includes('youtu.be')) return 'youtube';
    if (url.includes('xiaohongshu.com') || url.includes('xhslink.com')) return 'xiaohongshu';
    return null;
  }
  
  // 统一输入处理
  $('#resource-input').addEventListener('keydown', function(e) { 
    if (e.key === 'Enter') handleResourceInput(); 
  });
  $('#resource-btn').addEventListener('click', handleResourceInput);
  
  // 资源解析框清空按钮
  var resourceInput = $('#resource-input');
  var resourceClear = $('#resource-clear');
  resourceInput.addEventListener('input', function() {
    resourceClear.classList.toggle('show', resourceInput.value.length > 0);
  });
  resourceClear.addEventListener('click', function() {
    resourceInput.value = '';
    resourceClear.classList.remove('show');
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
      toast('暂不支持该平台', 'error');
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
    st.innerHTML = '<span class="spinner"></span> 正在解析...';
    st.className = 'status-msg';
    $('#resource-preview').style.display = 'none';
    
    api('/api/video/parse', { method: 'POST', body: { url: url } }).then(function(data) {
      st.style.display = 'none';
      showResourcePreview(data, platform, url);
    }).catch(function(err) {
      st.innerHTML = '解析失败：' + err.message;
      st.className = 'status-msg error';
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
    st.innerHTML = '<span class="spinner"></span> 正在解析 ' + urls.length + ' 个链接...';
    st.className = 'status-msg';
    $('#resource-preview').style.display = 'none';

    api('/api/video/batch-parse', { method: 'POST', body: { urls: urls } }).then(function(data) {
      st.style.display = 'none';
      showInlineBatchResults(data.results || []);
    }).catch(function(err) {
      st.innerHTML = '解析失败：' + err.message;
      st.className = 'status-msg error';
    }).finally(function() {
      btn.disabled = false;
    });
  }

  // 显示内联批量解析结果（在单输入框预览区）
  function showInlineBatchResults(results) {
    var preview = $('#resource-preview');
    preview.style.display = 'block';
    preview.className = 'resource-preview-container';

    var platformColors = {
      'douyin': { bg: '#FF6B6B20', color: '#FF6B6B', label: '抖音' },
      'bilibili': { bg: '#00A1D620', color: '#00A1D6', label: 'B站' },
      'youtube': { bg: '#FF000020', color: '#FF0000', label: 'YouTube' },
      'xiaohongshu': { bg: '#FF244220', color: '#FF2442', label: '小红书' }
    };

    var successCount = results.filter(function(r) { return r.status === 'success'; }).length;
    var failCount = results.length - successCount;

    var html = '';

    // 汇总栏
    html += '<div class="inline-batch-summary">' +
      '<span>解析完成：<strong class="text-success">' + successCount + ' 成功</strong>' +
      (failCount > 0 ? '，<strong class="text-error">' + failCount + ' 失败</strong>' : '') + '</span>';
    if (successCount > 0) {
      html += '<button class="btn btn-primary" id="inline-batch-dl-all" style="padding:6px 14px;font-size:12px"><i data-lucide="download" style="width:12px;height:12px;margin-right:4px"></i>下载全部</button>';
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
      html += '<div class="batch-item-meta">' + escHtml(item.author || '未知作者') + ' · <span class="platform-tag" style="background:' + p.bg + ';color:' + p.color + ';margin-top:0">' + p.label + '</span></div>';
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

    // 绑定全部下载按钮
    var dlAll = $('#inline-batch-dl-all');
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
      'xiaohongshu': { bg: '#FF244220', color: '#FF2442', label: '小红书' }
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
      '</div>';

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
      html += '<div class="preview-unavailable">' +
        '<i data-lucide="eye-off"></i>' +
        '<span class="preview-unavailable-text">暂无可用预览</span>' +
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
          slowEl.textContent = '视频较大，正在下载中（可能需要10-20秒）...';
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
    
    // 使用统一下载接口
    api('/api/video/download', { method: 'POST', body: { url: url, platform: platform } }).then(function(result) {
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
  // 批量解析结果
  var batchResults = [];
  var batchSelected = {};
  
  // 模式切换
  $$('.mode-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
      var mode = btn.dataset.mode;
      $$('.mode-btn').forEach(function(b) { b.classList.toggle('active', b === btn); });
      $('#single-mode').style.display = mode === 'single' ? 'block' : 'none';
      $('#batch-mode').style.display = mode === 'batch' ? 'block' : 'none';
    });
  });
  
  // 批量解析
  $('#batch-parse-btn').addEventListener('click', function() {
    var input = $('#batch-input').value.trim();
    if (!input) {
      toast('请输入链接', 'error');
      return;
    }
    
    // 从多行文本中提取所有URL
    var urls = extractAllUrls(input);
    
    if (urls.length === 0) {
      toast('未找到有效链接', 'error');
      return;
    }
    
    var btn = $('#batch-parse-btn');
    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="search"></i>解析中...';
    lucide.createIcons();
    
    var st = $('#batch-status');
    st.style.display = 'block';
    st.innerHTML = '<span class="spinner"></span> 正在解析 ' + urls.length + ' 个链接...';
    st.className = 'status-msg';
    $('#batch-results').style.display = 'none';
    
    api('/api/video/batch-parse', { method: 'POST', body: { urls: urls } }).then(function(data) {
      batchResults = data.results || [];
      st.style.display = 'none';
      showBatchResults();
    }).catch(function(err) {
      st.innerHTML = '解析失败：' + err.message;
      st.className = 'status-msg error';
    }).finally(function() { 
      btn.disabled = false; 
      btn.innerHTML = '<i data-lucide="search"></i>解析全部';
      lucide.createIcons();
    });
  });
  
  // 清空批量输入
  $('#batch-clear-btn').addEventListener('click', function() {
    $('#batch-input').value = '';
    $('#batch-results').style.display = 'none';
    $('#batch-status').style.display = 'none';
    batchResults = [];
    batchSelected = {};
  });
  
  // 显示批量解析结果
  function showBatchResults() {
    var container = $('#batch-results');
    container.style.display = 'block';
    
    var platformColors = {
      'douyin': { bg: '#FF6B6B20', color: '#FF6B6B', label: '抖音' },
      'bilibili': { bg: '#00A1D620', color: '#00A1D6', label: 'B站' },
      'youtube': { bg: '#FF000020', color: '#FF0000', label: 'YouTube' },
      'xiaohongshu': { bg: '#FF244220', color: '#FF2442', label: '小红书' }
    };
    
    var successCount = batchResults.filter(function(r) { return r.status === 'success'; }).length;
    
    var html = '';
    
    // 结果列表
    html += '<div class="batch-results-list">';
    batchResults.forEach(function(item, index) {
      var p = platformColors[item.platform] || { bg: '#86868B20', color: '#86868B', label: '未知' };
      
      html += '<div class="batch-item" data-index="' + index + '">';
      
      if (item.status === 'success') {
        html += '<div class="batch-item-checkbox"><input type="checkbox" class="batch-select" data-index="' + index + '" checked></div>';
      }
      
      var itemIcon = getContentTypeIcon(item.content_type);
      html += '<div class="batch-item-cover" style="background:linear-gradient(135deg,' + p.bg + ',' + p.bg.replace('20', '10') + ')"><i data-lucide="' + itemIcon + '"></i></div>';
      html += '<div class="batch-item-info">';
      html += '<div class="batch-item-title">' + escHtml(item.title || '未知标题') + '</div>';
      html += '<div class="batch-item-meta">' + escHtml(item.author || '未知作者') + '</div>';
      html += '</div>';
      
      if (item.status === 'success') {
        html += '<span class="batch-item-status success">可下载</span>';
      } else {
        html += '<span class="batch-item-status failed" title="' + escAttr(item.error || '') + '">解析失败</span>';
      }
      
      html += '</div>';
    });
    html += '</div>';
    
    // 操作栏
    if (successCount > 0) {
      html += '<div class="batch-toolbar">';
      html += '<div class="batch-select-all">';
      html += '<input type="checkbox" id="batch-select-all" checked>';
      html += '<label for="batch-select-all">全选 (' + successCount + ')</label>';
      html += '</div>';
      html += '<div class="batch-download-actions">';
      html += '<button class="btn btn-primary" id="batch-download-selected"><i data-lucide="download"></i>下载选中</button>';
      html += '<button class="btn btn-secondary" id="batch-download-all"><i data-lucide="download"></i>下载全部</button>';
      html += '</div>';
      html += '</div>';
    }
    
    container.innerHTML = html;
    lucide.createIcons();
    
    // 初始化选中状态
    batchSelected = {};
    batchResults.forEach(function(item, index) {
      if (item.status === 'success') {
        batchSelected[index] = true;
      }
    });
    
    // 绑定事件
    bindBatchEvents();
  }
  
  // 绑定批量操作事件
  function bindBatchEvents() {
    // 单个选择
    $$('.batch-select').forEach(function(checkbox) {
      checkbox.addEventListener('change', function() {
        var index = parseInt(checkbox.dataset.index);
        if (checkbox.checked) {
          batchSelected[index] = true;
        } else {
          delete batchSelected[index];
        }
        updateBatchSelectAll();
      });
    });
    
    // 全选
    var selectAll = $('#batch-select-all');
    if (selectAll) {
      selectAll.addEventListener('change', function() {
        var checked = this.checked;
        $$('.batch-select').forEach(function(checkbox) {
          checkbox.checked = checked;
          var index = parseInt(checkbox.dataset.index);
          if (checked) {
            batchSelected[index] = true;
          } else {
            delete batchSelected[index];
          }
        });
      });
    }
    
    // 下载选中
    var downloadSelected = $('#batch-download-selected');
    if (downloadSelected) {
      downloadSelected.addEventListener('click', function() {
        var urls = Object.keys(batchSelected).map(function(index) {
          return batchResults[parseInt(index)].url;
        });
        if (urls.length > 0) {
          startBatchDownload(urls);
        }
      });
    }
    
    // 下载全部
    var downloadAll = $('#batch-download-all');
    if (downloadAll) {
      downloadAll.addEventListener('click', function() {
        var urls = batchResults
          .filter(function(item) { return item.status === 'success'; })
          .map(function(item) { return item.url; });
        if (urls.length > 0) {
          startBatchDownload(urls);
        }
      });
    }
  }
  
  // 更新全选状态
  function updateBatchSelectAll() {
    var selectAll = $('#batch-select-all');
    if (!selectAll) return;
    
    var successCount = batchResults.filter(function(r) { return r.status === 'success'; }).length;
    var selectedCount = Object.keys(batchSelected).length;
    
    selectAll.checked = selectedCount === successCount;
    var label = selectAll.nextElementSibling;
    if (label) {
      label.textContent = '全选 (' + selectedCount + '/' + successCount + ')';
    }
  }
  
  // 开始批量下载
  function startBatchDownload(urls) {
    toast('开始批量下载 ' + urls.length + ' 个视频...', 'info');
    
    api('/api/video/batch-download', { method: 'POST', body: { urls: urls } }).then(function(result) {
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