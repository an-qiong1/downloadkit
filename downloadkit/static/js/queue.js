// ========== 下载队列模块 ==========
  var queueRefreshTimer = null;
  
  // 任务下载速度追踪 (bytes, time, speed)
  var _taskSpeeds = {};
  
  function formatSpeed(bytesPerSec) {
    if (bytesPerSec <= 0) return '--';
    if (bytesPerSec >= 1048576) {
      return (bytesPerSec / 1048576).toFixed(1) + ' MB/s';
    }
    return Math.round(bytesPerSec / 1024) + ' KB/s';
  }
  
  function formatETA(seconds) {
    if (seconds <= 0 || !isFinite(seconds)) return '--';
    if (seconds >= 60) {
      var m = Math.floor(seconds / 60);
      var s = Math.floor(seconds % 60);
      return m + '分' + s + '秒';
    }
    return Math.floor(seconds) + '秒';
  }
  
  function refreshQueue() {
    api('/api/queue/status').then(function(data) {
      // 更新统计
      $('#queue-downloading').textContent = data.downloading || 0;
      $('#queue-pending').textContent = data.pending || 0;
      $('#queue-completed').textContent = data.completed || 0;
      // 失败计数与批量重试按钮同显隐：没失败时按钮毫无用处，
      // 留着常亮只会让人点了个寂寞
      var failedCount = data.failed || 0;
      $('#queue-failed').textContent = failedCount;
      $('#queue-failed-stat').style.display = failedCount > 0 ? '' : 'none';
      $('#queue-retry-failed').style.display = failedCount > 0 ? '' : 'none';
      
      var listEl = $('#queue-list');
      var emptyEl = $('#queue-empty');
      
      var tasks = data.tasks || [];
      
      if (tasks.length === 0) {
        listEl.innerHTML = '';
        emptyEl.style.display = 'block';
        return;
      }
      
      emptyEl.style.display = 'none';
      
      // 计算每个任务的瞬时下载速度
      var speedNow = Date.now();
      tasks.forEach(function(task) {
        var prev = _taskSpeeds[task.task_id];
        if (!prev) {
          _taskSpeeds[task.task_id] = { bytes: task.downloaded_size || 0, time: speedNow, speed: 0 };
        } else {
          var dt = (speedNow - prev.time) / 1000;
          if (dt > 0 && task.downloaded_size >= prev.bytes) {
            prev.speed = (task.downloaded_size - prev.bytes) / dt;
          } else if (dt > 0 && task.downloaded_size < prev.bytes) {
            prev.speed = 0;
          }
          prev.bytes = task.downloaded_size || 0;
          prev.time = speedNow;
        }
      });
      // 清理已移除任务的速度记录
      var activeTaskIds = {};
      tasks.forEach(function(t) { activeTaskIds[t.task_id] = true; });
      Object.keys(_taskSpeeds).forEach(function(id) {
        if (!activeTaskIds[id]) delete _taskSpeeds[id];
      });
      
      var platformIcons = {
        'douyin': 'film',
        'bilibili': 'tv',
        'youtube': 'youtube',
        'xiaohongshu': 'book-open'
      };
      
      var statusIcons = {
        'downloading': 'download',
        'pending': 'clock',
        'completed': 'check',
        'failed': 'alert-circle',
        'paused': 'pause',
        'cancelled': 'x'
      };
      
      var html = '';
      tasks.forEach(function(task) {
        var icon = platformIcons[task.platform] || 'film';
        var statusIcon = statusIcons[task.status] || 'clock';
        var progress = Math.round(task.progress * 100);
        var isDone = task.status === 'completed';
        
        html += '<div class="queue-item' + (isDone ? ' queue-item-done' : '') + '" data-task-id="' + task.task_id + '"' +
                (isDone ? ' title="点击打开文件"' : '') + '>';
        html += '<div class="queue-item-icon ' + task.status + '"><i data-lucide="' + statusIcon + '"></i></div>';
        html += '<div class="queue-item-info">';
        html += '<div class="queue-item-title">' + escHtml(task.title || '未知任务') + '</div>';
        html += '<div class="queue-item-meta">' + task.platform + ' · ' + progress + '%</div>';
        
        if (task.status === 'downloading' || task.status === 'paused') {
          html += '<div class="queue-item-progress">';
          html += '<div class="queue-item-progress-bar ' + task.status + '" style="width:' + progress + '%"></div>';
          html += '</div>';
        }
        
        // 计算并显示下载速度和剩余时间
        if (task.status === 'downloading') {
          var speedData = _taskSpeeds[task.task_id] || { speed: 0 };
          var speed = speedData.speed || 0;
          var speedText = task.downloaded_size > 0 ? formatSpeed(speed) : '--';
          var etaText = '--';
          if (speed > 0 && task.file_size > 0) {
            var remaining = task.file_size - task.downloaded_size;
            if (remaining > 0) {
              etaText = formatETA(remaining / speed);
            }
          }
          html += '<div class="queue-item-speed">';
          html += '<span class="task-speed">' + speedText + '</span>';
          html += '<span class="task-eta">' + etaText + '</span>';
          html += '</div>';
        }
        
        html += '</div>';
        html += '<div class="queue-item-actions">';
        
        if (task.status === 'downloading') {
          html += '<button class="icon-btn" data-action="pause" data-task-id="' + task.task_id + '" title="暂停"><i data-lucide="pause"></i></button>';
          html += '<button class="icon-btn danger" data-action="cancel" data-task-id="' + task.task_id + '" title="取消"><i data-lucide="x"></i></button>';
        } else if (task.status === 'paused') {
          html += '<button class="icon-btn" data-action="resume" data-task-id="' + task.task_id + '" title="恢复"><i data-lucide="play"></i></button>';
          html += '<button class="icon-btn danger" data-action="cancel" data-task-id="' + task.task_id + '" title="取消"><i data-lucide="x"></i></button>';
        } else if (task.status === 'failed') {
          html += '<button class="icon-btn" data-action="retry" data-task-id="' + task.task_id + '" title="重试"><i data-lucide="refresh-cw"></i></button>';
        }
        
        html += '</div>';
        html += '</div>';
      });
      
      listEl.innerHTML = html;
      lucide.createIcons();
      
      // 绑定按钮事件
      $$('.queue-item-actions .icon-btn', listEl).forEach(function(btn) {
        btn.addEventListener('click', async function() {
          var action = btn.dataset.action;
          var taskId = btn.dataset.taskId;
          
          if (action === 'pause') {
            api('/api/queue/' + taskId + '/pause', { method: 'POST' }).then(function() {
              refreshQueue();
            });
          } else if (action === 'resume') {
            api('/api/queue/' + taskId + '/resume', { method: 'POST' }).then(function() {
              refreshQueue();
            });
          } else if (action === 'cancel') {
            if (await uiConfirm('确定取消此下载？')) {
              api('/api/queue/' + taskId + '/cancel', { method: 'POST' }).then(function() {
                refreshQueue();
              });
            }
          } else if (action === 'retry') {
            api('/api/queue/' + taskId + '/retry', { method: 'POST' }).then(function() {
              refreshQueue();
              toast('任务已重新加入队列', 'success');
            }).catch(function(err) {
              toast('重试失败：' + err.message, 'error');
            });
          }
        });
      });
      
      // 绑定完成项行点击：打开文件，成功后把它移出「进行中」列表（Bug⑥）
      var taskById = {};
      tasks.forEach(function(t) { taskById[t.task_id] = t; });
      $$('.queue-item', listEl).forEach(function(row) {
        row.addEventListener('click', function(e) {
          if (e.target.closest('.queue-item-actions')) return;
          var task = taskById[row.dataset.taskId];
          if (!task || task.status !== 'completed') return;
          openCompletedTask(task);
        });
      });
    }).catch(function(err) {
      console.error('获取队列状态失败:', err);
    });
  }
  
  // 打开已完成任务的文件，成功后把它移出「进行中」列表
  function openCompletedTask(task) {
    if (!task.filename) {
      toast('该任务没有记录文件名，无法打开', 'error');
      return;
    }
    api('/api/open-file', { method: 'POST', body: { path: task.filename } })
      .then(function(data) {
        if (data.status === 'headless') {
          // 容器环境：给出 NAS 路径，由弹窗展示
          showRemotePathDialog(data);
        } else {
          toast('已打开文件', 'success');
        }
        return api('/api/queue/' + task.task_id + '/dismiss', { method: 'POST' });
      })
      .then(function() {
        refreshQueue();
      })
      .catch(function(err) {
        toast('打开文件失败：' + err.message, 'error');
      });
  }
  
  // 刷新队列按钮
  $('#queue-refresh').addEventListener('click', refreshQueue);

  // 一键重试全部失败（P3-2）
  // orphaned = 失败太久已被清理出队列的任务（见 api_retry_failed 注释），
  // 它们统计得出来但重发不了，必须跟用户说明白，不然点了像没反应
  $('#queue-retry-failed').addEventListener('click', async function() {
    if (!(await uiConfirm('重试所有失败任务？'))) return;
    api('/api/queue/retry-failed', { method: 'POST' }).then(function(r) {
      var n = r.retried || 0;
      var msg = n > 0 ? ('已重新加入 ' + n + ' 个任务') : '没有可重试的任务';
      if (r.orphaned > 0) {
        msg += '；' + r.orphaned + ' 个失败任务已过期被自动清理，无法重试';
      }
      toast(msg, n > 0 ? 'success' : 'error');
      refreshQueue();
    }).catch(function(err) {
      toast('重试失败：' + err.message, 'error');
    });
  });
  
  // 自动刷新队列状态
  function startQueueAutoRefresh() {
    if (queueRefreshTimer) clearInterval(queueRefreshTimer);
    queueRefreshTimer = setInterval(function() {
      if (state.activeTab === 'downloads' && state.downloadView === 'queue') {
        refreshQueue();
      }
    }, 2000);
  }