// ========== 音乐模块（智能识别） ==========
  // 检测是否为URL
  function isUrl(text) {
    return /^https?:\/\//.test(text) || /^www\./.test(text);
  }
  
  // 从文本中提取URL（支持抖音口令等混合文本）
  function extractUrl(text) {
    // 先检查是否是纯URL
    if (isUrl(text)) return text;
    
    // 尝试从文本中提取URL
    var urlPatterns = [
      /https?:\/\/[^\s]+/,  // http/https链接
      /www\.[^\s]+/,         // www链接
      /v\.douyin\.com\/[^\s]+/,  // 抖音短链接
      /douyin\.com\/[^\s]+/,     // 抖音链接
    ];
    
    for (var i = 0; i < urlPatterns.length; i++) {
      var match = text.match(urlPatterns[i]);
      if (match) {
        // 清理URL末尾的标点符号
        return match[0].replace(/[，。！？、；：""''）】》\s]+$/, '');
      }
    }
    
    return null;
  }
  
  // 从多行文本中提取所有URL
  function extractAllUrls(text) {
    var urls = [];
    var lines = text.split('\n');
    
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i].trim();
      if (!line) continue;
      
      // 尝试从每行中提取URL
      var url = extractUrl(line);
      if (url) {
        urls.push(url);
      }
    }
    
    return urls;
  }
  
  // 检测是否为歌单链接
  function isPlaylistUrl(text) {
    return text.includes('music.163.com/playlist') || 
           text.includes('y.qq.com/n/ryqq/playlist') ||
           text.includes('music.163.com/#/playlist') ||
           text.includes('c6.y.qq.com/base/fcgi-bin');
  }
  
  // 检测是否为单曲链接
  function isSingleSongUrl(text) {
    // 网易云单曲链接
    if (/music\.163\.com\/(song|#\/song|song\/media\/outer\/url)/.test(text)) return true;
    // QQ音乐单曲链接
    if (/y\.qq\.com\/n\/ryqq\/songDetail/.test(text)) return true;
    // 含有 /song?id= 格式的链接
    if (/\/song\?id=\d+/.test(text)) return true;
    return false;
  }
  
  // 统一输入处理
  $('#music-input').addEventListener('keydown', function(e) { 
    if (e.key === 'Enter') handleMusicInput(); 
  });
  $('#music-btn').addEventListener('click', handleMusicInput);
  
  // 音乐搜索框清空按钮
  var musicInput = $('#music-input');
  var musicClear = $('#music-clear');
  musicInput.addEventListener('input', function() {
    musicClear.classList.toggle('show', musicInput.value.length > 0);
  });
  musicClear.addEventListener('click', function() {
    musicInput.value = '';
    musicClear.classList.remove('show');
    musicInput.focus();
  });
  
  function handleMusicInput() {
    var input = $('#music-input').value.trim();
    if (!input) return;
    
    // 先尝试从输入中提取URL（支持含URL的文本）
    var url = extractUrl(input);
    
    if (url) {
      // 提取到URL，判断是单曲还是歌单
      if (isSingleSongUrl(url)) {
        parseSingleSong(url);
      } else {
        parsePlaylist(url);
      }
    } else {
      // 没有URL，走搜索流程
      doSearch(input);
    }
  }
  
  // 搜索歌曲
  function doSearch(keyword) {
    var btn = $('#music-btn');
    btn.disabled = true;
    
    var st = $('#music-status');
    st.style.display = 'block';
    st.innerHTML = '<span class="spinner"></span> 搜索中...';
    st.className = 'status-msg';
    $('#music-results').innerHTML = '';
    $('#playlist-preview').classList.remove('show');
    hideBulkBar();
    
    api('/api/search?keyword=' + encodeURIComponent(keyword) + '&count=30').then(function(data) {
      state.songs = data.songs || [];
      if (state.songs.length === 0) {
        st.innerHTML = '未找到相关结果';
      } else {
        st.style.display = 'none';
      }
      renderResults();
    }).catch(function(err) {
      st.innerHTML = '搜索失败：' + err.message;
      st.className = 'status-msg error';
    }).finally(function() { 
      btn.disabled = false; 
    });
  }
  
  // 解析歌单
  function parsePlaylist(url) {
    var btn = $('#music-btn');
    btn.disabled = true;
    
    var st = $('#music-status');
    st.style.display = 'block';
    st.innerHTML = '<span class="spinner"></span> 正在解析歌单...';
    st.className = 'status-msg';
    $('#music-results').innerHTML = '';
    $('#playlist-preview').classList.remove('show');
    hideBulkBar();
    
    api('/api/playlist', { method: 'POST', body: { url: url } }).then(function(data) {
      state.playlistSongs = data.songs;
      st.style.display = 'none';
      showPlaylistPreview(data);
    }).catch(function(err) {
      st.innerHTML = '解析失败：' + err.message;
      st.className = 'status-msg error';
    }).finally(function() { 
      btn.disabled = false; 
    });
  }
  
  // 解析单曲链接
  function parseSingleSong(url) {
    var btn = $('#music-btn');
    btn.disabled = true;
    
    var st = $('#music-status');
    st.style.display = 'block';
    st.innerHTML = '<span class="spinner"></span> 正在解析单曲...';
    st.className = 'status-msg';
    $('#music-results').innerHTML = '';
    $('#playlist-preview').classList.remove('show');
    hideBulkBar();
    
    api('/api/song-info', { method: 'POST', body: { url: url } }).then(function(data) {
      st.style.display = 'none';
      // 将单曲信息渲染为搜索结果，用户可以点击下载
      state.songs = [data.song];
      renderResults();
      toast('解析成功，点击下载按钮下载', 'success');
    }).catch(function(err) {
      st.innerHTML = '解析失败：' + err.message;
      st.className = 'status-msg error';
    }).finally(function() { 
      btn.disabled = false; 
    });
  }
  
  // ========== 渲染搜索结果 ==========
  function renderResults() {
    var container = $('#music-results');
    
    if (state.songs.length === 0) {
      container.innerHTML = '<div class="status-msg">未找到相关结果</div>';
      return;
    }
    
    var icons = { netease: 'music', qq: 'music', kugou: 'music', migu: 'music' };
    
    container.innerHTML = state.songs.map(function(s) {
      var icon = icons[s.platform] || 'music';
      return '<div class="song-card" data-id="' + s.song_id + '" data-platform="' + s.platform + '">' +
        '<div class="song-cover ' + s.platform + '"><i data-lucide="' + icon + '"></i></div>' +
        '<div class="song-info">' +
          '<div class="song-title" title="' + escAttr(s.title) + '">' + escHtml(s.title) + '</div>' +
          '<div class="song-meta">' + escHtml(s.artist) + (s.album ? ' · ' + escHtml(s.album) : '') + '</div>' +
        '</div>' +
        '<div class="song-actions">' +
          '<button class="dl-btn" data-action="download" data-id="' + s.song_id + '" data-title="' + escAttr(s.title) + '" data-artist="' + escAttr(s.artist) + '" data-platform="' + s.platform + '" title="下载"><i data-lucide="download"></i></button>' +
        '</div>' +
      '</div>';
    }).join('');
    
    // 初始化新添加的Lucide图标
    lucide.createIcons();
    
    // 绑定卡片点击事件（批量选择）
    $$('.song-card').forEach(function(card) {
      card.addEventListener('click', function(e) {
        if (e.target.closest('.dl-btn')) return;
        var id = card.dataset.id;
        if (state.selectedSongs[id]) { 
          delete state.selectedSongs[id]; 
          card.classList.remove('selected'); 
        } else { 
          state.selectedSongs[id] = true; 
          card.classList.add('selected'); 
        }
        updateBulkBar();
      });
      
      if (state.selectedSongs[card.dataset.id]) {
        card.classList.add('selected');
      }
      
      // 恢复下载状态（仅对音乐面板内的卡片）
      var dlBtn = card.querySelector('.dl-btn');
      if (dlBtn) {
        var task = state.downloading[dlBtn.dataset.id];
        if (task) updateDlBtn(dlBtn, task);
      }
    });
    
    // 绑定下载按钮
    $$('.dl-btn').forEach(function(btn) {
      btn.addEventListener('click', function(e) {
        e.stopPropagation();
        handleDownload(btn);
      });
    });
  }
  
  // ========== 下载处理 ==========
  function handleDownload(btn) {
    var id = btn.dataset.id;
    if (state.downloading[id] && state.downloading[id].status === 'downloading') return;
    
    btn.disabled = true;
    btn.classList.add('dl-spin');
    var card = btn.closest('.song-card');
    if (card) card.classList.add('downloading');
    
    api('/api/download', {
      method: 'POST',
      body: {
        title: btn.dataset.title,
        artist: btn.dataset.artist,
        platform: btn.dataset.platform,
        song_id: id
      }
    }).then(function(data) {
      state.downloading[id] = { status: 'downloading', task_id: data.task_id };
      pollDownload(id, btn);
    }).catch(function(err) {
      btn.classList.remove('dl-spin');
      btn.classList.add('dl-fail');
      btn.disabled = false;
      if (card) { card.classList.remove('downloading'); card.classList.add('failed'); }
      toast('下载失败：' + err.message, 'error');
    });
  }
  
  function pollDownload(id, btn) {
    var task = state.downloading[id];
    if (!task) return;
    
    var card = btn.closest('.song-card');
    
    api('/api/download/' + task.task_id).then(function(info) {
      task.status = info.status;
      task.filename = info.filename;
      updateDlBtn(btn, task);
      
      if (card) {
        card.classList.remove('downloading');
        if (info.status === 'done') card.classList.add('done');
        if (info.status === 'failed') card.classList.add('failed');
      }
      
      if (info.status === 'done') {
        toast('下载完成：' + info.filename, 'success');
        if (state.activeTab === 'files') refreshFiles();
      } else if (info.status === 'failed') {
        toast('下载失败：' + (info.error || '未知错误'), 'error');
      } else if (info.status === 'downloading') {
        setTimeout(function() { pollDownload(id, btn); }, 1500);
      }
    }).catch(function() {
      setTimeout(function() { pollDownload(id, btn); }, 1500);
    });
  }
  
  function updateDlBtn(btn, task) {
    btn.classList.remove('dl-spin');
    btn.disabled = false;
    if (task.status === 'done') { 
      btn.classList.add('dl-ok'); 
      btn.title = '已下载'; 
    } else if (task.status === 'failed') { 
      btn.classList.add('dl-fail'); 
      btn.title = '下载失败'; 
    } else { 
      btn.classList.add('dl-spin'); 
      btn.disabled = true; 
    }
  }
  
  // ========== 批量操作 ==========
  function hideBulkBar() { 
    state.selectedSongs = {}; 
    $('#bulk-bar').classList.remove('show'); 
  }
  
  function updateBulkBar() {
    var bar = $('#bulk-bar');
    var count = Object.keys(state.selectedSongs).length;
    if (count === 0) { 
      bar.classList.remove('show'); 
      return; 
    }
    bar.classList.add('show');
    $('#bulk-count').textContent = '已选 ' + count + ' 首';
  }
  
  $('#bulk-clear').addEventListener('click', hideBulkBar);
  
  $('#bulk-download').addEventListener('click', function() {
    var toDownload = state.songs.filter(function(s) { return state.selectedSongs[s.song_id]; });
    hideBulkBar();
    toDownload.forEach(function(s) {
      var btn = document.querySelector('.dl-btn[data-id="' + s.song_id + '"]');
      if (btn && !(state.downloading[s.song_id] && state.downloading[s.song_id].status === 'downloading')) {
        handleDownload(btn);
      }
    });
  });
  
  // ========== 歌单预览 ==========
  $('#pl-clear').addEventListener('click', function() {
    $('#playlist-preview').classList.remove('show');
    state.playlistSongs = null;
  });
  
  function showPlaylistPreview(data) {
    var preview = $('#playlist-preview');
    preview.classList.add('show');
    
    $('#pl-name').textContent = data.name;
    $('#pl-meta').textContent = data.song_count + ' 首 · ' + data.platform;
    
    var list = $('#pl-songs');
    list.innerHTML = data.songs.map(function(s, i) {
      return '<div class="pl-song">' +
        '<span class="pl-song-idx">' + (i + 1) + '</span>' +
        '<span class="pl-song-title">' + escHtml(s.title) + '</span>' +
        '<span class="pl-song-artist">' + escHtml(s.artist) + '</span>' +
      '</div>';
    }).join('');
    
    $('#pl-download-all').onclick = function() { downloadPlaylistSongs(data.songs); };
  }
  
  function downloadPlaylistSongs(songs) {
    $('#playlist-preview').classList.remove('show');
    state.playlistSongs = null;
    state.songs = songs;
    renderResults();
    
    songs.forEach(function(s, i) {
      setTimeout(function() {
        var btn = document.querySelector('.dl-btn[data-id="' + s.song_id + '"]');
        if (btn && !(state.downloading[s.song_id] && state.downloading[s.song_id].status === 'downloading')) {
          handleDownload(btn);
        }
      }, i * 300);
    });
  }