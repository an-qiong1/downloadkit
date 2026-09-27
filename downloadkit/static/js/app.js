(function() {
  'use strict';
  
  // ========== 侧边栏切换 ==========
  function switchTab(tab) {
    var navItem = $('.nav-item[data-tab="' + tab + '"]');
    if (navItem && navItem.classList.contains('disabled')) {
      return;
    }
    
    state.activeTab = tab;
    
    $$('.nav-item').forEach(function(item) {
      item.classList.toggle('active', item.dataset.tab === tab);
    });
    
    $$('.tab-panel').forEach(function(panel) {
      panel.classList.toggle('active', panel.id === 'panel-' + tab);
    });
    
    $('#page-title').textContent = tabTitles[tab] || tab;
    
    if (tab === 'downloads') {
      // 「下载」页有子视图（进行中/已完成），只刷新当前那个
      refreshDownloadView();
    }
    
    if (tab === 'settings') {
      if (typeof loadSettings === 'function') loadSettings();
    }
    
    closeSidebar();
  }
  
  // ========== 「下载」页子视图（进行中 / 已完成）==========
  function refreshDownloadView() {
    if (state.downloadView === 'files') {
      refreshFiles();
    } else {
      refreshQueue();
    }
  }
  
  function switchDownloadView(view) {
    if (view !== 'queue' && view !== 'files') view = 'queue';
    state.downloadView = view;
    
    $$('.dl-subtab').forEach(function(btn) {
      var on = btn.dataset.view === view;
      btn.classList.toggle('active', on);
      btn.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    
    var queueView = $('#dl-view-queue');
    var filesView = $('#dl-view-files');
    if (queueView) queueView.style.display = view === 'queue' ? '' : 'none';
    if (filesView) filesView.style.display = view === 'files' ? '' : 'none';
    
    refreshDownloadView();
  }
  
  $$('.dl-subtab').forEach(function(btn) {
    btn.addEventListener('click', function() {
      switchDownloadView(btn.dataset.view);
    });
  });
  
  $$('.nav-item').forEach(function(item) {
    item.addEventListener('click', function() {
      switchTab(item.dataset.tab);
    });
  });
  
  // ========== 移动端侧边栏 ==========
  function openSidebar() {
    $('#sidebar').classList.add('open');
    $('#sidebar-overlay').classList.add('show');
  }
  
  function closeSidebar() {
    $('#sidebar').classList.remove('open');
    $('#sidebar-overlay').classList.remove('show');
  }
  
  $('#menu-btn').addEventListener('click', openSidebar);
  $('#sidebar-overlay').addEventListener('click', closeSidebar);
  
  // ========== 初始化 ==========
  lucide.createIcons();
  
  refreshFiles();
  startQueueAutoRefresh();
})();
