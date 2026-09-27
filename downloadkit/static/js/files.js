// ========== 文件管理 ==========
  // 文件分类图标映射
  var categoryIcons = {
    'music': 'music',
    'videos': 'film',
    'images': 'image',
    'animated': 'sparkles',
    'others': 'file'
  };
  
  // 选中的文件
  var selectedFiles = {};
  
  function refreshFiles() {
    var st = $('#files-status');
    var listEl = $('#files-list');
    var emptyEl = $('#files-empty');
    
    api('/api/files').then(function(data) {
      state.files = data.files || [];
      
      // 裁剪选中：刷新后已删除/不再存在的文件不许继续留在选中集里，
      // 否则「删除选中 (N)」会一直挂着旧计数（Bug⑤）
      var pruned = {};
      state.files.forEach(function(f) {
        if (selectedFiles[f.path]) pruned[f.path] = true;
      });
      selectedFiles = pruned;
      
      if (state.files.length === 0) {
        listEl.innerHTML = '';
        emptyEl.style.display = 'block';
        st.style.display = 'none';
        // 空列表也要复位全选框和工具栏计数，不能停在上一次的「删除选中 (N)」
        $('#select-all').checked = false;
        $('#select-all').indeterminate = false;
        updateFilesToolbar();
        return;
      }
      
      emptyEl.style.display = 'none';
      st.style.display = 'none';
      
      // 按分类分组
      var groups = {};
      var categoryOrder = ['music', 'videos', 'images', 'animated', 'others'];
      
      state.files.forEach(function(f) {
        var category = f.category || 'others';
        if (!groups[category]) {
          groups[category] = {
            label: f.category_label || '其他',
            files: []
          };
        }
        groups[category].files.push(f);
      });
      
      // 渲染分组
      var html = '';
      
      categoryOrder.forEach(function(category) {
        if (!groups[category]) return;
        
        var group = groups[category];
        var icon = categoryIcons[category] || 'file';
        
        html += '<div class="file-group">';
        html += '<div class="file-group-header">';
        html += '<i data-lucide="' + icon + '"></i>';
        html += '<span>' + group.label + '</span>';
        html += '<span class="file-group-count">' + group.files.length + '</span>';
        html += '</div>';
        html += '<div class="file-group-list">';
        
        group.files.forEach(function(f) {
          // 优先按category检测图标，再按扩展名
          var icon;
          if (f.category === 'animated') {
            icon = 'sparkles';
          } else if (f.name.endsWith('.mp4') || f.name.endsWith('.webm') || f.name.endsWith('.mov')) {
            icon = 'film';
          } else if (f.name.endsWith('.jpg') || f.name.endsWith('.jpeg') || f.name.endsWith('.png') || f.name.endsWith('.webp') || f.name.endsWith('.gif')) {
            icon = 'image';
          } else {
            icon = 'music';
          }
          var meta = fmtSize(f.size);
          var date = new Date(f.time * 1000);
          meta += ' · ' + date.toLocaleDateString();
          // 实况照片额外标记
          if (f.category === 'animated') {
            meta += ' · <span style="color:#5856D6;font-weight:500">实况照片</span>';
          }
          
          html += '<div class="file-row" data-path="' + escAttr(f.path) + '">';
          html += '<div class="file-checkbox"><input type="checkbox" class="file-select" data-path="' + escAttr(f.path) + '"></div>';
          html += '<div class="file-icon"><i data-lucide="' + icon + '"></i></div>';
          html += '<div class="file-info">';
          html += '<div class="file-name" title="' + escAttr(f.name) + '">' + escHtml(f.name) + '</div>';
          html += '<div class="file-meta">' + meta + '</div>';
          html += '</div>';
          html += '<button class="icon-btn file-delete-btn" data-path="' + escAttr(f.path) + '" title="删除"><i data-lucide="trash-2"></i></button>';
          html += '</div>';
        });
        
        html += '</div></div>';
      });
      
      listEl.innerHTML = html;
      
      // 初始化新添加的Lucide图标
      lucide.createIcons();
      
      // 绑定文件行点击事件（打开目录）
      $$('.file-row', listEl).forEach(function(row) {
        row.addEventListener('click', function(e) {
          // 如果点击的是复选框或删除按钮，不触发打开目录
          if (e.target.closest('.file-checkbox') || e.target.closest('.file-delete-btn')) return;
          openFileDir(row.dataset.path);
        });
      });
      
      // 绑定复选框事件
      $$('.file-select', listEl).forEach(function(checkbox) {
        checkbox.addEventListener('change', function() {
          toggleFileSelect(checkbox.dataset.path, checkbox.checked);
        });
      });
      
      // 恢复仍有效的勾选（重绘出来的框默认全不勾，勾选状态存在 selectedFiles 里）
      var visibleSelected = 0;
      $$('.file-select', listEl).forEach(function(checkbox) {
        if (selectedFiles[checkbox.dataset.path]) {
          checkbox.checked = true;
          visibleSelected++;
        }
      });
      var allBox = $('#select-all');
      allBox.checked = visibleSelected > 0 && visibleSelected === state.files.length;
      allBox.indeterminate = visibleSelected > 0 && visibleSelected < state.files.length;
      updateFilesToolbar();
      
      // 绑定单文件删除按钮事件
      $$('.file-delete-btn', listEl).forEach(function(btn) {
        btn.addEventListener('click', async function(e) {
          e.stopPropagation();  // 阻止冒泡，避免触发打开目录
          var filepath = btn.dataset.path;
          if (await uiConfirm('确定删除此文件？')) {
            api('/api/files/batch-delete', { method: 'POST', body: { files: [filepath] } })
              .then(function(result) {
                if (result.deleted && result.deleted.length > 0) {
                  toast('已删除', 'success');
                  // 单删也要同步移出选中集，否则计数残留
                  delete selectedFiles[filepath];
                  updateFilesToolbar();
                  refreshFiles();
                } else {
                  toast('删除失败', 'error');
                }
              })
              .catch(function(err) {
                toast('删除失败：' + err.message, 'error');
              });
          }
        });
      });
    }).catch(function(err) {
      st.style.display = 'block';
      st.innerHTML = '加载文件列表失败';
      st.className = 'status-msg error';
    });
  }
  
  // 打开文件所在目录
  function openFileDir(filepath) {
    api('/api/open-dir', { method: 'POST', body: { path: filepath } })
      .then(function(data) {
        if (data.status === 'headless') {
          showRemotePathDialog(data);
        } else {
          toast('已打开目录', 'info');
        }
      })
      .catch(function(err) {
        toast('打开目录失败：' + err.message, 'error');
      });
  }
  
  // 容器环境下展示路径信息弹窗
  function showRemotePathDialog(info) {
    // 移除已有弹窗
    var old = document.querySelector('.remote-path-overlay');
    if (old) old.remove();
    
    var overlay = document.createElement('div');
    overlay.className = 'remote-path-overlay';
    
    var modal = document.createElement('div');
    modal.className = 'remote-path-modal';
    
    var paths = [];
    if (info.nas_path) {
      paths.push({ label: 'NAS 文件路径', value: info.nas_path, icon: 'hard-drive' });
    }
    if (info.smb_path) {
      paths.push({ label: 'SMB 网络路径 (Windows)', value: info.smb_path, icon: 'network' });
    }
    if (info.path) {
      paths.push({ label: '容器内路径', value: info.path, icon: 'terminal' });
    }
    
    var pathRows = paths.map(function(p) {
      return '<div class="remote-path-row">' +
        '<div class="remote-path-label"><i data-lucide="' + p.icon + '" class="remote-path-icon"></i>' + escHtml(p.label) + '</div>' +
        '<div class="remote-path-value-wrap">' +
          '<code class="remote-path-value" id="rp-value-' + escAttr(p.label) + '">' + escHtml(p.value) + '</code>' +
          '<button class="icon-btn remote-path-copy" data-copy="' + escAttr(p.value) + '" title="复制"><i data-lucide="copy"></i></button>' +
        '</div>' +
      '</div>';
    }).join('');
    
    modal.innerHTML =
      '<div class="remote-path-header">' +
        '<h4 class="remote-path-title"><i data-lucide="folder-open"></i> ' + escHtml(info.title || '目录位置') + '</h4>' +
        '<button class="icon-btn remote-path-close" id="rp-close" title="关闭"><i data-lucide="x"></i></button>' +
      '</div>' +
      '<div class="remote-path-body">' +
        '<p class="remote-path-hint">' + escHtml(info.hint || '该目录在 NAS 上的位置：') + '</p>' +
        pathRows +
      '</div>' +
      '<div class="remote-path-footer">' +
        '<button class="btn btn-secondary" id="rp-close-btn">关闭</button>' +
      '</div>';
    
    overlay.appendChild(modal);
    document.body.appendChild(overlay);
    lucide.createIcons();
    
    // 关闭
    function closeDialog() { overlay.remove(); }
    $('#rp-close').addEventListener('click', closeDialog);
    $('#rp-close-btn').addEventListener('click', closeDialog);
    overlay.addEventListener('click', function(e) {
      if (e.target === overlay) closeDialog();
    });
    
    // 复制到剪贴板
    $$('.remote-path-copy', modal).forEach(function(btn) {
      btn.addEventListener('click', function() {
        var val = btn.dataset.copy;
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(val).then(function() {
            toast('已复制到剪贴板', 'success');
          }).catch(function() {
            fallbackCopy(val);
          });
        } else {
          fallbackCopy(val);
        }
      });
    });
    
    function fallbackCopy(text) {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand('copy');
        toast('已复制到剪贴板', 'success');
      } catch (e) {
        toast('复制失败，请手动复制', 'error');
      }
      document.body.removeChild(ta);
    }
  }
  
  // 切换文件选中状态
  function toggleFileSelect(filepath, checked) {
    if (checked) {
      selectedFiles[filepath] = true;
    } else {
      delete selectedFiles[filepath];
    }
    updateFilesToolbar();
  }
  
  // 更新工具栏状态
  function updateFilesToolbar() {
    var count = Object.keys(selectedFiles).length;
    var deleteBtn = $('#files-delete-selected');
    deleteBtn.disabled = count === 0;
    deleteBtn.innerHTML = '<i data-lucide="trash-2"></i> 删除选中' + (count > 0 ? ' (' + count + ')' : '');
    lucide.createIcons();
  }
  
  // 全选/取消全选
  $('#select-all').addEventListener('change', function() {
    var checked = this.checked;
    $$('.file-select').forEach(function(checkbox) {
      checkbox.checked = checked;
      toggleFileSelect(checkbox.dataset.path, checked);
    });
  });
  
  // 批量删除选中文件
  $('#files-delete-selected').addEventListener('click', async function() {
    var files = Object.keys(selectedFiles);
    if (files.length === 0) return;
    
    if (!(await uiConfirm('确定删除选中的 ' + files.length + ' 个文件？'))) return;
    
    api('/api/files/batch-delete', { method: 'POST', body: { files: files } })
      .then(function(result) {
        toast('已删除 ' + result.deleted.length + ' 个文件', 'success');
        selectedFiles = {};
        $('#select-all').checked = false;
        refreshFiles();
      })
      .catch(function(err) {
        toast('删除失败：' + err.message, 'error');
      });
  });
  
  // 打开下载目录
  $('#files-open-dir').addEventListener('click', function() {
    openFileDir('');
  });