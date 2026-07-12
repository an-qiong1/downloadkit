// ========== 影视功能 ==========
  var movieState = {
    sources: [],
    currentSource: '',
    currentVodId: '',
    detail: null,
    currentEpisodeUrl: '',
    currentEpisodeTitle: ''
  };
  
  // 初始化影视源
  function loadMovieSources() {
    api('/api/movie/sources').then(function(res) {
      movieState.sources = res.sources || res.data || res || [];
      var bar = $('#movie-source-bar');
      bar.innerHTML = '';
      movieState.sources.forEach(function(src, i) {
        var name = typeof src === 'string' ? src : (src.name || src.source);
        var btn = document.createElement('button');
        btn.className = 'source-btn' + (i === 0 ? ' active' : '');
        btn.textContent = name;
        btn.dataset.source = name;
        btn.addEventListener('click', function() {
          $$('.source-btn').forEach(function(b) { b.classList.remove('active'); });
          btn.classList.add('active');
          movieState.currentSource = name;
        });
        bar.appendChild(btn);
      });
      if (movieState.sources.length > 0) {
        var first = movieState.sources[0];
        movieState.currentSource = typeof first === 'string' ? first : (first.name || first.source);
      }
    }).catch(function(err) {
      console.error('获取影视源失败:', err);
    });
  }
  
  // 搜索影视
  function searchMovie(keyword) {
    if (!keyword) return;
    var statusEl = $('#movie-status');
    var resultsEl = $('#movie-results');
    var detailEl = $('#movie-detail');
    
    detailEl.style.display = 'none';
    resultsEl.innerHTML = '';
    statusEl.style.display = 'block';
    statusEl.textContent = '搜索中...';
    
    var url = '/api/movie/search?keyword=' + encodeURIComponent(keyword);
    if (movieState.currentSource) {
      url += '&source=' + encodeURIComponent(movieState.currentSource);
    }
    
    api(url).then(function(res) {
      var list = res.results || res.data || res || [];
      statusEl.style.display = 'none';
      if (list.length === 0) {
        statusEl.style.display = 'block';
        statusEl.textContent = '未找到相关结果';
        return;
      }
      list.forEach(function(item) {
        var card = document.createElement('div');
        card.className = 'movie-card';
        card.innerHTML = '<img class="movie-card-poster" src="' + (item.vod_pic || '') + '" alt="" onerror="this.src=\'\'">' +
          '<div class="movie-card-info">' +
          '<div class="movie-card-title">' + (item.vod_name || '') + '</div>' +
          '<div class="movie-card-meta">' + (item.vod_remarks || item.type_name || '') + '</div>' +
          (item.vod_year ? '<span class="movie-card-tag">' + item.vod_year + '</span>' : '') +
          '</div>';
        card.addEventListener('click', function() {
          showMovieDetail(item.vod_id || item.id, item.vod_source || movieState.currentSource);
        });
        resultsEl.appendChild(card);
      });
    }).catch(function(err) {
      statusEl.style.display = 'block';
      statusEl.textContent = '搜索失败：' + err.message;
    });
  }
  
  // 显示影视详情
  function showMovieDetail(vodId, source) {
    movieState.currentVodId = vodId;
    var statusEl = $('#movie-status');
    var resultsEl = $('#movie-results');
    var detailEl = $('#movie-detail');
    
    resultsEl.style.display = 'none';
    statusEl.style.display = 'block';
    statusEl.textContent = '加载详情中...';
    detailEl.style.display = 'none';
    
    var url = '/api/movie/' + vodId;
    if (source) {
      url += '?source=' + encodeURIComponent(source);
    }
    
    api(url).then(function(res) {
      var detail = res;
      movieState.detail = detail;
      statusEl.style.display = 'none';
      detailEl.style.display = 'block';
      
      $('#movie-poster').src = detail.vod_pic || '';
      $('#movie-title-detail').textContent = detail.vod_name || '';
      $('#movie-meta-text').innerHTML = [
        detail.vod_year ? '年份：' + detail.vod_year : '',
        detail.vod_area ? '地区：' + detail.vod_area : '',
        detail.type_name ? '类型：' + detail.type_name : '',
        detail.vod_director ? '导演：' + detail.vod_director : '',
        detail.vod_actor ? '主演：' + detail.vod_actor : ''
      ].filter(Boolean).join('<br>');
      $('#movie-desc').textContent = detail.vod_content || detail.vod_blurb || '';
      
      // 渲染剧集列表
      var episodeListEl = $('#episode-list');
      episodeListEl.innerHTML = '';
      
      // 使用API返回的预解析剧集列表
      var episodes = detail.episodes || [];
      
      if (episodes.length > 0) {
        // 构建完整的HTML
        var allHtml = '';
        episodes.forEach(function(group) {
          allHtml += '<div class="episode-title">' + (group.name || '播放源') + '</div><div class="episode-grid">';
          group.episodes.forEach(function(ep, idx) {
            allHtml += '<button class="episode-btn" data-url="' + ep.url + '" data-title="' + ep.name + '">' + ep.name + '</button>';
          });
          allHtml += '</div>';
        });
        episodeListEl.innerHTML = allHtml;
        
        // 绑定剧集点击事件
        $$('.episode-btn', episodeListEl).forEach(function(btn) {
          btn.addEventListener('click', function() {
            $$('.episode-btn').forEach(function(b) { b.classList.remove('active'); });
            btn.classList.add('active');
            var url = btn.dataset.url;
            var title = btn.dataset.title;
            movieState.currentEpisodeUrl = url;
            movieState.currentEpisodeTitle = title;
            initPlayer(url, detail.vod_name + ' - ' + title);
          });
        });
        
        // 绑定下载按钮
        var downloadBtn = $('#movie-download-btn');
        downloadBtn.onclick = function() {
          if (!movieState.currentEpisodeUrl) {
            toast('请先选择一个剧集', 'info');
            return;
          }
          downloadMovie(movieState.currentEpisodeUrl, detail.vod_name + ' - ' + (movieState.currentEpisodeTitle || '未知剧集'));
        };
      } else {
        episodeListEl.innerHTML = '<div style="color:var(--text-secondary);padding:10px 0;">暂无可用播放源</div>';
      }
    }).catch(function(err) {
      statusEl.style.display = 'block';
      statusEl.textContent = '加载详情失败：' + err.message;
    });
  }
  
  // 解析剧集列表
  function parseEpisodes(playFrom, playUrl) {
    var result = [];
    var fromList = playFrom.split('$$$');
    var urlList = playUrl.split('$$$');
    
    for (var i = 0; i < fromList.length; i++) {
      var name = fromList[i] || '播放源' + (i + 1);
      var urls = (urlList[i] || '').split('#');
      var episodes = [];
      urls.forEach(function(u) {
        var parts = u.split('$');
        if (parts.length >= 2) {
          episodes.push({ name: parts[0], url: parts[1] });
        } else if (u) {
          episodes.push({ name: '第' + (episodes.length + 1) + '集', url: u });
        }
      });
      if (episodes.length > 0) {
        result.push({ name: name, episodes: episodes });
      }
    }
    return result;
  }
  
  // 初始化DPlayer播放器
  function initPlayer(url, title) {
    var container = $('#player-container');
    container.style.display = 'block';
    container.scrollIntoView({ behavior: 'smooth' });
    
    var isM3u8 = url.indexOf('.m3u8') > -1 || url.indexOf('/m3u8') > -1;
    var isMp4 = url.indexOf('.mp4') > -1;
    
    // 销毁旧播放器
    if (window.dplayer) {
      try {
        window.dplayer.destroy();
      } catch(e) {}
      window.dplayer = null;
    }
    
    // 清空容器
    $('#dplayer').innerHTML = '';
    
    // 创建video元素
    var videoEl = document.createElement('video');
    videoEl.controls = true;
    videoEl.autoplay = true;
    videoEl.style.width = '100%';
    videoEl.style.maxHeight = '500px';
    videoEl.style.background = '#000';
    $('#dplayer').appendChild(videoEl);
    
    // 错误提示容器
    var errorDiv = document.createElement('div');
    errorDiv.id = 'player-error';
    errorDiv.style.cssText = 'display:none;padding:20px;text-align:center;color:var(--text-secondary);';
    errorDiv.innerHTML = '<p>视频加载失败</p><p style="font-size:12px;margin-top:8px;">请尝试其他剧集或播放源</p>';
    $('#dplayer').appendChild(errorDiv);
    
    // 视频加载失败处理
    videoEl.onerror = function() {
      console.error('Video load error');
      videoEl.style.display = 'none';
      errorDiv.style.display = 'block';
    };
    
    // 设置视频源
    if (isM3u8 && typeof Hls !== 'undefined' && Hls.isSupported()) {
      var hls = new Hls({
        maxBufferLength: 30,
        maxMaxBufferLength: 60,
      });
      hls.loadSource(url);
      hls.attachMedia(videoEl);
      hls.on(Hls.Events.ERROR, function(event, data) {
        console.error('HLS error:', data.type, data.details);
        if (data.fatal) {
          switch (data.type) {
            case Hls.ErrorTypes.NETWORK_ERROR:
              console.error('Network error, trying to recover...');
              hls.startLoad();
              break;
            case Hls.ErrorTypes.MEDIA_ERROR:
              console.error('Media error, trying to recover...');
              hls.recoverMediaError();
              break;
            default:
              console.error('Unrecoverable error');
              videoEl.style.display = 'none';
              errorDiv.style.display = 'block';
              break;
          }
        }
      });
      hls.on(Hls.Events.MANIFEST_PARSED, function() {
        videoEl.play().catch(function(e) {
          console.log('Autoplay prevented:', e);
        });
      });
    } else if (videoEl.canPlayType('application/vnd.apple.mpegurl')) {
      // Safari原生支持HLS
      videoEl.src = url;
      videoEl.addEventListener('loadedmetadata', function() {
        videoEl.play().catch(function(e) {
          console.log('Autoplay prevented:', e);
        });
      });
    } else {
      // 直接设置src（mp4等）
      videoEl.src = url;
      videoEl.play().catch(function(e) {
        console.log('Autoplay prevented:', e);
      });
    }
  }
  
  // 下载影视视频
  function downloadMovie(url, title) {
    var btn = $('#movie-download-btn');
    var iconHtml = '<i data-lucide="download" style="width:14px;height:14px;margin-right:6px"></i>';
    btn.disabled = true;
    btn.innerHTML = iconHtml + '下载中...';
    lucide.createIcons();
    
    api('/api/movie/download', { 
      method: 'POST', 
      body: { 
        url: url, 
        title: title,
        source: movieState.currentSource || ''
      } 
    }).then(function(result) {
      pollMovieDownload(result.task_id, btn, iconHtml);
    }).catch(function(err) {
      btn.innerHTML = iconHtml + '下载失败';
      lucide.createIcons();
      toast('下载失败：' + err.message, 'error');
      setTimeout(function() { 
        btn.disabled = false; 
        btn.innerHTML = iconHtml + '下载当前剧集';
        lucide.createIcons();
      }, 2000);
    });
  }
  
  // 轮询影视下载状态
  function pollMovieDownload(taskId, btn, iconHtml) {
    api('/api/video/' + taskId).then(function(info) {
      if (info.status === 'done') {
        btn.innerHTML = iconHtml + '下载完成';
        lucide.createIcons();
        toast('下载完成：' + (info.filename || ''), 'success');
        if (state.activeTab === 'files') refreshFiles();
      } else if (info.status === 'failed') {
        btn.innerHTML = iconHtml + '下载失败';
        lucide.createIcons();
        toast('下载失败：' + (info.error || '未知错误'), 'error');
      } else {
        setTimeout(function() { pollMovieDownload(taskId, btn, iconHtml); }, 1500);
        return;
      }
      setTimeout(function() { 
        btn.disabled = false; 
        btn.innerHTML = iconHtml + '下载当前剧集';
        lucide.createIcons();
      }, 2000);
    }).catch(function() {
      setTimeout(function() { pollMovieDownload(taskId, btn, iconHtml); }, 1500);
    });
  }
  
  // 返回按钮
  $('#movie-back').addEventListener('click', function() {
    $('#movie-detail').style.display = 'none';
    $('#movie-results').style.display = '';
    $('#movie-status').style.display = 'none';
    if (window.dplayer) {
      window.dplayer.destroy();
      window.dplayer = null;
    }
    $('#player-container').style.display = 'none';
  });
  
  // 搜索按钮和回车
  $('#movie-btn').addEventListener('click', function() {
    searchMovie($('#movie-input').value.trim());
  });
  $('#movie-input').addEventListener('keydown', function(e) {
    if (e.key === 'Enter') {
      searchMovie($('#movie-input').value.trim());
    }
  });
  
  // 清空按钮（显示/隐藏 + 清空）
  var movieInput = $('#movie-input');
  var movieClear = $('#movie-clear');
  movieInput.addEventListener('input', function() {
    movieClear.classList.toggle('show', movieInput.value.length > 0);
  });
  movieClear.addEventListener('click', function() {
    movieInput.value = '';
    movieClear.classList.remove('show');
    movieInput.focus();
    // 清空搜索结果
    $('#movie-results').innerHTML = '';
    $('#movie-detail').style.display = 'none';
    $('#movie-status').style.display = 'none';
  });
  
  // 加载影视源
  loadMovieSources();